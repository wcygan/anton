# k8s-2 instability — investigation workspace

**Problem in one line:** k8s-2 has rebooted repeatedly over the past week (counting method contested — see open question below), k8s-1 and k8s-3 have been stable over the same window.

This folder is the working record for diagnosing, instrumenting, and fixing the instability. It is **not** an ADR (those are in `context/adrs/`, immutable) and **not** a plan (those are in `context/plans/`, execution state). It is a scratchpad that may graduate into an ADR (for the structural fix, e.g. "we committed to Talos logging destinations") and/or a plan (for the rollout).

## Current status

**Phase:** Post-intervention observation plus staged software rejoin. [Plan 0007](../../plans/0007-k8s-2-remote-diagnostic-rollout.md) still owns diagnostic rollout/teardown, [plan 0009](../../plans/0009-k8s-2-k8s-3-silent-reboot-followup.md) owns root-cause capture, and [plan 0010](../../plans/0010-stage-k8s-2-software-rejoin.md) now owns k8s-2 rejoin execution. Phase 2 kernel panic sysctls (`kernel.panic=10`, `kernel.panic_on_oops=1`) are live on all 3 nodes. Phase 3 Vector log sink is LIVE on all three nodes (activated 2026-04-22) with a daily rotation CronJob (2026-04-23). **Session-2 intervention applied 2026-04-21 02:39Z**: cilium-agent memory limit raised from `1536Mi` → `2560Mi` (commit `0ab84e77`, ADR 0020) — see [`evidence-2026-04-21-cilium-memory-rca.md`](evidence-2026-04-21-cilium-memory-rca.md). **2026-04-23 20:47Z: k8s-2 silently rebooted during Harbor drain-induced churn; the nearby k8s-3 reboot was operator-initiated, not a cascade.** Investigation continues; plan 0007 is NOT closed.

**Reboot history during investigation (corrected 2026-04-24):**
- ~12 pre-ADR-0020 on k8s-2 at 3-4h cadence (most uncaptured in Prometheus due to zombie outage)
- 2026-04-21 20:34Z: k8s-2 solo, ~18h after memory bump, no kernel trace, no identifiable pre-reboot trigger (Prometheus shows no CNI spike pre-reset)
- 2026-04-23 20:47Z: k8s-2 silent, exit 255, during Harbor drain-induced churn on k8s-1/k8s-2 (Multus OOMKilled ×4 on k8s-1 during the same window per plan 0006 Log)
- 2026-04-23 20:45Z: **k8s-3 was NOT a silent reboot** — operator-initiated `talosctl reboot` at 20:44:37Z as Harbor plan 0006 acceptance test; confirmed 2026-04-24 via plan 0006 Log line 115. k8s-3 has never silently rebooted during the investigation.
- k8s-1: 0 reboots, 7d+ continuous uptime

**Silent-reboot total: 2 events, both on k8s-2** (04-21 and 04-23). k8s-3 reboot was intentional; early analysis mis-identified it as a cascade.

**Top contested question — partially answered.** Prometheus is back on k8s-1 as of 2026-04-20 21:50Z (recovered via Longhorn Volume+Engine CR surgery — see plan 0007 Log). The `changes(node_boot_time_seconds[7d])` query now returns data but is **impaired by Prometheus's 26h zombie outage on k8s-2 earlier in the week**, so most historical reboots are absent from TSDB. Going forward TSDB is reliable; the ongoing-reboot pattern is already empirically confirmed from the session-1 uptime deltas and dmesg.

**Current dominant hypothesis — rewritten 2026-04-24 (later) after peer-agent falsification review.** Three earlier claims were wrong: (a) "two-node cascade" — k8s-3 was an operator-intentional reboot (plan 0006 Harbor test), k8s-3 has never silently rebooted; (b) "whereabouts OOMKilled 10 times" — exit code 1 (Error), not 137 (OOM); (c) "BIOS split explains difference via microcode" — runtime microcode is identical (0x00006134) across all 3 nodes. See `evidence-2026-04-24-cni-restart-counts.md` addendum for the full falsification detail.

**Corrected framing:**

Two unexplained silent reboots, both on k8s-2 (2026-04-21 20:34Z solo, 2026-04-23 20:47Z during Harbor-induced churn). k8s-1 and k8s-3 have zero silent reboots. The shared feature is **k8s-2 specifically**, not "BIOS-1.22 nodes" (k8s-3 is also 1.22 and is stable). Pre-reboot memory trajectory on k8s-2 at 20:30-20:46Z on 04-23 was dominated by **kube-apiserver +456 MiB WSS / +454 MiB RSS growth after cAdvisor scrape dedupe** (809 → 1265 MiB WSS), not by the re-admission cohort. The earlier +950 MiB number was a double-scraped `sum by (...)` artifact. See [`evidence-2026-04-24-apiserver-and-whereabouts.md`](evidence-2026-04-24-apiserver-and-whereabouts.md).

**Five live candidates, re-ranked 2026-04-24 (later):**

1. **Single-unit hardware defect on k8s-2's MS-01 chassis** — **re-strengthened** now that k8s-3 is out of the cascade framing. Only k8s-2 silently reboots; k8s-1 (BIOS 1.26) and k8s-3 (BIOS 1.22) are both stable. The BIOS-version confound is out because microcode is identical. DIMM, NVMe controller, thermal paste, VRM, or PCH silicon variance on k8s-2's chassis all fit the "k8s-2 only" pattern. DIMM-swap experiment is the decisive next physical-access test.
2. **Kernel-config-induced silent hang exposed by some pod-churn-adjacent stimulus** — Talos kernel has no `CONFIG_HARDLOCKUP_DETECTOR` / `CONFIG_SOFTLOCKUP_DETECTOR`, so a CPU wedge produces exactly the silent-reset signature we see. Netconsole (plan 0009 Phase 1, applied 2026-04-23) is the asymmetric bet — if the next event on k8s-2 produces a pre-reset kernel message, hypothesis narrows; if silent again, hypothesis gains weight.
3. **kube-apiserver memory pressure driving cascading node-level stress (NEW 2026-04-24)** — kube-apiserver on k8s-2 grew +456 MiB WSS / +454 MiB RSS in the 16 min before the 04-23 silent reboot after correcting for duplicate cAdvisor scrapes. The follow-up Prometheus pass found a watch/longrunning jump at 20:46Z, not a giant ordinary request/LIST storm; this remains a possible 04-23 stress amplifier but does not explain the 04-21 reboot.
4. **CNI OOM/pod-admission cascade (Multus/Whereabouts/VXLAN)** — **real, documented, and PARTIALLY explains 04-23 but not 04-21.** Plan 0006 Log for 04-23 records Multus OOMKilled ×4 on k8s-1 during Harbor drain; peer review found matching 20:36Z Multus OOM on k8s-3 pre-drain-reboot. Whereabouts restarts on k8s-2 are fallout from the k8s-2 silent reboot, not cause. CNI OOM does not on its own cause node reset anywhere in upstream precedent (peer review searched cilium/cilium, multus-cni, whereabouts issues). Treat CNI hardening (Multus 256→512 Mi bump + alerts) as independently justified for cluster stability, not as the reboot root cause.
5. **cilium-agent cgroup memory pressure / OOM loop** — **real on 04-20, not demonstrated on 04-23 or 04-21.** ADR 0020 (1536 → 2560 Mi) closed the 04-20 exit-137 OOMKill cycle per Prometheus. ADR 0021 (2560 → 3584 Mi) is defensible preventive headroom against upstream cilium #42007; not a reactive fix for the silent reboots.

**Refuted:** Longhorn unmount deadlock cascade (k8s-3 not Longhorn-drained yet never silently rebooted); "CNI × microcode two-layer cascade" (microcode identical across nodes; cascade didn't happen).

**Open threads worth pursuing:** (a) netconsole capture of the next k8s-2 event, (b) DIMM-swap / memtest86+ on k8s-2 when operator returns, (c) BIOS-settings diff / normalization, (d) whether the 04-21 k8s-2 solo reboot had any identifiable trigger that is not visible in the current Prometheus window.

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
| [`evidence-2026-04-23-cluster-reboot.md`](evidence-2026-04-23-cluster-reboot.md) | Original 04-23 reboot write-up with later addendum correcting the cascade framing: k8s-3 was operator-initiated; only k8s-2 silently rebooted |
| [`evidence-2026-04-24-cni-restart-counts.md`](evidence-2026-04-24-cni-restart-counts.md) | CNI-layer DaemonSet restart counts across the 04-23 window — Multus/Whereabouts/VXLAN on all 3 nodes including "stable" k8s-1, which weakens the "k8s-1 escaped the trigger" story and sharpens the two-layer hypothesis |
| [`evidence-2026-04-24-apiserver-and-whereabouts.md`](evidence-2026-04-24-apiserver-and-whereabouts.md) | Corrected apiserver memory attribution after cAdvisor scrape dedupe; 04-23 watch/longrunning spike; 04-21 comparison; whereabouts previous-log cause |
| [`evidence-2026-04-24-hardware-firmware-survey.md`](evidence-2026-04-24-hardware-firmware-survey.md) | Read-only hardware/firmware survey: BIOS/microcode, EDAC counters, NIC/NVMe firmware, temps, netconsole sink health |
| [`2026-04-24-software-rejoin-options.md`](2026-04-24-software-rejoin-options.md) | Software/cluster-side mitigation and staged k8s-2 rejoin options before any physical hardware work |
| [`evidence-2026-04-24-plan0010-baseline.md`](evidence-2026-04-24-plan0010-baseline.md) | Plan 0010 execution baseline: k8s-2 cordon/pod state, boot epochs, CNI counters, Longhorn state, Vector sink state, and staged repo-side hardening validation |
| [`evidence-2026-04-24-plan0010-staged-hardening.md`](evidence-2026-04-24-plan0010-staged-hardening.md) | Plan 0010 repo-side hardening: persistent k8s-2 rejoin taint/label, CNI memory/priority changes, kubelet reservations, and CNI alert rule validation |
| [`evidence-2026-04-24-plan0010-stale-state.md`](evidence-2026-04-24-plan0010-stale-state.md) | Plan 0010 stale-state recheck: no current `Unknown`/`ContainerCreating` pods, clean containerd statuses, remaining Longhorn stopped replica CRs, and reset/rejoin judgment |
| [`evidence-2026-04-24-plan0010-scheduling-gates.md`](evidence-2026-04-24-plan0010-scheduling-gates.md) | Plan 0010 scheduling gates: rejoin freeze, Stage A cohort definition, and topology/anti-affinity review |
| [`evidence-2026-04-29-memtester-stage2.md`](evidence-2026-04-29-memtester-stage2.md) | Stage 2 in-OS memtester pass on k8s-2 (32 GiB mlock'd, 92 min, clean) — what it falsifies, what it does NOT falsify, and why Stage 3 (multi-core load/thermal) and Stage 4 (boot-time memtest86+) remain uncovered |
| Rollout / execution state | [`../../plans/0007-k8s-2-remote-diagnostic-rollout.md`](../../plans/0007-k8s-2-remote-diagnostic-rollout.md) for diagnostic rollout/teardown; [`../../plans/0010-stage-k8s-2-software-rejoin.md`](../../plans/0010-stage-k8s-2-software-rejoin.md) for staged k8s-2 rejoin |

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
