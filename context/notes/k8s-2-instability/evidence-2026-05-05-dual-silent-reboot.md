# Evidence: 2026-05-05 sequential silent reboot of k8s-3 then k8s-1 (k8s-2 held)

**Date:** 2026-05-05
**Event (corrected 2026-05-05 evening):** 2026-05-05T**19:07:13Z** (k8s-3, verified via live `/proc/uptime`, boot ID `e55639d4…`) → 2026-05-05T**~19:33Z** (k8s-1 silent-reboot, postmortem estimate, not independently verifiable since overwritten by graceful reboot at 20:29:07Z). Δ ≈ **26 min**, **not** 28 s.
**Scope:** Re-cut the k8s-2-instability hypothesis space in light of an event whose signature is the inverse of every prior reboot in the investigation. This note is the closing evidence artifact for the BIOS-flash branch of plan-0009 Stage 4 and the opening evidence for whatever supersedes it.
**Operator:** wcygan (remote, off-LAN)

## ⚠ Correction — 2026-05-05 evening

This note was originally written under a **simultaneous within ~28 s** framing (k8s-3 19:33:54Z → k8s-1 19:34:22Z). That framing is **wrong**. Verified on the live cluster:

- k8s-3 actually booted **2026-05-05T19:07:13Z** (live `/proc/uptime`; boot ID `e55639d4…` matches the watch-loop's record)
- k8s-1 silent-rebooted at ~19:33Z (cannot independently verify; overwritten by 20:29:07Z graceful reboot which IS verified)
- k8s-2 did not reboot (still on the 2026-05-04T01:47:06Z BIOS-flash boot)

The actual pattern is **sequential, ~26 min apart, k8s-3 going first**. Hypothesis re-ranking implications:

- DAC #2 / shared-power / single-cluster-wide-stimulus hypotheses are **weaker** — a 26-min gap doesn't fit a single shared trigger
- "Kernel-level mechanism, cluster-wide-in-principle" (candidate #2 below) is **strengthened** — slow propagation between nodes fits a 26-min cascade
- New hypothesis: **k8s-3's failure was the trigger that broke k8s-1 26 min later** — investigate what state change on k8s-3 (kubelet/API blip recovery, etcd churn, network re-convergence) could have stressed k8s-1 during the gap

The candidate ranking and "checkable next" sections below were written before this correction. Re-evaluate before acting.

---

> The full operational record lives in [`../../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md) and is interpreted in [`../../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md). This file is intentionally narrower: it is the evidence-side bookkeeping that the k8s-2-instability investigation needs in order to know what happened, what is now falsified, and what should be tested next.

## Event signature in one paragraph

Two of the three control-plane nodes silent-rebooted within ~28 s of each other. The held node was k8s-2 — the node that has been the *only* silent-reboot offender for the entire prior investigation (R1–R9 in plan 0009 terms; ~12 events in plan 0007 terms before that). The two rebooted nodes span both BIOS versions (k8s-1 on un-flashed 1.26, k8s-3 on post-flash 1.27); the held node shares its BIOS with one of the rebooted (k8s-2 on post-flash 1.27). k8s-1 had never silently rebooted before in ~190 days of cluster age. No kernel-side trace was captured: the Vector kernel sink was torn down at 2026-05-04T~02:00Z (commit `4037deec`, plan 0007 Phase 5 file-side teardown), ~30 h before the event, with an explicit acceptable-trade note that came due in <2 days.

## Per-node state matrix

Boot IDs as captured by the bastion-side BIOS-flash watch loop (`1762a4f1`, 30-min cadence) at its 2026-05-05T19:54Z tick — the watch baseline was the post-flash boot of 2026-05-04T01:46Z.

| Node | BIOS | Pre-event boot ID (watch baseline) | Post-event boot ID (after silent reset) | Later post-recovery boot ID | Δ from baseline |
|------|------|------------------------------------|-----------------------------------------|-----------------------------|------------------|
| k8s-1 | **1.26** (untouched 2024-10-14 firmware) | `374d7bdd-530f-4e88-8194-8f66554b9ca8` | `3d007d1c-735f-46b3-baaa-84bef1525851` | `65fc58fd-26bb-44fe-91a3-f44eb5d421a5` (graceful reboot at 20:29Z to clear containerd wedge) | **CHANGED** twice |
| k8s-2 | **1.27** (post-flash 2026-05-04) | `28688229-2d15-4216-b028-8b558a5530fe` | `28688229-2d15-4216-b028-8b558a5530fe` | `28688229-2d15-4216-b028-8b558a5530fe` | **UNCHANGED** |
| k8s-3 | **1.27** (post-flash 2026-05-04) | `7cc9ced8-a46a-459f-b860-674df340d23b` | `e55639d4-9be7-4d73-a31d-0279a99abffe` | `e55639d4-9be7-4d73-a31d-0279a99abffe` | **CHANGED** |

Etcd held throughout: 3/3 healthy, k8s-2 leader at RAFT term 32, all members at synchronized applied index `177226274` immediately post-recovery. No leader election was triggered by the event.

## Forensic posture at T+0 of recovery

What we have:

- Boot-ID baseline diff from the bastion watch loop (above table)
- Earliest post-reboot dmesg timestamp on each rebooted node, giving the Δ ≈ 28 s gap
- `/proc/uptime` cross-check confirming the same window
- Prometheus TSDB on k8s-2 (the held node) — covers the entire window, including the seconds before the event
- Plan 0007 Phase 3 Vector log sink — application/container/syslog channel still live (not torn down)
- Containerd / kubelet event records on the rebooted nodes from after they came back up

What we do **not** have:

- Kernel-side trace / netconsole stream from k8s-1 or k8s-3 in the seconds preceding the reset. The Vector kernel sink (`KmsgLogConfig` + UDP/TCP receiver) was torn down at 2026-05-04T~02:00Z per the plan-0009 T+14h checkpoint. Ring-buffer dmesg from before the reboot is gone (cleared by the boot itself). This is the exact diagnostic surface that plan 0009 Phase 1 was built to provide; the trade-off note in the plan-0009 Log made the loss explicit, and it came due here.
- BMC / IPMI / Redfish logs (MS-01 has no BMC — see `corrigendum-2026-04-20-no-bmc.md`)
- Any pre-event power-rail / thermal telemetry beyond what node-exporter captures (no PDU-side logging)

## What this falsifies, weakens, strengthens, opens

Stated against the hypothesis ranking from `README.md` "Five live candidates, re-ranked 2026-04-24 (later)" plus the BIOS-fix narrative that motivated the 2026-05-04 flash.

### Falsified or materially weakened

- **#1 from 2026-04-24: "Single-unit hardware defect on k8s-2's MS-01 chassis."** Predicts only k8s-2 silently reboots. This event has k8s-2 holding while two *other* nodes reboot. The hypothesis cannot survive without significant rewriting (e.g. "k8s-2 chassis defect *plus* a separate dual-node trigger" — which is not a single hypothesis any more, it is two stacked).
- **BIOS-fix narrative (the basis for the 2026-05-04 1.22 → 1.27 flash on k8s-2 + k8s-3).** Predicts that the un-flashed node (k8s-1, 1.26) and/or the historically-fragile node (k8s-2, now 1.27) would be the next to misbehave. Reality: the un-flashed node *did* misbehave for the first time, but so did a *post-flash* node, while the historically-fragile post-flash node held. BIOS version is not predictive of susceptibility for this event. The flash may still have produced *some* mitigation (e.g. why k8s-2 specifically held), but it does not explain the new failure mode.
- **#3 from 2026-04-24: "kube-apiserver memory pressure on k8s-2 → cascading node-level stress."** Was already scoped to "stress amplifier on 04-23, does not explain 04-21"; with k8s-2 holding cleanly here, this is no longer load-bearing.
- **"Whatever caused R1–R9 only affects k8s-2."** Refuted in general by k8s-1 + k8s-3 silently rebooting. Either there are now ≥2 distinct mechanisms in play, or the mechanism was always cluster-wide and k8s-2 was just the most-frequent expression for unrelated reasons (load distribution, pod placement, an unfortunate prior).

### Strengthened

- **#2 from 2026-04-24: "Kernel-config-induced silent hang exposed by some pod-churn-adjacent stimulus."** This was already framed as cluster-wide-in-principle (Talos kernel has no `CONFIG_HARDLOCKUP_DETECTOR` / `SOFTLOCKUP_DETECTOR`, so any node that wedges produces this signature). The dual-node simultaneous expression is consistent with a shared kernel-level trigger that can take >1 node down when conditions align. No direct evidence — the kernel sink is gone — but the hypothesis is now the best-fit *survivor* of the prior ranking.
- **"Multus / VXLAN / CNI plumbing has cluster-wide failure modes that look like silent reboots"** (was a contributing factor on 04-23, not a primary). The 28-s gap between k8s-1 and k8s-3 reboots is suggestive of a propagating event, and CNI/data-plane is one of the few cluster-wide channels that crosses nodes near-simultaneously. Promoted from "contributing factor" to "candidate primary" pending Vector kernel sink restoration.

### New candidates introduced by this event

1. **Cluster-wide kernel/network/data-plane trigger that affects ≥2 nodes when conditions align.** Sub-variants:
   1a. Cilium / eBPF event that takes a kernel down on multiple nodes (e.g. a BPF map operation, a tail-call recursion, an XDP hook) — Cilium is the only cluster-wide kernel-mode software running across all three nodes
   1b. Multus / VXLAN storage-overlay event (per ADR 0017) — runs on all three nodes, kernel-side, and is plumbing across the per-node SFP+ mesh
   1c. Talos kernel module / sysctl change interacting with one of the above
2. **Power or electrical event affecting two of three Mini-PC chassis.** Sub-variants:
   2a. UPS topology — if k8s-1 and k8s-3 share a PSU group / outlet that k8s-2 is not on, a brownout or transient could drop the pair while sparing the third
   2b. Mains breaker / circuit shared by k8s-1 + k8s-3 outlets
   2c. PDU-side fault
   This is checkable with physical inventory of the rack/desk power topology and is the lowest-cost discriminating test for the dual-node-simultaneous shape.
3. **Concurrent-but-independent failure that happened to land within 28 s.** Hard to falsify directly, but priors are against it: 28-s coincidence on a population of three nodes after >190 days of single-node silence is not a flat-prior coincidence. Treat as a tie-breaker hypothesis only if (1) and (2) are both ruled out.

### Open

- **Why did k8s-2 hold?** k8s-2 is on post-flash BIOS 1.27 like k8s-3; the difference is not BIOS version. Possible factors: (a) load distribution (k8s-2 was etcd leader and may have been doing different work), (b) the held node happened to be off the propagation path of whatever stimulus took k8s-1 and k8s-3, (c) the BIOS flash mitigated *something* on k8s-2 specifically that is not present on k8s-3 for an unrelated reason. None of these are testable without the kernel-side trace channel back up.
- **Was the event triggered by something we can see in Prometheus TSDB on the held node?** k8s-2 was scraping metrics for itself and the others through the event window. A retrospective pass over the 19:30–19:34Z window for all three nodes' node-exporter, kubelet, container, network, and Cilium metrics is independently warranted and cheap.
- **Why did the kubelet on k8s-1 stop reporting on those specific pods 4 d 15 h before the reboot?** This is the postmortem AI-7 question. If a partial event went unnoticed days ago and is on the same mechanism as the 2026-05-05 trigger, that earlier event's timeline could be the missing data point. Checkable against Prometheus + Vector log sink (which *was* live in that window, even though the kernel sink was not).

## Discriminating tests for the next event

In rough order of cost (cheapest first), with the hypotheses each one moves:

| Test | Cost | Discriminates |
|------|------|---------------|
| **Re-stand up the Vector kernel sink before the next event** (postmortem AI-1) — restore `KmsgLogConfig` + receiver, verify kernel lines arriving on all three nodes | ~30 min, all software | Required for almost every hypothesis below — this is the missing forensic surface, not a discriminator. P0 prerequisite. |
| **Add `kube_pod_status_phase{phase="Unknown"}` and per-node `NodeUnexpectedReboot` PrometheusRules** (postmortem AI-2 + AI-3) — already done; commit landed at HEAD `40bb66a6` | done | Closes the detection gap; means the cluster's own alerting catches the next event without relying on the bastion loop. |
| **Audit physical power topology** — write down exactly which outlet / PDU port / breaker / UPS each MS-01 is on; capture as `evidence-2026-05-XX-power-topology.md` | ~10 min on next physical-access visit | If k8s-1 and k8s-3 share a power group that k8s-2 is not on, hypothesis (2) jumps to #1. If all three are on independent paths, (2) drops materially. |
| **Retrospective Prometheus pass over 19:30–19:34Z, 2026-05-05** for node-exporter + Cilium + Multus + kube-state metrics across all 3 nodes | ~1 h, software | Looks for a pre-event signature (memory step, CNI restart, IRQ storm, network burst). May surface (1a/1b) directly. Cheap and independent of physical access. |
| **Off-cluster reboot probes for k8s-1 and k8s-3** in the bastion `loop` style, distinct from the now-done `K8sNUnexpectedReboot` in-cluster alert. Belt-and-suspenders for the case where the cluster's own alerting is itself impacted | ~30 min | Same coverage as above; adds an external channel that survives cluster-wide failure modes. |
| **Stress-test the data-plane mesh** — run a controlled VXLAN-storage-overlay traffic burst across all three nodes with the kernel sink live, looking for the exact pre-reset signature | hours, low risk while operator is watching | Direct test of (1b). If a controlled burst produces the silent-reboot signature, the mechanism is localized. |
| **DIMM swap on k8s-2** (deferred from 2026-05-04 BIOS flash session) | physical access | Was the decisive test for the now-falsified "k8s-2 chassis defect" #1; under the new hypothesis space this is **deprioritized** — k8s-2 is the held node, not the victim. Still cheap to do during the next physical visit but no longer plan-critical. |
| **Cilium-side controlled experiments** — scale a workload that exercises a known-heavy BPF code path (e.g. service-mesh / encryption / large endpoint churn) with the kernel sink live | hours, medium risk | Direct test of (1a). |

## Disposition implication for plan 0009

This evidence note does not itself decide plan 0009's disposition (reopen / fork / close); the plan owns that decision. What this note provides is the inputs:

- The plan's stated acceptance criterion "(a) committed root-cause fix lands" is **not met**, and the 2026-05-05 event invalidates the prior leading hypothesis it was being chased against.
- The plan's stated acceptance criterion "(b) 14 consecutive days pass with zero unexplained reboots" is reset by this event; the previous longest-uptime streak across all three nodes ended at 19:33Z.
- Three of the plan's existing acceptance-criteria items are still individually deliverable (cilium memory alert, BIOS-posture documentation, the netconsole armature once restored), but they no longer add up to "k8s-2-only silent-reboot localized" — that framing is gone.

The most natural disposition is **fork**: close plan 0009 against the (now-falsified) k8s-2-only framing, citing this evidence note, and open a new plan against the cluster-wide / dual-node hypothesis space using this note's "Discriminating tests for the next event" table as its starting backlog. An alternative is **reopen with a re-scoped goal**, but the change in framing is large enough that a new plan keeps the history cleaner and avoids relitigating the closed acceptance items.

## Tooling / methodology notes

- The bastion-side `loop` cron job (off-cluster, 30-min cadence) was the *only* channel that detected this event in the first 21 minutes. The cluster's own alerting was structurally blind (only k8s-2 had a reboot rule). This is now closed by the postmortem AI-3 PrometheusRule generalization, but the lesson is worth preserving: an off-cluster watch loop running for an unrelated reason caught a failure the cluster could not self-detect. Keep at least one such loop around as a permanent fixture, not as a per-investigation prop.
- The forensic-channel teardown was *file-side only* (commit `4037deec`, plan 0007 Phase 5) — the actual `KmsgLogConfig` runtime resource may or may not have been removed from each node depending on how Talos handles the absence of a config document. The restoration step (postmortem AI-1, plan 0009 Phase 1 revival) should verify both file-side and runtime-side state on all three nodes before claiming the channel is live.
- Boot-ID watch baselines should not be reset to the *latest* observation — the value in the table above is that we have the post-flash 2026-05-04T01:46Z baseline preserved, which is what made the 2026-05-05T19:54Z diff legible. The bastion loop in this run did the right thing; future loops should follow the same pattern (capture once, diff against the captured value, do not auto-update on each tick).

## Cross-references

- Incident: [`../../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md) — full operational timeline, every recovery batch, every `kubectl` invocation
- Postmortem: [`../../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md) — root-cause analysis (split into trigger + amplifier + recovery friction), 12 prioritized action items, lessons learned
- Plan 0009: [`../../plans/0009-k8s-2-k8s-3-silent-reboot-followup.md`](../../plans/0009-k8s-2-k8s-3-silent-reboot-followup.md) — the plan whose hypothesis ranking this note re-cuts. Disposition decision pending.
- Plan 0007: [`../../plans/0007-k8s-2-remote-diagnostic-rollout.md`](../../plans/0007-k8s-2-remote-diagnostic-rollout.md) — origin of the Vector kernel sink that was torn down 30 h pre-event; origin of the ghost-pod recovery deadlock pattern that was the public-impact amplifier
- Vector kernel sink teardown commit: `4037deec` (2026-05-04T~02:00Z file-side teardown)
- Restoration commit (postmortem AI-1): `35533bdb feat(observability): restore Vector kernel sink (revert plan-0007 teardown)`
- New PrometheusRules (postmortem AI-2 + AI-3): `40bb66a6 feat(observability): alert on Unknown-phase pods + per-node reboot`
- Prior evidence: [`evidence-2026-05-04-bios-1.27-flash.md`](evidence-2026-05-04-bios-1.27-flash.md) — the BIOS flash whose hypothesis this event materially weakens; [`evidence-2026-04-30-web-research.md`](evidence-2026-04-30-web-research.md) — Raptor Lake "passes stress, fails at idle" pattern, NVMe/ASPM, DDR5 considerations (still load-bearing under the new dual-node hypothesis); [`README.md`](README.md) — the live hypothesis-ranking doc that this evidence note will trigger an update to
