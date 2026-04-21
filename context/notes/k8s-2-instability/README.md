# k8s-2 instability — investigation workspace

**Problem in one line:** k8s-2 has rebooted repeatedly over the past week (counting method contested — see open question below), k8s-1 and k8s-3 have been stable over the same window.

This folder is the working record for diagnosing, instrumenting, and fixing the instability. It is **not** an ADR (those are in `context/adrs/`, immutable) and **not** a plan (those are in `context/plans/`, execution state). It is a scratchpad that may graduate into an ADR (for the structural fix, e.g. "we committed to Talos logging destinations") and/or a plan (for the rollout).

## Current status

**Phase:** Post-intervention observation — [plan 0007](../../plans/0007-k8s-2-remote-diagnostic-rollout.md) owns the rollout. Phase 2 kernel panic sysctls (`kernel.panic=10`, `kernel.panic_on_oops=1`) are live on all 3 nodes. Phase 3 Vector log sink is scaffolded in `kubernetes/apps/observability/talos-log-sink/` on standby (deployed but not yet collecting — activation gated on a one-line wire-up in `talos/talconfig.yaml`). **Session-2 intervention applied 2026-04-21 02:39Z**: cilium-agent memory limit raised from `1536Mi` → `2560Mi` (commit `0ab84e77`) — see [`evidence-2026-04-21-cilium-memory-rca.md`](evidence-2026-04-21-cilium-memory-rca.md). This folder remains the evidence scratchpad; execution state lives in plan 0007.

**Last known reboot on k8s-2:** 2026-04-20 **21:39 UTC** (~12th observed; Kubernetes Ready transition captured as plan 0007 Phase 1 baseline). A graceful `talosctl reboot --mode=default` was performed at 22:20 UTC during recovery — does not count as a failure-mode reboot. As of 2026-04-21 03:56Z, k8s-2 uptime is 5.17h and climbing — **past the upper bound of the pre-intervention 3-4h reboot cadence**, no reboot observed since the memory-limit bump.

**Top contested question — partially answered.** Prometheus is back on k8s-1 as of 2026-04-20 21:50Z (recovered via Longhorn Volume+Engine CR surgery — see plan 0007 Log). The `changes(node_boot_time_seconds[7d])` query now returns data but is **impaired by Prometheus's 26h zombie outage on k8s-2 earlier in the week**, so most historical reboots are absent from TSDB. Going forward TSDB is reliable; the ongoing-reboot pattern is already empirically confirmed from the session-1 uptime deltas and dmesg.

**Current dominant hypothesis:** unclear. Four live candidates (revised 2026-04-20 after session 1 discoveries):
- **Longhorn CSI unmount deadlock → dirty reboot retry loop** (direct evidence from Apr 18). Currently under **natural-experiment observation**: k8s-2 is organically drained (0 running Longhorn replicas, `Ready=False` with `ManagerPodDown`) yet reboots continued through the drain. If the cadence truly stopped since 17:48Z, this trends toward **refuted**; if a new reboot lands, **live**. 72h observation window closes 2026-04-23 21:39Z.
- Silent hardware watchdog (`iTCO_wdt` / `softdog`): **weakened** — hardware present identically on k8s-1, no Talos process opens `/dev/watchdog`, so the iTCO should be dormant unless soft-arming-then-starving behaviour emerges. See `evidence-2026-04-20-talos-inspect.md`.
- Hardware: thermal / NVMe hang / stale MS-01 BIOS (`AHWSA.1.22` from Mar 2024): **partially strengthened, partially refuted.** Single-node pattern + silent-hang-friendly kernel config still strongly single-unit-defect-shaped. **BIOS alone is refuted as the cause**: k8s-3 shares 1.22 with k8s-2 and is stable (up 96h); k8s-1 was already on 1.26. See `evidence-2026-04-20-bios-matrix.md`.
- **cilium-agent OOM feedback loop** (refined 2026-04-21 from original hypothesis #4): the original hypothesis had the right node and right subsystem but wrong mechanism. Not a cluster-wide memory pressure driving many cilium-cni helpers to die — it's a **self-perpetuating page-cache accumulation inside the cilium-agent cgroup** that repeatedly hit the 1536 MiB memory limit and OOMKilled the agent. Previous `cilium-agent` on k8s-2 has `exitCode: 137` (SIGKILL from kernel OOM-killer) at `2026-04-20T22:45:56Z`. Each restart re-loaded BPF ELFs and state files, generating page cache inside the cgroup; WSS climbed back toward the limit within ~4h, OOMKilled again. Intervention: memory limit raised to `2560Mi` (commit `0ab84e77`, landed 2026-04-21 02:39Z). Full mechanism analysis and post-intervention observation data in [`evidence-2026-04-21-cilium-memory-rca.md`](evidence-2026-04-21-cilium-memory-rca.md). **Currently trending confirmed**: 5h+ post-rollout without reboot, cache pegged at 2 MiB (vs 166 MiB pre-rollout anomaly), zero restarts.

Two hypotheses dismissed this session: cilium-envoy restart trigger (restart count just mirrors reboot count; exit is normal Envoy hot-restart), supervisor automation (no kured / SUC installed).

**Dominant remaining candidates (ranked after session 2 intervention):**
1. **cilium-agent OOM feedback loop** — trending **confirmed** as root cause. Smoking-gun exit code 137 captured, mechanism characterized (page cache inside cgroup, not RSS / endpoints / BPF maps), intervention deployed, 5h+ post-rollout observation showing fix is holding. Final verdict pending 24h uptime (~22:20Z today) for durable-fix claim and 72h (2026-04-23 21:39Z) to close the plan 0007 Phase 1 window.
2. **Single-unit hardware defect on k8s-2's MS-01 chassis** — DIMM, NVMe, thermal paste, VRM, or PCH-specific silicon variance. The DIMM-swap test is the decisive experiment but parked until operator returns 2026-05-04. **Weakened** by the cilium-agent mechanism finding — the "anomaly" on k8s-2 was software-state, not hardware — but keep alive until the 72h observation window closes without a reboot.
3. **Kernel-config-induced silent hang** — now partially-armed: `kernel.panic_on_oops=1` live, but Talos kernel lacks `CONFIG_HARDLOCKUP_DETECTOR` / `CONFIG_SOFTLOCKUP_DETECTOR` so pure CPU spin-locks remain undetectable. Panic sysctls will catch an explicit BUG()/oops but not a silent wedge. Moot if #1 is confirmed.
4. **Longhorn unmount deadlock cascade** — **refuted**. k8s-2 was organically drained throughout the intervention window (0 live replicas), reboots continued regardless while drained — inconsistent with Longhorn being the driver.

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
