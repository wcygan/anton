# 2026-04-29 — Stage 2 in-OS memtester pass on k8s-2 (32 GiB locked, ~92 min, clean)

Follow-on to the 2026-04-28 Stage 1 pass logged inline at plan
[0009](../../plans/0009-k8s-2-k8s-3-silent-reboot-followup.md) Log entry for
2026-04-28. Stage 1 ran 8192 MiB mlock'd memtester for 23 min. Stage 2 was the
operator-approved escalation: 32 GiB mlock'd, single pass, full 17-pattern
sweep, 5-minute progress cadence with hard stop conditions on reboot or job
failure.

This note exists so the multi-agent synthesis at
[`evidence-2026-04-28-plan0010-four-agent-synthesis.md`](evidence-2026-04-28-plan0010-four-agent-synthesis.md)
has a sibling for the in-OS memory exhaustion path: what Stage 2 did, what it
showed, and — critically — what it does and does not falsify in the line-143
plan-0009 hypothesis ranking.

## Job shape

Ad-hoc `Job` `playground/k8s-2-memtest-stage2` (not committed to
`kubernetes/apps/playground/` — the wired-but-suspended scaffolds in that
directory are `k8s-2-bounded-stress` and `k8s-rejoin-mirrored-load`, neither of
which exercises a full DRAM sweep).

| field                             | value                                                                                |
|-----------------------------------|--------------------------------------------------------------------------------------|
| image                             | `docker.io/library/alpine:3.21`                                                      |
| command                           | `apk add memtester && memtester 32768M 1`                                            |
| capabilities                      | `IPC_LOCK` (mlock 32 GiB), `drop: ALL` otherwise                                     |
| `requests` / `limits`             | `cpu=1/2`, `memory=33Gi/36Gi`                                                        |
| `nodeName`                        | `k8s-2`                                                                              |
| tolerations                       | `anton.io/rejoin=k8s-2:NoSchedule`, `node.kubernetes.io/unschedulable:NoSchedule`    |
| `restartPolicy`                   | `Never`                                                                              |
| `backoffLimit`                    | `0`                                                                                  |
| `activeDeadlineSeconds`           | `7200` (2 h hard ceiling)                                                            |
| `ttlSecondsAfterFinished`         | `21600` (6 h GC)                                                                     |
| node posture during run           | k8s-2 stayed `Ready=True cordoned=true` throughout; no other workloads scheduled     |

Two tolerations matter: `anton.io/rejoin` is the plan-0009 rejoin-cohort taint
that gates real workload re-admission; `node.kubernetes.io/unschedulable` is
the cordon-derived taint that the test deliberately bypasses so cordon is
preserved while the test runs. This mirrors the Stage 1 pattern in plan 0009
Log line 139.

## Timeline

| epoch                      | event                                                                                  |
|----------------------------|----------------------------------------------------------------------------------------|
| `2026-04-28T23:15:12Z`     | pod started, `apk add memtester` followed by `memtester 32768M 1`                      |
| `2026-04-28T23:15:12Z`     | pre-test boot-epoch baseline `node_boot_time_seconds = 1777412482` (`21:41:22Z` boot) |
| T+12 min                   | `Compare MUL/DIV/OR/AND : ok`, `Solid Bits` in flight                                 |
| T+27 min                   | `Block Sequential : ok`                                                                |
| T+31 min                   | `Checkerboard : ok`                                                                    |
| T+41 min                   | `Bit Spread : ok`                                                                      |
| T+72 min                   | still in `Bit Flip` (longest pattern in the suite)                                     |
| T+84 min                   | `Walking Ones : ok`                                                                    |
| `2026-04-29T00:47:01Z`     | `Done.` `complete`, exit code 0, `succeeded=1`                                         |
| total elapsed              | 5509 s ≈ 91 min 49 s                                                                   |
| pod restarts               | 0                                                                                      |

Pattern progression observed end-to-end: Compare MUL/DIV/OR/AND → Solid Bits →
Block Sequential → Checkerboard → Bit Spread → Bit Flip → Walking Ones →
Walking Zeroes → ... → `Done.`. Bit Flip dominated the runtime (~31 min in that
pattern alone), consistent with a 32-bit walking flip across 32 GiB.

## Boot-epoch surveillance

A 5-min cron loop polled `node_boot_time_seconds{instance="192.168.1.99:9100"}`
via the Prometheus pod for the duration of the test. Every tick from T+12
through T+92 returned `1777412482` — identical to the pre-test baseline. k8s-2
did **not** reboot during the test window.

`changes(node_boot_time_seconds[6h]) = 0` for k8s-2 across the 92-min window;
the broader `K8s2UnexpectedReboot` PrometheusRule (widened to `[6h]` per plan
0009 Log entry 2026-04-28 "review hardening pass") did not fire.

Cluster-side state stayed quiet: kubelet on k8s-2 retained connection to the
apiserver, `Ready=True cordoned=true` held, no Vector kernel-sink anomaly, no
CNI restarts, no etcd leadership change.

## What this does falsify

- **Page-allocator pressure as a sufficient trigger.** Stage 1 (8 GiB) already
  weakened this. Stage 2 escalates to 32 GiB locked memory with full pattern
  coverage and 92 min of sustained DRAM activity — k8s-2 did not reboot. The
  framing "any sustained mlock'd memory pressure trips the silent reboot" is
  refuted at the 32 GiB / 92 min boundary.
- **Userland page-cache feedback as a sufficient trigger.** memtester is
  mlock'd, so its 32 GiB lives in anonymous pages, not page cache. Page-cache
  reclaim pressure was not exercised. But the cgroup memory accounting,
  page-allocator slow path, and zswap (if active) were all under load. None
  produced visible anomaly.
- **Single-threaded sustained DRAM activity as a sufficient trigger.** memtester
  is single-threaded and CPU-light; it does not pressurize the cache coherency
  fabric, the inter-core interconnect, or the thermal/power envelope.

## What this does NOT falsify

- **Boot-time DIMM faults.** memtester is a userland test running under a
  loaded kernel. Pre-OS POST DIMM training defects, ECC paths, and JEDEC
  channel/rank-level faults at memory-controller speed are invisible to it.
  memtest86+ at the bootloader level is the authoritative test, gated on the
  physical-access window (Phase 5).
- **Multi-core / multi-threaded memory bandwidth and cache coherency stress.**
  The line-143 hypothesis #1 ("single-unit k8s-2 hardware defect ... promoted
  to moderately supported, with the DDR5 SKU/speed mismatch + BIOS 1.22 as the
  new concrete hook") implicates faults that may be load-or-temperature gated
  rather than purely capacity-gated. memtester does not exercise that axis.
- **Thermal envelope.** memtester barely warms the CPU (single-threaded
  deterministic memory ops). If the silent-reboot mode is thermal/VRM-gated,
  Stage 2 was the wrong probe.
- **Kernel-level fault paths invisible to userland.** The four-agent
  synthesis found zero pre-reboot kernel last words across 5 of 6 inspectable
  reboots. If the failure is a hard reset below the kernel-logging horizon,
  Stage 2 could not have triggered or detected it.
- **Sustained workload over multi-day windows.** All six post-Stage-A reboots
  (2026-04-25T19:32:04Z through 2026-04-28T10:37:33Z) happened with
  `k8s-2-rejoin-smoke` running busybox heartbeats, not under stress. Stage 2's
  92-min window does not cover the inter-reboot mean of ~10.5 h observed at
  Stage A failure.

## Hypothesis-ranking impact (delta vs line 143)

The line-143 ranking is unchanged in order; Stage 2 sharpens the boundaries
slightly:

| rank | hypothesis                                              | Stage-2 impact                                                                                                                                                |
|------|---------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1    | single-unit k8s-2 hardware defect (DDR5 + BIOS hook)    | unchanged — Stage 2 cannot reach the boot-time / training / load-gated subspace where this hypothesis lives                                                  |
| 2    | kernel silent-hang exposed by environmental stimulus    | unchanged — single-threaded RAM load is not the relevant stimulus                                                                                            |
| 3    | kube-apiserver memory pressure                          | unchanged — not exercised by Stage 2                                                                                                                          |
| 4    | CNI OOM / pod-admission cascade                         | mildly weakened — k8s-2's CNI plumbing held under cordon + heavy local memory pressure; no Multus/Whereabouts/storage-vxlan restarts                          |

Stage 2 does **not** promote any hypothesis to "proven", does **not** clear
DIMMs against firmware-level POST, and does **not** claim that "k8s-2 RAM is
healthy" in any absolute sense. It claims the narrower, useful thing: 32 GiB
mlock'd userland memory load for 92 min is not the trigger we are hunting.

## Next move (recommended)

Stage 3: bounded all-core CPU + memory stress to pressurize the
load/temperature axis Stage 1 + Stage 2 left untouched. The scaffold for this
already exists at
[`kubernetes/apps/playground/k8s-2-bounded-stress/`](../../../kubernetes/apps/playground/k8s-2-bounded-stress/)
(suspended; comment block notes a reboot is an expected possible outcome).
Stage 3 follows the Stage 1/2 pattern: ad-hoc apply with the
`node.kubernetes.io/unschedulable` toleration added so the cordon is preserved,
boot-epoch baseline captured pre-launch, 3-5 min monitoring cadence, hard stop
conditions on reboot.

Stage 4 (boot-time memtest86+ / DIMM swap) remains the only thing in-cluster
testing cannot reach. Gated on the operator-access window per plan 0009 Phase 5.

## Cross-references

- plan 0009, Log entries `2026-04-28` (Stage 1) and `2026-04-29` (Stage 2)
- [`evidence-2026-04-28-plan0010-four-agent-synthesis.md`](evidence-2026-04-28-plan0010-four-agent-synthesis.md)
  — the multi-agent synthesis whose hypothesis ranking Stage 2 was designed to test
- [`evidence-2026-04-28-plan0010-stage-a-abort.md`](evidence-2026-04-28-plan0010-stage-a-abort.md)
  — the 6-reboot post-Stage-A timeline that motivated the in-OS memtester escalation
- [`evidence-2026-04-24-hardware-firmware-survey.md`](evidence-2026-04-24-hardware-firmware-survey.md)
  — DDR5 SKU/speed delta and BIOS-1.22 details for hypothesis #1
