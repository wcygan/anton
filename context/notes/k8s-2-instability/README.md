# k8s-2 instability — investigation workspace

**Problem in one line:** k8s-2 has rebooted repeatedly over the past week (counting method contested — see open question below), k8s-1 and k8s-3 have been stable over the same window.

This folder is the working record for diagnosing, instrumenting, and fixing the instability. It is **not** an ADR (those are in `context/adrs/`, immutable) and **not** a plan (those are in `context/plans/`, execution state). It is a scratchpad that may graduate into an ADR (for the structural fix, e.g. "we committed to Talos logging destinations") and/or a plan (for the rollout).

## Current status

**Phase:** Post-intervention observation — [plan 0007](../../plans/0007-k8s-2-remote-diagnostic-rollout.md) owns the rollout. Phase 2 kernel panic sysctls (`kernel.panic=10`, `kernel.panic_on_oops=1`) are live on all 3 nodes. Phase 3 Vector log sink is LIVE on all three nodes (activated 2026-04-22) with a daily rotation CronJob (2026-04-23). **Session-2 intervention applied 2026-04-21 02:39Z**: cilium-agent memory limit raised from `1536Mi` → `2560Mi` (commit `0ab84e77`, ADR 0020) — see [`evidence-2026-04-21-cilium-memory-rca.md`](evidence-2026-04-21-cilium-memory-rca.md). **2026-04-23 20:45-20:47Z: two-node reboot cascade (k8s-3 + k8s-2) ~2h after re-admitting k8s-2 compute.** This falsifies the "k8s-2-specific hardware defect" framing — see [`evidence-2026-04-23-cluster-reboot.md`](evidence-2026-04-23-cluster-reboot.md). Investigation continues; plan 0007 is NOT closed.

**Reboot history during investigation:**
- ~12 pre-ADR-0020 on k8s-2 at 3-4h cadence (most uncaptured in Prometheus due to zombie outage)
- 2026-04-21 20:34Z: k8s-2 solo, ~18h after memory bump, no kernel trace
- 2026-04-23 20:45Z: **k8s-3** (first reboot of k8s-3 in the investigation)
- 2026-04-23 20:47Z: k8s-2, 2 min after k8s-3, ~11 min after re-admission pod cohort reached steady-state
- k8s-1: 0 reboots, 7d+ continuous uptime

**Top contested question — partially answered.** Prometheus is back on k8s-1 as of 2026-04-20 21:50Z (recovered via Longhorn Volume+Engine CR surgery — see plan 0007 Log). The `changes(node_boot_time_seconds[7d])` query now returns data but is **impaired by Prometheus's 26h zombie outage on k8s-2 earlier in the week**, so most historical reboots are absent from TSDB. Going forward TSDB is reliable; the ongoing-reboot pattern is already empirically confirmed from the session-1 uptime deltas and dmesg.

**Current dominant hypothesis:** unclear — re-opened after the 2026-04-23 two-node cascade. Five live candidates:

1. **cilium-agent cgroup memory pressure / OOM loop** — **primary suspect again under revised model.** ADR 0020 extended k8s-2 uptime from 3-4h to 45h+, but the 04-21 and 04-23 reboots both had upward cilium WSS/cache trajectories preceding them. The 04-23 event captured the spike live on k8s-2 (WSS 2048→2334 MiB in 10 min, Cache +593 MiB). Mechanism from [`evidence-2026-04-21-cilium-memory-rca.md`](evidence-2026-04-21-cilium-memory-rca.md) (page-cache accumulation inside the cgroup) still fits, but the trigger on 04-23 was clearly re-admission pod churn, not passive drift. Memory limit may need another bump.
2. **Kernel-config-induced silent hang** — still live. Talos kernel lacks `CONFIG_HARDLOCKUP_DETECTOR` / `CONFIG_SOFTLOCKUP_DETECTOR`; pure CPU spin-locks remain undetectable. All three unexplained reboots (04-21 and the 04-23 pair) show the silent-gap signature: network drop → ~30s silence → clean cold boot, no kernel trace.
3. **Distributed trigger on re-admission pod churn (NEW, 2026-04-23).** Scheduling a large cohort onto a previously-idle node may exercise a code path (CSI registration, Multus/whereabouts IPAM, seaweedfs volume registration, Longhorn engine attach, cilium endpoint reload) that induces memory or kernel-subsystem pressure across multiple nodes simultaneously. Two data points both happen during cilium-agent upward trajectories; the 04-23 cascade hit k8s-3 *as well as* k8s-2, and k8s-3 had not been the churn target — the mechanism may propagate via cluster-wide control plane state (cilium identity DB, Longhorn controller reconcile loop).
4. **Single-unit hardware defect on k8s-2's MS-01 chassis** — **weakened further** by k8s-3 now sharing the signature. Cannot be a k8s-2-only chassis issue unless two chassis concurrently defective. Keep alive only as a tail hypothesis; DIMM swap parked until operator returns ~2026-05-04.
5. **Longhorn unmount deadlock cascade** — **refuted.** k8s-2 Longhorn-drained throughout; k8s-3 (not drained) still rebooted. Not the driver.

Two hypotheses dismissed earlier: cilium-envoy restart trigger (restart count just mirrors reboot count; exit is normal Envoy hot-restart), supervisor automation (no kured / SUC installed).

## Relationship to existing docs

- **Personal ideas note** at `~/Development/notes/ideas/k8s-2-reboot-issues.md` — the original triage write-up. Contains the raw forensic timeline for the Apr 20 reboot. Not in the repo; don't duplicate. Referenced by the synthesis doc below.
- **context/hardware.md** — MS-01 inventory; any hardware confirmation/rejection should update hardware.md (not this folder).
- **ADR 0005 (Longhorn)** — relevant because the Apr 18 smoking gun is in Longhorn's shutdown behaviour.

## File index

| File | Purpose |
|---|---|
| [`README.md`](README.md) | This file — status + index |
| [`2026-04-20-multi-agent-rca.md`](2026-04-20-multi-agent-rca.md) | Synthesis of five parallel agent investigations (talos-operator, cluster-triage, observability-advisor, devils-advocate, simplifier) |
| [`evidence-2026-04-20-reboot-count.md`](evidence-2026-04-20-reboot-count.md) | Phase 1 step 1 — point-in-time boot epochs per node; documents Prometheus-zombie blocker |
| [`evidence-2026-04-20-talos-inspect.md`](evidence-2026-04-20-talos-inspect.md) | Phase 1 steps 3 + 5 — Talos watchdog config, kernel cmdline, dmesg, thermal, cilium-envoy restart status |
| [`evidence-2026-04-20-bios-matrix.md`](evidence-2026-04-20-bios-matrix.md) | Phase 1 step 4 — DMI-read BIOS versions per node + Minisforum MS-01 changelog 1.22→1.27 |
| [`corrigendum-2026-04-20-no-bmc.md`](corrigendum-2026-04-20-no-bmc.md) | Phase 1 step 2 is structurally void — MS-01 has no BMC/IPMI/Redfish; in-band Talos logging replaces it in Phase 2 |
| [`evidence-2026-04-21-cilium-memory-rca.md`](evidence-2026-04-21-cilium-memory-rca.md) | Session-2 hypothesis #4 investigation — mechanism (page-cache feedback loop, exit-137 smoking gun), intervention (limit 1536→2560 MiB), post-rollout observation loop data |
| [`evidence-2026-04-23-cluster-reboot.md`](evidence-2026-04-23-cluster-reboot.md) | Two-node reboot cascade (k8s-3 20:45Z + k8s-2 20:47Z) after k8s-2 re-admission. Silent-hang signature, pre-reboot WSS/cache spike, ranked recommendations |
| Rollout / execution state | [`../../plans/0007-k8s-2-remote-diagnostic-rollout.md`](../../plans/0007-k8s-2-remote-diagnostic-rollout.md) — mutable plan with Phase 1-5 tasks and session-by-session Log |

## Next files expected

As the investigation progresses, this folder should accumulate (without being prescriptive):

- `evidence-*.md` — raw outputs of the pre-work checks listed in the synthesis (Prometheus reboot count, BMC SEL, watchdog state, BIOS version). Dated.
- `action-plan.md` — the ordered list of interventions once pre-work narrows hypotheses.
- `rollout-log.md` — what was changed, when, and what happened after.
- `resolution.md` — the final cause, the fix, and a brief "lessons" section.

## Open questions (top of mind)

1. ~~What does `changes(node_boot_time_seconds[7d])` return?~~ **Partially resolved (session 1, 2026-04-20)** — Prometheus recovered on k8s-1; query now returns data. Still impaired by the 26h zombie outage that cost most of the historical reboot timestamps from TSDB. Going forward, reliable. See `evidence-2026-04-20-reboot-count.md` and plan 0007 Log.
2. ~~Is there anything in the MS-01 BMC SEL from the past week?~~ **Void** — MS-01 has no BMC. See `corrigendum-2026-04-20-no-bmc.md`.
3. ~~Is a Talos / kernel watchdog armed on this node?~~ **Resolved** — no Talos `runtime.watchdogTimer` configured on any node; iTCO_wdt is identical across k8s-1 and k8s-2. See `evidence-2026-04-20-talos-inspect.md`.
4. ~~Is BIOS `AHWSA.1.22` current?~~ **Resolved** — current is 1.27 (Apr 2025). k8s-1 is already on 1.26 and stable; k8s-2 and k8s-3 share 1.22 but only k8s-2 reboots, so BIOS is not the distinguishing factor. See `evidence-2026-04-20-bios-matrix.md`.
5. ~~Why do 15 pods remain in `Unknown` phase on k8s-2 *after* reboot?~~ **Hypothesis in hand (session 1, 2026-04-20)** — pattern is **containerd sandbox-name saturation surviving reboot**: old sandbox names remain reserved for stale container IDs, kubelet `StopPodSandbox` hits context deadlines trying to clean them, new pods stuck `ContainerCreating` indefinitely. Compounded by kubelet volume-reconciler saturation from `/var/lib/kubelet/` state that also persists across reboot. Documented in plan 0007 Log entries 2026-04-20#10–11. Full fix likely requires `talosctl reset` on k8s-2 to wipe `/var/lib/kubelet/`; deferred. **As of 2026-04-21 03:56Z**: still 7 stuck `ContainerCreating` pods on k8s-2 — unchanged by the cilium memory-limit intervention, as expected. Separate issue from hypothesis #1 / #4.

## Working rules for this folder

- One Markdown file per concern. Cross-link, don't copy.
- Use ISO date prefixes (`YYYY-MM-DD-*.md`) for evidence and timeline entries.
- Prefer tables for evidence and ranked hypotheses.
- Don't apply fixes from inside this folder — when ready, lift a concrete change into a `context/plans/` plan or a Talos/Flux manifest.
