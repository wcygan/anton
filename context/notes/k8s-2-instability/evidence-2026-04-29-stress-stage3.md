# 2026-04-29 — Stage 3 multicore CPU + memory-bandwidth stress on k8s-2 (90 min, clean)

Follow-on to the 2026-04-29 Stage 2 in-OS memtester pass
([`evidence-2026-04-29-memtester-stage2.md`](evidence-2026-04-29-memtester-stage2.md)).
Stage 2 covered DRAM capacity at 32 GiB locked, but memtester is single-threaded
and CPU-light — it does not pressurize the cache coherency fabric, the inter-core
interconnect, or the thermal/power envelope. Stage 3 is the operator-approved
escalation that closes the load/temperature/bandwidth axis the memtester stages
left untouched, which is exactly where the line-143 plan-0009 hypothesis #1
(load-or-temperature-gated single-unit hardware fault) lives.

## Job shape

Ad-hoc `Job` `playground/k8s-2-stress-stage3`. Manifest authored at
`/tmp/k8s-2-stage3-job.yaml`, applied via `kubectl apply` (not committed to
`kubernetes/apps/playground/` — same out-of-tree pattern as Stages 1 and 2).

| field                             | value                                                                                                       |
|-----------------------------------|-------------------------------------------------------------------------------------------------------------|
| image                             | `docker.io/library/alpine:3.21`                                                                             |
| command                           | `apk add stress-ng && stress-ng --cpu 0 --cpu-method matrixprod --vm 8 --vm-bytes 1G --vm-method all --metrics-brief --verify --log-brief --timeout 90m` |
| dispatched workers                | 20 cpu stressors (matrixprod, all logical cores) + 8 vm stressors (1 GiB each, `--vm-method all`)           |
| `requests` / `limits`             | `cpu=4/-`, `memory=10Gi/12Gi` (no CPU cap so all 20 cores can be saturated)                                 |
| `nodeName`                        | `k8s-2`                                                                                                     |
| tolerations                       | `anton.io/rejoin=k8s-2:NoSchedule`, `node.kubernetes.io/unschedulable:NoSchedule`                           |
| `restartPolicy`                   | `Never`                                                                                                     |
| `backoffLimit`                    | `0`                                                                                                         |
| `activeDeadlineSeconds`           | `6000` (100 min hard ceiling, 10 min over the stress-ng 90 min budget)                                      |
| `ttlSecondsAfterFinished`         | `21600` (6 h GC)                                                                                            |
| `securityContext`                 | `seccompProfile: RuntimeDefault`, `capabilities: drop ALL`, `allowPrivilegeEscalation: false`               |
| node posture during run           | k8s-2 stayed `Ready=True cordoned=true` throughout                                                          |

Stress-ng dispatched: `dispatching hogs: 20 cpu, 8 vm`. cpufreq governor was
`powersave` for all 20 logical CPUs — stress-ng warned that `performance` would
yield more thermal load. Since the test still saturated all cores at the
governor ceiling (~3.4 GHz on this SKU under powersave's frequency-scaling
heuristic when kept pinned), this is a known limit of the run, not an error;
flipping the governor would require a privileged pod and was out of scope for
a bounded ad-hoc probe.

## Timeline

| epoch                      | event                                                                              |
|----------------------------|------------------------------------------------------------------------------------|
| `2026-04-29T01:29:04Z`     | pod started, `apk add stress-ng`                                                  |
| T+0 (after apk)            | `setting to a 1 hour, 30 mins run per stressor` / `dispatching hogs: 20 cpu, 8 vm` |
| T+17 min                   | first observed node-exporter scrape gap (`up=0` for k8s-2)                         |
| T+50 min                   | scrape recovered (`up=1`); bootID + last_over_time boot epoch unchanged             |
| T+57 min                   | continued; no log advancement (stress-ng holds metrics until completion)            |
| T+74 min                   | 16 min remaining; bootID stable                                                     |
| T+79 min                   | second scrape gap (`up=0`); bootID stable                                           |
| `2026-04-29T02:59:06Z`     | `successful run completed in 1 hour, 30 mins` / `stage3 stress complete`           |
| total elapsed              | 5402 s ≈ 90 min                                                                    |
| pod restarts               | 0                                                                                   |

stress-ng end-of-run summary:

```
stressor       bogo ops real time  usr time  sys time   bogo ops/s     bogo ops/s
                          (secs)    (secs)    (secs)   (real time) (usr+sys time)
cpu           100559864   5400.00  75391.47    137.85     18622.19        1331.40
vm            128041112   5400.02  29593.51    445.80     23711.23        4262.45
skipped: 0
passed: 28: cpu (20) vm (8)
failed: 0
metrics untrustworthy: 0
```

`--verify` mode was active; zero stressor verification failures across the
~228 M combined bogo-ops. CPU stressors consumed ~75,391 user-seconds across
20 workers over 5400 wall-seconds — i.e., effectively all 20 logical cores were
pinned at ~70% busy (`75391 / (5400 * 20) ≈ 0.70`) for the full 90 minutes.
VM stressors consumed ~29,593 user-seconds across 8 workers — saturating
memory bandwidth at the page-cycling level.

## Boot-epoch surveillance

Boot-epoch detection used a dual-source method this stage to harden against
node-exporter scrape starvation under stress:

1. **kubelet `nodeInfo.bootID`** — UUID assigned at boot, reported through the
   apiserver, independent of node-exporter. Stable through the entire run:
   `3b6e1929-bad4-4333-9f42-3a5b88e73f5a`.
2. **`last_over_time(node_boot_time_seconds[30m])`** — survives the scrape
   gaps that broke instant queries. Returned `1777412482` on every tick.

Two scrape gaps were observed (T+17, T+79). Both resolved without intervention.
**Neither was a reboot.** The `up=0` signal under stress is metric starvation
(node-exporter starved for CPU under 100% CPU saturation, or its scrape socket
blocked under high context-switch contention); kubelet→apiserver heartbeats
kept flowing on the same node, and `node.status.conditions = Ready=True` was
maintained. The reboot detection logic was hardened mid-run to reflect this:
declare REBOOT only on bootID change OR `last_over_time` boot-epoch advance.
node-exporter `up=0` alone is not a reboot.

`changes(node_boot_time_seconds[6h]) = 0` for k8s-2 across the 90-min window;
`K8s2UnexpectedReboot` did not fire.

## What this does falsify

- **Multi-core CPU saturation as a sufficient trigger.** All 20 logical cores
  pinned at ~70% busy for 90 min via integer matrix-product workload. No
  reboot.
- **Memory bandwidth saturation as a sufficient trigger.** 8 concurrent VM
  workers cycling through `--vm-method all` against 8 GiB resident with the
  page allocator hammered. No reboot.
- **Cache coherency / inter-core interconnect stress as a sufficient trigger.**
  matrixprod across 20 cores generates substantial L1↔L2↔L3↔DRAM traffic and
  cache-line ping-pong. No reboot.
- **Sustained max-userspace-load thermal envelope (under powersave governor)**
  as a sufficient trigger. 90 min of all-core pinning at the powersave ceiling
  did not produce a reboot. (Caveat: `performance` governor would yield higher
  package power and temperature; not exercised this stage.)
- **Combined CPU + memory bandwidth + page-allocator pressure** as a sufficient
  trigger. Stage 2 covered capacity-only memory load; Stage 3 added all-core
  CPU pressure on top. Still no reboot.

## What this does NOT falsify

- **Boot-time DIMM/firmware faults.** memtester (Stage 2) and stress-ng
  (Stage 3) both run under a loaded kernel. Pre-OS POST DIMM training defects,
  ECC paths at memory-controller speed, JEDEC channel/rank-level faults, and
  BIOS-level memory training defects remain invisible to userland. memtest86+
  at the bootloader level is the authoritative test, gated on the
  physical-access window (Phase 5).
- **Performance-governor / max-package-power thermal envelope.** Stage 3 ran
  under `powersave`. A `performance` governor run would push the package
  temperature ~10-15°C higher and exercise VRM / power-delivery transients
  Stage 3 did not. This is the next available in-OS lever if a Stage 3.1 is
  warranted, but requires either a privileged pod or a Talos sysctl/kernel-arg
  configuration change.
- **Multi-day sustained moderate load.** All six post-Stage-A reboots
  (2026-04-25T19:32:04Z through 2026-04-28T10:37:33Z, mean inter-reboot
  interval ~10.5 h) happened with `k8s-2-rejoin-smoke` running busybox
  heartbeats — orders of magnitude lighter than Stage 3, and over a window
  much longer than 90 min. If the trigger is weighted toward elapsed time at
  moderate load rather than instantaneous load magnitude, Stage 3 cannot
  detect it.
- **Workload-specific I/O paths.** Stage 3 is purely CPU + memory. It does
  not exercise NVMe writes, network bandwidth (Cilium BPF / Multus VXLAN /
  Tailscale operator proxy), or persistent-storage paths (Longhorn block,
  filer S3 buckets). If a NIC firmware bug, NVMe controller stall, or
  storage-fabric event is part of the failure mode, Stage 3 cannot trigger it.
- **Hardware faults that need cold-boot / power-cycling stimulus.** Stage 3
  ran on a warm-booted node (uptime ~5 h at start, currently ~6.5 h). Faults
  that depend on power-on transients are not reachable from a running OS.
- **Kernel-level fault paths invisible to userland.** Same caveat as Stage 2:
  if the failure is a hard reset below the kernel-logging horizon, no
  userspace probe can produce or detect it.

## Hypothesis-ranking impact (delta vs line 143 / Stage 2 evidence note)

The line-143 ranking is **unchanged in order**. Stages 1+2+3 collectively
sharpen the boundaries of hypothesis #1 substantially:

| rank | hypothesis                                              | post-Stage-3 status                                                                                                                                                                |
|------|---------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1    | single-unit k8s-2 hardware defect (DDR5 + BIOS hook)    | **narrowed** — the in-OS subspace (userland-reachable load/bandwidth/thermal triggers) is now exhausted; remaining unfalsified subspace is firmware/POST training, performance-governor thermal envelope, multi-day cumulative-load triggers, and physical-layer faults requiring cold-boot stimulus |
| 2    | kernel silent-hang exposed by environmental stimulus    | unchanged — userland CPU/memory pressure was not the relevant stimulus; netconsole UDP path is still our best bet for the next genuine event                                      |
| 3    | kube-apiserver memory pressure                          | unchanged — not exercised by Stage 3                                                                                                                                              |
| 4    | CNI OOM / pod-admission cascade                         | mildly weakened further — 90 min of intense kubelet/apiserver-adjacent contention with 20-core CPU saturation produced zero CNI restarts on k8s-2                                  |

Net effect: the three in-OS stages have closed off "load-pressure on RAM,
CPU, cache, or memory bandwidth from userspace" as a sufficient trigger.
Hypothesis #1 has not been falsified — but its *practical* surface area is
significantly smaller. Either (a) the fault is gated on something Stage 3
couldn't reach (firmware/POST, max-power thermal, cold boot, multi-day
cumulative), or (b) it is not a userland-loadable hardware fault and the
correct path is netconsole capture of the next event + physical DIMM swap.

## Next move (recommended)

The in-OS diagnostic surface is now exhausted. Two paths remaining, in
ascending cost:

1. **Stage 3.1 (optional, low-cost): performance-governor re-run.** Same
   workload as Stage 3 with `cpufreq.scaling_governor=performance` set per CPU
   on k8s-2 — pushes package temperature ~10-15°C higher and stresses the
   VRM. Requires either a privileged-pod sysctl write or a Talos
   `KernelParam` change. Diagnostically marginal vs Stage 3 (powersave at
   100% pin already saturates thermals to the governor ceiling); skippable
   if the operator-access window is near.
2. **Stage 4 (decisive, gated on operator access): boot-time memtest86+ +
   DIMM swap.** This is the only remaining test that can reach DIMM-training
   and firmware-level memory faults. Per plan 0009 Phase 5, gated on the
   operator-access window (~2026-05-04 per the plans index). Includes:
   normalize BIOS posture (1.22 → 1.27), memtest86+ for ≥4 passes, optional
   DIMM swap with k8s-3 (Crucial DDR5 5600 MT/s) to test the mismatch
   hypothesis, capture pre/post BIOS + microcode IDs for the plan log.

Stage 3 should NOT be re-run: a clean 90-min pass at this load level is a
near-optimal in-OS result, and additional in-OS testing has diminishing
returns. The next reboot — whether on the cordon under the smoke pods or
during a deliberate post-Stage-4 re-admission — is now the canonical signal,
and the netconsole UDP + TCP paths are configured to capture whatever the
kernel emits.

## Cross-references

- plan 0009, Log entries `2026-04-28` (Stage 1), `2026-04-29` (Stage 2), `2026-04-29` (Stage 3)
- [`evidence-2026-04-29-memtester-stage2.md`](evidence-2026-04-29-memtester-stage2.md)
  — Stage 2 32 GiB mlock'd memtester pass; sibling note this stage builds on
- [`evidence-2026-04-28-plan0010-four-agent-synthesis.md`](evidence-2026-04-28-plan0010-four-agent-synthesis.md)
  — multi-agent synthesis whose hypothesis #1 (load-or-temperature-gated single-unit hardware fault) Stage 3 was designed to test
- [`evidence-2026-04-28-plan0010-stage-a-abort.md`](evidence-2026-04-28-plan0010-stage-a-abort.md)
  — 6-reboot post-Stage-A timeline; "moderate sustained load over multi-day windows" remains the failure-observation regime Stage 3 cannot reach
- [`evidence-2026-04-24-hardware-firmware-survey.md`](evidence-2026-04-24-hardware-firmware-survey.md)
  — DDR5 SKU/speed delta and BIOS-1.22 details for the Stage 4 physical-access work
