---
name: Longhorn Phase 1 rollout complete (2026-04-16)
description: All 3 nodes upgraded to 445a99db schematic + 5 userVolumes provisioned + 5 kubelet extraMounts online; etcd leader migrated k8s-3→k8s-2 during k8s-3 reboot (raft term 26); Phase 1 complete 2026-04-16
type: project
---

## Outcome

Phase 1 canary on k8s-2 on 2026-04-16: **complete and healthy**.

- Schematic upgraded to `445a99db...:v1.12.6` (strictly additive; baseline i915/intel-ucode/tailscale preserved, new iscsi-tools v0.2.0 + util-linux-tools 2.41.2 added).
- `apply-config --mode=auto` landed userVolume + kubelet extraMounts online (no reboot).
- Initial `u-longhorn-1` provisioning failed because the WD_BLACK (serial `251021802221`) carried a leftover **bluestore** signature from a prior Rook/Ceph install (Talos refuses to auto-wipe disks with recognizable fs signatures — safety feature).
- `talosctl wipe disk nvme0n1 --method FAST` cleared the signature; volume controller auto-reprovisioned within ~5 seconds. `u-longhorn-1` phase transitioned `failed → ready`, partition `/dev/nvme0n1p1` ext4, mounted at `/var/mnt/longhorn-1`, kubelet bind-mount visible in `/proc/self/mountinfo`.
- Etcd quorum healthy throughout (k8s-3 leader, all 3 members HEALTH=OK).

**Total node-touch time: ~15 min, one reboot (the upgrade).**

## Key operational details (for k8s-1 / k8s-3 replays)

### `talosctl wipe disk` syntax (v1.12, verified 2026-04-16)

```
talosctl wipe disk <device names>... [--drop-partition] [--method FAST|ZEROES]
```

- **Arguments are device names (`nvme0n1`), not `/dev/...` paths.**
- `--method FAST` is the default and is effectively instant on NVMe (signature clear, no zero-fill).
- `--drop-partition` is only needed if you're wiping a specific partition and want it removed — **not** needed for whole-disk wipe when there's no partition table (e.g. bare bluestore). Not used on k8s-2; the wipe worked fine without it.
- **Wipe returns silently on success** (exit 0, no output). Don't interpret "no output" as "no-op". Verify with `talosctl get discoveredvolume <device>`.

### Pre-wipe validation pattern (safe, recommended)

Before every wipe, run these three reads to confirm you're pointed at the right disk:

1. `talosctl ... get disks <device>` — confirms the serial matches the declared Longhorn target (NOT the 500GB CT500P3 OS disk).
2. `talosctl ... get discoveredvolume <device> -o yaml` — confirms the fs signature (expect `name: bluestore` for prior-Rook disks; if anything else, stop and look).
3. `talosctl ... get mountstatus | grep <device>` — must be empty (not in use by any volume). Talos' wipe refuses in-use disks anyway, but check first.

### Post-wipe verification pattern

- `get discoveredvolume <device>` — `name` field should be `gpt` (Talos immediately partitions) or blank, NOT `bluestore`.
- `get volumestatus u-longhorn-N -o yaml` — `spec.phase: ready`, `filesystem: ext4`, `location: /dev/<device>p1`.
- `get mountstatus | grep longhorn-N` — entry present, `FILESYSTEM ext4`.
- `read /proc/self/mountinfo | grep longhorn-N` — expect TWO ext4 entries at `/var/mnt/longhorn-N`: one is the userVolume mount, one is the kubelet extraMounts bind. An additional xfs entry at the same path is normal — it's the ephemeral `/var/mnt` overmounted by the real partition. The topmost ext4 is what userspace sees.

### Device numbering flips — use serials, not nvmeXnY

k8s-2 has flipped device numbering across reboots at least twice (observed in the memory trail). Always drive from **serial**, not `nvme0n1`/`nvme1n1`. On k8s-2 as of 2026-04-16 post-upgrade: `nvme0n1` = WD_BLACK 251021802221 (data), `nvme1n1` = CT500P3 24304A23D2F0 (OS). The `talconfig.yaml` userVolume selector uses CEL `disk.serial == "251021802221"` which is stable regardless of device numbering.

### Extension stream oddity (cosmetic, not a bug)

`talosctl upgrade` emits `upgrade action: START`, several `phase:` lines, then the stream **closes mid-`phase: stopServices`** as the API goes down for reboot. The client returns exit 1 with the last stream frame — this is **expected** and NOT a failure. Confirm success by polling `talosctl ... version` afterward; extensions and schematic ID are the real proof.

## Implications for k8s-1 / k8s-3 (authorized per operator 2026-04-16)

- k8s-1 declared serials: `251021802186`, `251021802190` — both WD_BLACKs, both carried bluestore residue (confirmed 2026-04-16, both wiped successfully).
- k8s-3 declared serials: `251021800405`, `251021801882` — same expectation pending verification.
- Per-node sequence is now: upgrade → `wipe disk <two data nvmes>` → `apply-config --mode=auto` → verification. Plan updated (jj `nqspsxzq c06b7e04`).
- Order is unchanged: k8s-1 first (non-leader, 2 disks, COMPLETE 2026-04-16), then k8s-3 LAST (etcd leader; leadership will migrate off during its upgrade reboot).

## k8s-1 completion log (2026-04-16)

- Upgrade to 445a99db schematic: ~5 min from dispatch to healthy extensions. Same `stopServicesForUpgrade` stream close as k8s-2 (cosmetic).
- **Device renumbering was full-rotation this time:** pre-upgrade `nvme0n1,nvme1n1,nvme2n1` → post-upgrade `nvme1n1,nvme2n1,nvme0n1`. The OS disk moved from `nvme1n1` to `nvme2n1`. If I had trusted the operator's pre-reboot device names rather than re-verifying serials, I would have wiped the OS disk. **Always run `talosctl get disks <device>` by each candidate device name AFTER the upgrade reboot, before any wipe. Match on serial.**
- Both bluestore signatures cleared cleanly by `wipe disk --method FAST` (silent exit 0).
- Post-wipe, the disks sat `DISCOVERED` = blank (no gpt yet) — different from k8s-2 where the controller immediately repartitioned. Reason: on k8s-2 the userVolume config had already been applied before the wipe, so the controller partitioned immediately; on k8s-1 I wiped BEFORE apply-config, so disks stayed bare until apply-config landed. Both patterns are fine.
- `apply-config --mode=auto` applied without reboot. Both userVolumes (`u-longhorn-1`, `u-longhorn-2`) provisioned in parallel within ~5s. Both mount points (`/var/mnt/longhorn-1`, `/var/mnt/longhorn-2`) came up ext4 with kubelet bind overlays.
- Etcd quorum never degraded (k8s-1 etcd came back fast enough that by our first post-upgrade check, it was 15m healthy).
- Total node-touch: ~15-18 min.

## k8s-3 completion log (2026-04-16, Phase 1 finale)

- Upgrade to 445a99db: ~3 min from dispatch to healthy extensions (fastest of the three — k8s-3 has the smallest RAM footprint to re-init). Same cosmetic `stopServicesForUpgrade` stream close.
- **Etcd leader migrated off k8s-3 during the reboot** (k8s-3 was leader pre-upgrade). Post-reboot leader is `k8s-2` (ID `50beb6304d05dae3`), raft term incremented to 26, db 102MB, 25.66% in use. All 3 members returned HEALTH=OK within ~15s of k8s-3 coming back. Plan execution order (k8s-3 last) was correct — put the leader last so leadership only migrates once.
- **Device renumbering was partial-rotation:** pre-upgrade `nvme0n1,nvme1n1,nvme2n1` = `data-405, data-882, OS` → post-upgrade = `data-405, OS, data-882`. The OS disk moved from `nvme2n1` to `nvme1n1`. Wipe targets after re-verification-by-serial became `nvme0n1` + `nvme2n1` (NOT `nvme0n1` + `nvme1n1` as they were pre-reboot). Third data point confirming the protocol: always `get disks <device>` post-reboot before wiping.
- Both bluestore signatures cleared cleanly. Post-wipe disks remained `DISCOVERED` blank until `apply-config --mode=auto` landed (same pattern as k8s-1: wipe-before-apply → bare until config reconcile).
- `u-longhorn-1` (serial 251021800405) provisioned on `/dev/nvme0n1p1`, `u-longhorn-2` (serial 251021801882) on `/dev/nvme2n1p1`, both ext4, both kubelet-bind-mounted at `/var/mnt/longhorn-N`.

### k8s-3 OS partition layout anomaly (Phase 2 flag, not a Phase 1 blocker)

- k8s-1 and k8s-2 OS disk layout: **6 partitions** (EFI / BIOS / BOOT / META / STATE / EPHEMERAL) — BIOS-fallback capable.
- k8s-3 OS disk layout: **4 partitions** (EFI 1.2GB / META / STATE / EPHEMERAL) — pure UEFI, no BIOS partition, no BOOT partition.
- **Why this matters:** indicates k8s-3 was originally bootstrapped with a different installer image or a different factory config than k8s-1/k8s-2. Not causing any current issue (boots fine, all services up, extensions load), but anything that assumes uniform partition layout across nodes (future bootloader work, custom partition manipulation, disaster recovery from a stock installer) should account for this asymmetry. Read-only observation; no action needed for Longhorn.

## Final Phase 1 cluster state (2026-04-16, verified on all 3 nodes)

- Schematic: `445a99db4002e6127e7f6e2a96377ac2c06d0de52f7a186b5536c0ac2f2a2ece` on all 3 (identical extension set: i915-ucode, intel-ucode, iscsi-tools v0.2.0, tailscale, util-linux-tools 2.41.2).
- Talos: v1.12.6, kernel 6.18.18-talos, containerd 2.1.6, k8s v1.35.3, Cilium unchanged.
- UserVolumes: 5/5 ready, all ext4, all bind-mounted to kubelet:
  - k8s-1: `u-longhorn-1` (251021802186) / `u-longhorn-2` (251021802190)
  - k8s-2: `u-longhorn-1` (251021802221)  *(single data disk — second slot empty, tracked in k8s-2 hardware memory)*
  - k8s-3: `u-longhorn-1` (251021800405) / `u-longhorn-2` (251021801882)
- Etcd: 3/3 HEALTH=OK, leader `k8s-2` (migrated from k8s-3 during k8s-3 reboot), raft term 26.
- Total cluster node-touch time across the rolling upgrade: ~45 min wall-clock, 3 reboots (one per node), zero downtime for Kubernetes workloads (etcd quorum held throughout).

## Phase 2 readiness flags

1. **Asymmetric Longhorn topology**: cluster will start with 2+1+2=5 OSDs, not 6. k8s-2 is short one disk (WD_BLACK never installed; see `project_k8s_2_hardware_state.md`). Longhorn replica placement needs to tolerate per-node OSD count variance — default replicas=3 policies that assume identical capacity per node will skew. Consider `nodeSelector` / explicit topology constraints or accept the imbalance.
2. **k8s-3 OS partition asymmetry** (above): flag but don't act.
3. **Tailscale mem: state**: Talos nodes re-register to Tailscale after upgrades, often picking a `-1` suffixed hostname until the old registration expires. If Tailscale MagicDNS resolution flakes for a few minutes post-upgrade, check the admin console — kept the old address entries through all 3 upgrades this time, but the pattern has bitten before.

## Sanity warnings for future runs

- **Never wipe the CT500P3** (500GB, serial matches `installDiskSelector.serial`). That's the OS disk. Device name is unpredictable across reboots — k8s-1 just demonstrated the OS disk moving `nvme1n1` → `nvme2n1`.
- **Always verify wipe target with `get disks <device>` by serial first** — device numbering is unstable across reboots. Confirmed on both k8s-2 and k8s-1.
- **Wait ~5s after wipe** before querying volumestatus; the controller reconcile loop is fast but not instant.
- **Wipe order vs apply-config order doesn't matter for success** — both patterns (apply-config before wipe on k8s-2, wipe before apply-config on k8s-1) converged to the same healthy end state. Cleaner to wipe BEFORE apply-config so the first volume controller reconcile sees a clean disk (avoids the `failed → ready` transition).
