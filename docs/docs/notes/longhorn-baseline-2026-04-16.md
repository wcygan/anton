# Longhorn baseline — 2026-04-16

Phase 3 acceptance artifact for [plan 0001 — Adopt Longhorn as replicated block storage](https://github.com/wcygan/anton/blob/main/context/plans/0001-adopt-longhorn-block-storage.md). This is the **reference bar** against which the ADR 0009 SFP+ 10 Gbit cutover (delivered by [plan 0004](https://github.com/wcygan/anton/blob/main/context/plans/0004-sfp-mesh-multus-storagenetwork.md), closed 2026-04-19) demonstrates improvement.

> **Update 2026-04-19 — cutover landed.** Plan 0004 closed today. Longhorn `defaultSettings.storageNetwork: storage/longhorn-storage` is live on a macvlan/bridge NAD over a `vxlan-storage` overlay (VNI 100, 10.100.1.0/24) on the SFP+ /31 mesh, with a `lhnet1-host` macvlan host-shim child that gives the host iSCSI initiator a path to co-located IM pods. Phase 5 throughput burst (10 GiB urandom dd, 2-replica volume): SFP+ ports carried **~790 Mbps TX / ~988 Mbps RX**, 2.5 GbE management interface saw **&lt;2 Mbps** of Longhorn traffic. dd was urandom-bound at **146 MiB/s** (~1.2 Gbps payload, CPU not network) so this isn't the achievable replica ceiling — a non-urandom write source plus the higher-fanout rebuild path are needed to hit the actual SFP+ ceiling. Plan 0004 Log 2026-04-19 has the full forensics, including the two failed NAD plugin attempts (macvlan-on-parent and ipvlan-L2-on-parent) before the host-shim landed.

## Cluster shape at measurement time

- Longhorn chart `1.11.1`, Helm-installed in `storage` namespace
- `defaultReplicaCount: 2`, `defaultDataLocality: best-effort`, `staleReplicaTimeout: 2880`
- 5 declared data NVMes (WD_BLACK SN7100 1 TB) in asymmetric 2+1+2 layout — k8s-1: 2, k8s-2: 1, k8s-3: 2
- Raw capacity ~4.58 TiB, usable ~2.29 TiB at 2-replica
- Network: **2.5 GbE per node** (no Multus `storageNetwork`, no SFP+ mesh — that's ADR 0009 / future plan)
- Talos v1.12.6, kernel 6.18.18-talos, kubelet bind-mounts `/var/mnt/longhorn-{1,2}` with `rshared`

## Smoke test

**Namespace**: `longhorn-smoke` (torn down post-test). **PVC**: `bench-pvc`, 5 GiB on `longhorn` SC.

1. Writer pod wrote a deterministic 128 MiB payload + 60-line heartbeat log. SHA256 captured: `5d8b4...`.
2. Replicas materialised on **k8s-1 + k8s-3**. k8s-2 (single-disk) not elected — this is the expected skew from the asymmetric 2+1+2 topology and is acceptable until the k8s-2 second-NVMe followup lands.
3. Engine placed on k8s-3; `dataLocality: best-effort` honored (reader pod co-scheduled).
4. Pod-recreate cycles preserved SHA256 exactly across multiple attach/detach transitions.

**Verdict**: PVC provisioning, replica placement, locality, and attach/detach all behave as expected.

## fio throughput baseline

Single 5 GiB PVC, engine on k8s-3 (local replica), remote replica on k8s-1. libaio, direct=1, 30s per workload, one workload at a time.

| Workload | Block size | Queue depth | Throughput | IOPS |
|---|---|---|---|---|
| seq-write | 1 MiB | 16 | 113 MB/s (108 MiB/s) | 108 |
| seq-read  | 1 MiB | 16 | **219 MB/s (209 MiB/s)** | 209 |
| rand-write | 4 KiB | 32 | 103 MB/s | **26.3k** |
| rand-read  | 4 KiB | 32 | 132 MB/s | **33.9k** |

**Reads** hit ~70% of 2.5 GbE theoretical (~312 MB/s). With `best-effort` locality the reader serves from the local replica, so read ceiling is NVMe-bound once cache is warm; cold reads pull from the local sparse file on k8s-3's WD_BLACK.

**Writes** are network-bound on the synchronous replication fan-out to k8s-1 — Longhorn waits for all replicas to ack before acknowledging the write. 113 MB/s is ~45% of wire; remaining budget is iSCSI framing + TCP + Longhorn-engine overhead.

**Random IOPS** are strong for a sync-replicated distributed block system at this scale — 26.3k write / 33.9k read at 4 KiB gives healthy headroom for database-shaped workloads (Postgres, etcd-outside-k8s, app state stores).

## Reboot failover test

Controlled `talosctl reboot` against **k8s-1** (non-engine for this volume, non-etcd-leader) at 19:48:46 UTC. Volume remained attached to a long-lived keepalive pod pinned to k8s-3 throughout.

| t+ | Event |
|---|---|
| +5s  | k8s-1 `NotReady` |
| +10s | Longhorn volume `Robustness: degraded` (k8s-1 replica unavailable) |
| +30s | k8s-1 `Ready` again (Talos boot is fast) |
| +65s | Volume `Robustness: healthy` — remote replica reattached from existing sparse file |

**Total degraded window: ~55 seconds.** Engine stayed pinned to k8s-3; workload I/O uninterrupted. Stale-replica timeout (2880s) never tripped, so the replica **reattached** rather than rebuilt — **zero rebuild traffic over the 2.5 GbE fabric**. Post-reboot SHA256 and heartbeat log both intact: **zero data loss**.

This is the baseline for the failover-without-rebuild path. A rebuild-forced test (kill replica, let Longhorn re-create it) is the other half of the envelope; not captured in this pass — plan 0002 or an ADR 0009 cutover measurement should cover it, since the rebuild path is what actually stresses 2.5 GbE vs SFP+.

## What this means for ADR 0009

The SFP+ 10 Gbit `storageNetwork` cutover (ADR 0009) has two jobs on the throughput axis:

1. Lift the **write ceiling** — 113 MB/s today is wire-bound on sync fan-out; 10 Gbit should 3–4× this (ballpark).
2. Shrink the **rebuild window** when a replica *does* need re-creation (not measured here, but the dominant metric for ADR 0009's case).

Reads are already NVMe-bound once local, so the cutover won't help seq-read much — that's fine, reads aren't the bottleneck.

## Cleanup

`longhorn-smoke` namespace deleted (destructive-gate override required). Zero Longhorn volumes / zero PVCs cluster-wide post-teardown.

## Pointers

- Plan: `context/plans/0001-adopt-longhorn-block-storage.md`
- ADRs: 0005 (Longhorn decision), 0007 (kps install gate — **cleared** by this baseline), 0009 (SFP+ mesh — delivered via plan 0004, 2026-04-19), 0017 (Multus adoption), 0018 (install-cni init container)
- Hardware inventory: `context/hardware.md` (tracks k8s-2 missing 2nd NVMe)
- Longhorn skill pack: `.claude/skills/longhorn-{volume-ops,node-ops,backup-dr}/`
