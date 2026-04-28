# 2026-04-28 — plan 0010 Stage A abort: four-agent synthesis

After the Stage A abort was triggered earlier today (see
`evidence-2026-04-28-plan0010-stage-a-abort.md`), four read-only investigators
ran in parallel against the cluster and the Vector kernel sink to corroborate
the abort and localize the failure. This note consolidates their findings and
records the synthesis that informed the plan-0010 close-out and the new
direction for plan 0009.

## Investigation team

| Agent                        | Type             | Question                                                         |
|------------------------------|------------------|------------------------------------------------------------------|
| kernel-log-miner             | general-purpose  | What did the Talos kernel emit in the seconds before each reboot? |
| prometheus-correlator        | general-purpose  | Did any in-cluster metric anomaly precede each reboot?            |
| hardware-talos-investigator  | cluster-triage   | Is there a k8s-2-unique hardware/firmware delta?                  |
| pattern-analyst              | general-purpose  | Do the reboots line up with any cluster event or schedule?       |

All four were run with `--read-only` posture (no `apply`, no `reset`, no
`upgrade` verbs). Reproduction prompts and agent IDs are in the appendix.

## Executive summary

All four investigators converged on the same conclusion: the silent reboots
of `k8s-2` are explained by **a hardware or firmware fault below the
in-cluster observation horizon**, not by software or workload pressure.
Specifically:

- The kernel never produces last words before any reboot — no panic, oops,
  BUG, MCE, EDAC, OOM, RCU stall, NMI, watchdog, NVMe timeout, or `kernel:
  reboot:` line. Vector's `talos_service` stream cliffs ~35–40 s before each
  boot, then a fresh `Linux version` reappears ~36–40 s later. The cliff is
  TCP-keepalive lag on Vector's socket, **not** a graceful shutdown.
- All coded abort criteria (apiserver WSS Δ20m, APF queue, longrunning jump,
  watch burst) were **absent at T-1m on every reboot**. The cilium-agent
  plateau on k8s-2 (~760 MiB) is well below its 3584 MiB ADR-0022 limit and
  is **flat**, not growing.
- k8s-2 has the only k8s-2-unique hardware delta found across the
  investigation: **Mushkin DDR5 @ 5200 MT/s** (k8s-1 and k8s-3 both run
  Crucial DDR5 @ 5600 MT/s), older BIOS (`AHWSA.1.22`), and a unique
  `ENERGY_PERF_BIAS` boot-time correction.
- Reboot timing is dispersed (Rayleigh R = 0.27 in both UTC and PDT), with
  no alignment to git landings, Flux reconciles, kube-apiserver leadership
  changes, CronJobs, or PrometheusRule cadences.

The four-way fingerprint is **internally consistent** and **mutually
corroborating**: kernel-silent → metric-quiet → hardware-distinct →
schedule-unaligned. The weakest individual finding (the DIMM-SKU mismatch)
gains weight because it is the only k8s-2-specific signal across all four
lenses, and it pairs with a kernel-cliff signature shaped like a hardware
hard-stop.

## Agent findings

### Agent 1 — kernel-log-miner

**Sink location.** The Vector instance is `talos-log-sink-vector-0` in
namespace `observability`, scheduled to k8s-1 (anti-affinity excludes k8s-2).
Backed by a 5 Gi Longhorn PVC mounted at `/vector-data-dir`. The sink writes
daily files at `/vector-data-dir/talos-sink-%Y-%m-%d.log` (JSON codec). The
sidecar named `rotator` is a no-op (`trap 'exit 0' TERM; sleep infinity &
wait`) — Vector itself rotates the file. Fed by two TCP socket sources:
`talos_kernel` on :6001 and `talos_service` on :6000.

**Coverage.** `talos-sink-2026-04-21.log` … `talos-sink-2026-04-28.log`
(~470 MB/day; 04-28 is current). k8s-2 kernel records exist only from
`2026-04-25T19:32:03.926567Z` onward — the boot-#0 (pre-Stage-A) epoch is
**not** in the sink, so reboot #1 has no pre-window observable.

**Per-reboot table.**

| # | boot (UTC)          | last svc-stream record | gap pre-boot | dominant kernel marker(s) | stream silent in last 5 s? |
|---|---------------------|-----------------------:|-------------:|---------------------------|----------------------------|
| 1 | 2026-04-25T19:32:04 | n/a (sink starts here) | —            | NO PRE-WINDOW DATA        | n/a                        |
| 2 | 2026-04-25T21:04:19 | 21:03:38.889 (machined Memory RPC OK) | 39.7 s | none in pre-window | yes |
| 3 | 2026-04-27T04:56:08 | 04:55:28.200 (machined NetworkDeviceStats OK) | 38.6 s | none | yes |
| 4 | 2026-04-27T21:42:29 | 21:41:52.465 (machined Processes OK) | 35.4 s | none | yes |
| 5 | 2026-04-28T04:39:48 | 04:39:08.602 (machined CPUFreqStats OK) | 38.3 s | none | yes |
| 6 | 2026-04-28T10:37:33 | 10:37:11 region | ~22 s | none | yes |

**Negative findings (whole 04-25 → 04-28 k8s-2 kernel stream, 8129 records).**
Zero matches, in any pre-window, for: `panic`, `Oops`, `BUG:`, `general
protection`, soft/hard lockup, `watchdog`, `Call Trace:`, `RIP:`, `taint`,
`Machine Check`/`MCE`/`Hardware Error`, real `ECC`/word-boundary EDAC fault,
`OOM`/oom-kill, RCU stall, `unknown NMI`/`APIC error`, thermal throttle event,
NETDEV WATCHDOG, NVMe error or timeout, `I/O error`, `EXT4-fs error`. The only
matches for any of those keywords are boot-init lines (e.g. `EDAC MC: Ver:
3.0.0`, `LSM: ...,bpf,...`, ACPI `LAPIC_NMI`) and the once-per-boot
`nvme nvme0/1: using unchecked data buffer` warning, which is normal MS-01
NVMe behaviour.

**Cross-reboot signature.** The single signature that fires in 5 of 5
inspectable reboots is: **service stream cliff at boot − 35–40 s, with no
kernel-stream output at all in the last 5 minutes before boot.** The ~36–40 s
"silent then `Linux version`" gap is consistent with TCP-keepalive on
Vector's `talos_service` socket source taking that long to surface a
connection drop after the node stops processing.

**Conclusion.** The kernel never gets to write a final message — k8s-2 dies
from a hard-stop event (CPU/microcode wedge, firmware NMI/MCE that never
reaches kmsg, BMC-less platform reset, kernel hang inside an unforwarded
code path) and reboots. The absence of any unmount, `kernel: reboot:`,
panic banner, RCU stall, soft-lockup, MCE, or even a single warning in the
5-min pre-window across **all five observable reboots** strongly excludes:

- (a) software-initiated graceful reboot,
- (b) OOM (kernel-side OOM killer or container OOMKill),
- (c) RCU stall,
- (d) any kernel oops or trace-producing fault,
- (e) any thermal-throttle event Linux notices in time.

The MS-01 platform has **no BMC/IPMI** (per repo memory), so no out-of-band
logs exist either.

**Falsification path.** A single instance of any negative marker showing up
in a future reboot's pre-window would falsify the "kernel never reaches
kmsg" theory and re-open the software path. Conversely, capturing a
netconsole / kmsg-forwarder over UDP for the next reboot and finding *that*
also empty would strongly confirm a hardware/firmware hard-stop, since UDP
won't be silenced by TCP buffering.

**Reach-back data extracted.** `/tmp/k8s2-forensic/k8s2-kernel.tsv` (8129
lines, k8s-2 kernel-source records) and `svc-times-clean.txt` (1.2 M k8s-2
service-source events). These are operator-local; not committed.

### Agent 2 — prometheus-correlator

**Per-reboot fingerprint table** (T-1m = last scrape ≤ boot−60s; cilium-agent
limit per ADR 0022 = 3584 MiB; multus limit = 512 MiB; whereabouts =
512 MiB; storage-vxlan = 128 MiB):

| R  | Boot UTC   | CilA peak MiB (% lim) @t       | CilA T-1m | API WSS T-1m / Δ20m  | Watch /s T-1m (peak) | APF inq | LR T-1m | Multus peak (% 512) | WA peak (% 512) | VxLAN peak (% 128) | Node MemAvail T-1m GiB | load1 T-1m (peak) |
|----|------------|--------------------------------|-----------|----------------------|----------------------|---------|---------|---------------------|-----------------|--------------------|------------------------|-------------------|
| B1 | 19:32:04Z  | 184.5 (5.1%) @19:11:34         | 178.7     | 1029.3 / −81.4       | 4.33 (5.13)          | 0       | 73      | 63.2 (12.3%)        | 10.6 (2.1%)     | 0.3 (0.2%)         | 88.91                  | 1.79 (4.99)       |
| B2 | 21:04:19Z  | 759.5 (21.2%) @21:00:49        | 757.7     | 953.8 / −33.7        | 23.53 (23.67)        | 0       | 140     | 106.4 (20.8%)       | 12.8 (2.5%)     | 4.2 (3.3%)         | 89.28                  | 1.91 (5.01)       |
| B3 | 04:56:08Z  | 763.7 (21.3%) @04:39:38        | 760.1     | 981.2 / +13.8        | 22.00 (23.10)        | 0       | 124     | 106.4 (20.8%)       | 18.9 (3.7%)     | 4.1 (3.2%)         | 89.23                  | 1.66 (4.51)       |
| B4 | 21:42:29Z  | 761.5 (21.2%) @21:19:59        | 758.7     | 828.8 / +18.3        | 3.23 (4.83)          | 0       | 62      | 107.3 (21.0%)       | 13.4 (2.6%)     | 4.1 (3.2%)         | 89.40                  | 2.55 (4.55)       |
| B5 | 04:39:48Z  | 762.9 (21.3%) @04:13:18        | 757.1     | 725.8 / −169.3       | 3.17 (4.90)          | 0       | 38      | 106.9 (20.9%)       | 19.4 (3.8%)     | 4.1 (3.2%)         | 89.44                  | 2.49 (3.93)       |
| B6 | 10:37:33Z  | 760.9 (21.2%) @10:27:33        | 757.9     | 940.4 / +27.2        | 3.40 (4.40)          | 0       | 39      | 106.1 (20.7%)       | 12.7 (2.5%)     | 4.1 (3.2%)         | 89.24                  | 1.66 (3.30)       |

PSI memory rate = 0.0000/s at T-1m on all 6 reboots; `kubelet_running_pods`
on k8s-2 was steady (no scheduling burst); apiserver request rate
0.6–4.0/s (low). **Every "abort criterion" the rule set checks (Δ20m ≥
+384 MiB, APF queue, longrunning jump) was absent at T-1m on every reboot.**

**k8s-2 vs control nodes (cilium-agent WSS, pre-boot peak):**

| R  | k8s-1 MiB | k8s-2 MiB | k8s-3 MiB |
|----|-----------|-----------|-----------|
| B1 | 225.6     | 184.5     | 175.5     |
| B3 | 226.8     | 763.7     | 182.4     |
| B6 | 235.5     | 760.9     | 179.1     |

cilium-envoy is identical (~58 MiB) on all three nodes. **k8s-2's
cilium-agent is 3.3–4.3× the size of either control node** from B2 onward.
The B1→B2 jump (~92 minutes) is a *state transition*, not a leak — multus
goes 63→106 MiB, storage-vxlan goes 0→4 MiB, cilium-agent goes 184→760 MiB
together. Plateaus and never grows further. Consistent with k8s-2 newly
joining the Longhorn `vxlan-storage` overlay and getting Cilium endpoint
state for the first time post-Stage-A.

**Conclusion.** The reboots are not driven by any of these metrics. Every
"expected" failure mode — cilium-agent OOM, apiserver leak, APF saturation,
node memory exhaustion, PSI stall — was absent at T-1m on every reboot.
The plateau values are normal-looking with abundant headroom (cilium-agent
at 21% of limit, MemAvailable 89 GiB, load1 ~2). The reboot pattern itself
points to a hardware/firmware/kernel-level fault below Prometheus's
observation horizon.

**Killer-of-this-hypothesis evidence:** another reboot with PSI > 0 in the
last 60 s, MemAvailable collapsing under 1 GiB, or cilium-agent crossing
~3000 MiB. None of those are happening.

**Coverage gaps.** Post-boot scrape gap (~30–90 s) on every node-bound
target — node-exporter, cAdvisor, and apiserver-on-k8s-2 all stop
reporting during the kernel-down window. Sub-30s spikes between scrapes
remain invisible.

### Agent 3 — hardware/Talos angle (cluster-triage)

**Three-node hardware diff (key fields).** Same chassis (MS-01), same
CPU SKU and microcode at runtime, same Talos and kernel build. Two
deltas appeared on k8s-2:

- **DDR5 DIMM SKU and speed.** k8s-2 ships with **Mushkin DDR5 @ 5200
  MT/s**; k8s-1 and k8s-3 both run **Crucial DDR5 @ 5600 MT/s**. This is
  the first confirmed k8s-2-only hardware delta tied to the silent-reboot
  saga.
- **BIOS revision.** k8s-2 is on **AHWSA.1.22**; k8s-1 (and k8s-3 per
  the prior 04-24 hardware-firmware survey) are on a newer BIOS.
- A unique `ENERGY_PERF_BIAS` boot-time correction message appears on
  k8s-2 only.

**EDAC / MCE / dmesg state, current boot, all three nodes:** clean. No
machine-check counters, no edac error increments, no `mce|hardware
error|nmi|thermal` matches in the retained dmesg. EDAC requires the OS to
survive long enough to log the error — given the kernel-silent signature,
absence of EDAC events is **not** evidence of clean memory.

**Talos-side findings unique to k8s-2:** none beyond the hardware deltas
above. All services running, no apid/containerd/kubelet/machined errors
in the current boot, time-skew within tolerance (well under 100 ms across
all three).

**Hypothesis fitness.** A DDR5 instability on k8s-2 (whether driven by
the lower-clocked DIMM SKU, the older BIOS's memory training, or a
specific DIMM defect) explains:

- the k8s-2-specificity (k8s-1 / k8s-3 do not share the SKU + BIOS combo);
- the kernel-silent signature (memory faults can hard-stop the CPU before
  the kernel can write to kmsg, especially on a board with no BMC to
  capture an SMI/SCI trace);
- the dispersed time-of-day (memory faults are load-or-temperature-gated,
  not clock-driven);
- the bimodal interval pattern (short-burst recovery vs longer-quiet,
  consistent with thermal margin loss after a stress event).

The hypothesis is **moderately supported, not proven** — the same pattern
could be produced by an older BIOS's memory-training or power-management
bug independent of the DIMM SKU.

**Recommended in-band probes (no physical access required):**

1. **Pin the smoke workload to k8s-1** as a negative control. If k8s-1
   stays up while running an identical pod set, the workload itself is
   excluded as a trigger and the k8s-2-uniqueness is reinforced.
2. Add a **netconsole / UDP kmsg forwarder** so the next reboot has a
   chance to surface kernel last words even if TCP buffering eats them.
3. Optionally: run a memtest-equivalent stress on k8s-2 during a
   maintenance window before any physical-access work.

The cheapest path that meaningfully narrows the hypothesis without a
physical visit is (1) + (2) in parallel.

### Agent 4 — pattern analyst

**Interval table** (R0 is the pre-Stage-A control; deltas computed for
the post-Stage-A cluster only):

| R# | UTC                  | Δ_to_prev_h          | Local (PDT) | DOW |
|----|----------------------|---------------------:|-------------|-----|
| R0 | 2026-04-23T20:47:11Z | — (control)          | 2026-04-23 13:47 | Thu |
| R1 | 2026-04-25T19:32:04Z | 46.75 (vs R0)        | 2026-04-25 12:32 | Sat |
| R2 | 2026-04-25T21:04:19Z | **1.54**             | 2026-04-25 14:04 | Sat |
| R3 | 2026-04-27T04:56:08Z | **31.86**            | 2026-04-26 21:56 | Sun |
| R4 | 2026-04-27T21:42:29Z | **16.77**            | 2026-04-27 14:42 | Mon |
| R5 | 2026-04-28T04:39:48Z | **6.96**             | 2026-04-27 21:39 | Mon |
| R6 | 2026-04-28T10:37:33Z | **5.96**             | 2026-04-28 03:37 | Tue |

**Statistics (n = 5 deltas, R2−R1 … R6−R5).** mean **12.62 h**, median
**6.96 h**, stdev **12.11 h**, min **1.54 h**, max **31.86 h**. Linear
regression of Δ vs index: slope = **−1.61 h/step** ⇒ trend is mildly
accelerating, but stdev > mean so the trend is not statistically
meaningful at this n. Bimodal hint: short cluster {1.54, 5.96, 6.96} h
vs long cluster {16.77, 31.86} h — too small to call structurally.

**Time-of-day verdict.** Circular-mean Rayleigh R = **0.270** in both
UTC and PDT — **dispersed, statistically indistinguishable from
uniform**. No hour-of-day or day-phase clustering. Period-scan over
4–30 h shows weak peaks at ≈6.2 h (R = 0.74) and 8.0 h (R = 0.71); with
n = 6 the random-baseline R is ~0.5, so these are not convincing.

**Cluster-event alignment.** Hard data is thin because Kubernetes events
are TTL-pruned (earliest surviving event in cluster: 2026-04-28T15:04Z).

- **Git activity 2026-04-25 → 2026-04-28: zero commits in window.** Last
  commit before R1 is `51bb2d9d docs(plan-0010): record Stage A launch`
  at 2026-04-24T18:33Z, ≈25 h before R1. **No commit lands within ±2 min
  of any reboot.**
- **Flux reconciliations.** The only smoke-related Kustomization event
  surviving is `next run in 1h0m0s` (steady 1 h cadence). Cadence
  matches no inter-reboot interval.
- **Smoke deployment churn.** All 8 pods at exactly 6 restarts;
  `lastTermination.finishedAt = 2026-04-28T10:37:40Z` (R6 + 7 s);
  reason `Unknown`. Pods are the **victim**, not a trigger.
- **Apiserver leases.** Lease `apiserver-…` age 6 h 17 m at observation
  ⇒ acquired ≈2026-04-28T04:40Z, which **matches R5 (04:39:48Z) within
  ~1 min**. This is the apiserver pod on k8s-2 reappearing after the
  boot — expected post-reboot, not causal. Other two apiserver leases
  (k8s-1, k8s-3) are 11 d / 4 d 20 h old: **no control-plane leadership
  churn** correlated with reboots.

**Recurring-schedule scan.** CronJobs cluster-wide: only two —
`kube-system/pod-gc` (every 30 min) and `observability/talos-log-sink-
rotate` (daily at 03:17 UTC). PrometheusRule groups: shortest interval
30 s, none on a multi-hour cadence. R6 fired at 10:37 UTC (≠ 03:17),
R3/R5 at ≈04:5x UTC (≠ 03:17). **No scheduled job aligns with the
reboot phase.**

**Best temporal hypothesis (ranked):**

1. **Hardware-thermal / firmware-clock — top pick.** No git landings, no
   leadership churn, no scheduled job, no periodic Flux event aligns;
   time-of-day is dispersed; cadence is bimodal with stdev > mean —
   signature of a non-deterministic, load-or-temperature-gated trigger
   rather than a clock-driven one. k8s-1 and k8s-3 are stable while
   k8s-2 alone reboots, ruling out cluster-wide workload causes.
2. **Random / unstructured failure** — cannot be excluded at n = 6;
   circular-mean R values are statistically consistent with uniform.
   Argued against by the bimodal hint and by the workload-side restart
   count exactly matching boot count.
3. **Workload-driven** — least supported. The smoke deployment, Flux
   cadence, CronJobs, and PrometheusRule intervals do not align with
   any reboot timestamp; the workload is the visible victim
   (`reason=Unknown` synchronous with each boot), and the abort-
   criteria knobs (apiserver WSS Δ, watch burst, APF queue, longrunning)
   were quiet at observation.

## Convergence and contention

The four investigators converge cleanly:

- **No software trigger** (agents 1, 2, 4 — kernel silence + metric
  quiet + schedule miss).
- **k8s-2-specific hardware delta exists** (agent 3 — DDR5 SKU + BIOS).
- **Failure signature is hardware-fault-shaped** (agent 1 — kernel
  produces no last words; agent 4 — load-or-temperature-gated, not
  clock-driven).

The only soft-disagreement is statistical: agent 4 notes that pure
randomness cannot be excluded at n = 6. This does **not** contradict the
hardware hypothesis — random-looking inter-reboot intervals are exactly
what a load-or-temperature-gated DIMM/CPU fault produces. The two
positions can both be true.

## Open questions the team could not close

1. **What was happening in the last ~30 s before each kernel cliff.**
   Vector's TCP-keepalive on `talos_service` smears the death moment.
   Nothing in-cluster sees sub-30 s pre-death state.
2. **Whether the DIMM-SKU mismatch is causal**, or just correlated. The
   same MS-01 board with the same CPU is shared with k8s-1/k8s-3; the
   differences are RAM SKU + BIOS + `ENERGY_PERF_BIAS`. Could be any of
   those, or all three.
3. **Whether k8s-2 was ever stable.** The cluster was rebuilt in April
   2026 (ADR 0001). Pre-rebuild stability of this exact node would help
   distinguish "latent hardware fault present at acquisition" from
   "fault induced by some software change since rebuild."

## Recommendations, ordered by cost

1. **Negative control on k8s-1 (cheapest falsifier).** Scaffold a
   `k8s-1-rejoin-control` Deployment of identical shape to the k8s-2
   smoke, pinned to k8s-1, and watch it for 48 h. If k8s-1 stays up
   while running the same workload, the workload itself is excluded as
   a trigger, and the k8s-2-specificity is reinforced. **Cost:** one
   draft manifest committed unwired; one Flux reconcile when wired.
   **Mutation surface:** repo only at draft; `playground/kustomization
   .yaml` append at wire time (no node mutation).
2. **Capture last words on the next reboot.** TCP-buffered Vector loses
   the final ~30 s. Add Talos `printk.devkmsg=on` plus a UDP
   netconsole target pointed at the same Vector pod, *or* wire a
   USB-serial cable to k8s-2's COM header (MS-01 has no BMC). Either
   gives kmsg-over-UDP independent of TCP keepalive. **Cost:** Talos
   config patch + apply on k8s-2 only; no etcd-quorum risk if applied
   `--mode=auto`.
3. **BIOS reflash to current MS-01 firmware on k8s-2.** Closes the
   AHWSA.1.22 gap. Requires physical access. Defer until 1+2 narrow
   hardware/firmware vs. kernel.
4. **DIMM swap on k8s-2.** Move a Crucial DIMM from k8s-1 or k8s-3 into
   k8s-2 and re-test. Confirms or kills the DIMM-SKU hypothesis
   directly. Last resort, requires physical access.

## Implications for the planning system

- **Plan 0010** ("stage k8s-2 software rejoin") is closed by failure,
  not by completion. Software-side hardening was sufficient to space
  out reboots (mean ≈10.5 h post-Stage-A) but not to suppress them.
  The plan's own exit criterion ("if recurrence happens, hand off to
  plan 0009 or hardware-access successor") fires on this evidence.
- **Plan 0009** ("localize the k8s-2 silent-reboot root cause") absorbs
  the four-agent synthesis above. Hypothesis ranking moves: a single-
  unit hardware defect on k8s-2 stays at #1 with the DDR5-SKU delta as
  the new concrete hook; "kernel silent-hang exposed by pod-churn-
  adjacent stimulus" stays at #2; the kube-apiserver-pressure
  hypothesis is **demoted** (apiserver was quiet at every T-1m); the
  CNI-OOM cascade is also demoted (CNI plumbing was below limit on
  every reboot).

## Appendix — agent reproduction

To re-run any of the four investigators verbatim, use `Agent` with the
prompts captured below. Each is read-only and idempotent.

| Agent | subagent_type | Agent ID (one-shot resume) |
|-------|---------------|----------------------------|
| kernel-log-miner | general-purpose | `af1166ecf8ec29a5e` |
| prometheus-correlator | general-purpose | `aeff704e6a163efa3` |
| hardware/Talos angle | cluster-triage | `aa189a1df9e73441d` |
| pattern analyst | general-purpose | `a98f6f577cdb397ec` |

Continuing an existing agent (instead of spawning a fresh one) preserves
its prior context and any cached artifacts. To resume, use
`SendMessage({to: "<agent-id>", ...})`.

Local extracts produced by agent 1 (operator-side, not committed):

- `/tmp/k8s2-forensic/k8s2-kernel.tsv` — 8129 lines, k8s-2 kernel-source
  records 04-25 → 04-28.
- `/tmp/k8s2-forensic/svc-times-clean.txt` — 1.2 M k8s-2 service-source
  events.

Agent 3 wrote a memory entry to its own subagent memory at:
`.claude/agent-memory/cluster-triage/project_k8s2_dimm_split.md` (DDR5
SKU/speed delta, retained for future cluster-triage runs).
