---
status: Accepted
date: 2026-04-23
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: [0020]
superseded-by: null
retrospective: false
---

# 0021 — Raise cilium-agent memory limit to 3584Mi and enable clean-cilium-state

> Raise `cilium-agent.resources.limits.memory` from `2560Mi` to `3584Mi` and set `cleanState: true` on the `cleanCiliumState` init container. The 2560Mi ceiling did not eliminate the mechanism it was meant to contain; the 2026-04-23 two-node cascade is a near-exact match for cilium/cilium #42007 ("pods at or near memory limit + pod churn → BPF map entry corruption"). This ADR acknowledges the partial retraction of 0020's "durable fix" claim and ships the upstream-recommended mitigation.

## Status

Accepted

## Context

ADR 0020 (2026-04-21) raised the cilium-agent memory limit from the chart default 1536Mi to 2560Mi after a cgroup-WSS OOM mechanism was localized on k8s-2. 0020 framed the 2560Mi number as a "durable fix" on the grounds that it was ~1.5× the observed 1775 MiB pod-total WSS peak and that peer nodes sat at ~190 MiB steady state. Plan 0007's Phase 4 close cited 0020 as the outcome.

On 2026-04-23 20:45-20:47Z a two-node silent-reboot cascade hit k8s-3 and then k8s-2 within two minutes. k8s-1 was unaffected. The trigger was re-admitting k8s-2 earlier that day with a `PreferNoSchedule` taint; pod-scheduling churn landed a cohort on k8s-2 at ~20:36Z (cilium-operator + four CSI pods + seaweedfs-volume-1), and the reboot followed ~11 minutes later. The signature was the silent one that plan 0007 could not see from in-band channels: cold reboot, no kernel panic, no MCE, no oops. Plan 0009 was opened against it (see `context/notes/k8s-2-instability/evidence-2026-04-23-cluster-reboot.md`).

A research agent reviewing upstream cilium issues found a near-exact symptom match:

- [cilium/cilium #42007](https://github.com/cilium/cilium/issues/42007) — Cilium agent runs at or near its memory limit (common report: ~2.5 GiB) and, under pod churn, starts evicting BPF map entries or fails to repopulate them, manifesting as datapath connectivity corruption and, in some reports, node-level instability. The recommended remediations are (a) raise the limit by at least 1 GiB above observed steady-state and (b) set `cleanState: true` on the clean-cilium-state init container so that post-restart BPF state is rebuilt from scratch rather than inherited from the previous (possibly corrupted) cgroup.
- [cilium/cilium #37935](https://github.com/cilium/cilium/issues/37935) — Node churn causes a cluster-wide step-increase in cilium-agent memory: a reboot or eviction on one node forces endpoint re-discovery on every other node, which expands BPF maps on every node, not just the one that churned. This explains why a k8s-2 event can cascade to k8s-3: k8s-3's cilium-agent had to re-learn k8s-2's endpoints during re-admission churn, stepped its own WSS up, and by the time pod-scheduling churn landed on k8s-2 it had less cgroup headroom than a casual "peers are at 190 MiB" reading of 0020's numbers would suggest.

Live evidence, 2026-04-23 post-cascade, steady state with no pod churn:

| Metric | k8s-1 | k8s-2 | k8s-3 |
|---|---|---|---|
| `container_memory_working_set_bytes` (cilium-agent) | 221 MiB | 757 MiB | 752 MiB |
| Restart count | 0 | 2 | 0 (pod re-scheduled post-reboot) |

k8s-2 and k8s-3 cilium-agents sit at 3.4× k8s-1's steady state *in quiescence*. Under the next pod-churn event they will expand further. 2560Mi minus 752 MiB is 1808 MiB of headroom — plenty in absolute terms, but the 42007 mechanism does not require sustained pressure, only brief peaks that trigger BPF-map eviction. The mitigation pattern upstream advocates is a combination of a taller ceiling (so brief peaks have room) and `clean-cilium-state` on restart (so any node that does hit the ceiling doesn't propagate corrupted state on recovery).

## Decision

Apply two changes to `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`:

1. `resources.limits.memory`: `2560Mi` → `3584Mi`. Sizing rationale: the 42007 remediation is "at least +1 GiB above observed steady-state under the workload that triggered the event." Observed post-churn steady state is ~757 MiB. +1 GiB above the *peak* (1775 MiB observed on k8s-2 before the 0020 intervention) plus headroom for the #37935 cluster-wide step-increase rounds to 3584 MiB = 2048 + 1536 on a 128-MiB boundary. This is 4.7× k8s-1's current steady state, which is generous but not open-ended; a genuine memory leak would still be caught well below node-level pressure (MS-01 nodes have 96 GiB RAM each, so 3584 MiB is ~3.7% per node).
2. `cleanState: true` on the `cleanCiliumState` init container. This drops and recreates the BPF maps on every cilium-agent restart. Upstream #42007 identifies this as the guardrail against corruption-inheritance across a restart cycle. Trade-off: a ~10-20 s datapath interruption per cilium-agent restart, visible as a brief connectivity blip for pods on that node. We accept this as the cost of preventing a silent-reboot cascade.

Mark ADR 0020 `Superseded-by 0021`. ADR 0020's body stays immutable (anton rule). Plan 0007's Phase 4 close is retroactively qualified: the 2560Mi limit did reduce the OOM-killer cadence on k8s-2 for 48h, but did not close the mechanism — the mechanism's second face (BPF-state corruption under churn, without hitting the ceiling) surfaced on 04-23.

## Alternatives considered

- **Do nothing; trust 0020's 2560Mi ceiling** — rejected. The 04-23 cascade hit with *two nodes well below the ceiling* (757 MiB and 752 MiB, both ~30% of 2560Mi). Whatever killed them, it was not OOM. 42007 says the mechanism triggers on near-limit peaks and BPF map pressure, not on sustained saturation. Leaving the limit at 2560Mi would mean any future pod-scheduling event on a post-churn node lands in the same unsafe zone.
- **Raise the limit without `clean-cilium-state`** — rejected. #42007's remediation is explicitly the combination. Without clean-state, any node that does hit the ceiling restarts back into the same BPF state that triggered the event, and the restart doesn't recover. Setting `clean-cilium-state: true` is the surface that breaks the cycle.
- **Set `clean-cilium-state` without raising the limit** — rejected. Clean-state on a too-tight ceiling just makes the restart cycle louder: every restart temporarily doubles memory usage as old BPF maps are dropped and new ones allocated, and a too-tight limit may OOM during that very allocation. The two changes are coupled.
- **Bigger bump (e.g., 5120Mi or 6144Mi)** — rejected. 3584 MiB is already 2× the historical peak with a 4.7× safety margin against k8s-1's steady state. Larger values hide future regressions (a real memory leak would have ~2 GiB of additional runway to grow unnoticed before the alert in Phase 3 fires).
- **Smaller bump (e.g., 3072Mi)** — rejected. 3072Mi is only +512 MiB over 2560Mi; #42007's "at least +1 GiB" guidance is against observed peaks, not current headroom. 3072Mi is below the +1 GiB threshold relative to the 1775 MiB peak.
- **Drop to a host-level systemd slice or pin cilium-agent out-of-cgroup** — rejected as over-engineering for a single event. Plan 0009 Phase 6 leaves that door open if the mechanism recurs.
- **Pin the Multus secondary CNI interaction with `clean-cilium-state`** — ADR 0017 pairs Cilium with Multus for the Longhorn storage network. `cleanCiliumState` drops Cilium's BPF maps only; it does not touch Multus attachments, which are per-pod NetworkAttachmentDefinitions managed independently. No known interaction; flagged for verification on the first cilium-agent restart post-rollout.

## Consequences

### Accepted costs

- +1024 MiB headroom per node vs 0020's limit; +2048 MiB vs chart default. Total 3072 MiB additional reservation cluster-wide vs 0020. On 96 GiB nodes this is ~1.07% per node. Free.
- Each cilium-agent restart now takes ~10-20 s longer and causes a brief per-node datapath blip as BPF maps are rebuilt from scratch. On a rolling chart upgrade this is three sequential ~20 s blips, not a node blip — workloads with hostNetwork-aware health checks are the only thing that notices. Acceptable.
- Renovate-PR tax: none. `resources` is already overridden in-repo; chart bumps merge clean.
- 0020 is now the second ADR in a row on this same surface (0020 superseded within 2 days). That is unusual and worth naming. The root cause of that churn is the mechanism's two-face nature — 0020 closed the OOM-killer face, and this ADR closes the BPF-corruption face. The acceptance criterion for "we're done iterating on this" is plan 0009's 14-day stable-uptime window.

### Restore-runbook obligation

None — configuration decision, not stateful infrastructure.

### Lessons

- **A single upstream issue lookup at decision time would have shortened the 0020 → 0021 loop.** Plan 0007 investigated the mechanism with local evidence and a WSS-vs-RSS framing; it did not cross-reference upstream cilium issues. #42007 existed at the time 0020 was drafted; searching would have surfaced both the +1 GiB guidance and the `clean-cilium-state` pairing. Intake-time research is cheaper than retrospective research.
- **"Durable fix" is a claim that survives the next event, not a claim made after a short stable window.** ADR 0020's language implied closure; plan 0009 has now retracted it. Future ADRs in this series will downgrade the rhetoric: fixes are *observed stable for N days* until the next event, not durable in advance.
- **Per-node symptoms can mask cluster-wide mechanisms.** #37935's cluster-wide step-increase pattern would have been a plausible explanation for the 04-23 k8s-3 involvement even before #42007 was read, if it had been looked at. The correct mental model for cilium-agent memory is "every node's number moves together when any node churns."

## Follow-ups

- [ ] Update `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml` — limit `2560Mi` → `3584Mi`, set `cleanCiliumState.cleanState: true`, refresh the comment block to cite this ADR and retire the ADR 0020 reference. (Plan 0009 Phase 2 task.)
- [ ] After Flux reconciles, verify all three cilium-agents show the new limit; capture baseline WSS at T+5 min and T+60 min. (Plan 0009 Phase 2 task.)
- [ ] Author the cluster-wide `PrometheusRule` in plan 0009 Phase 3 — warning at >2048 MiB WSS for 5m, critical at >3072 MiB for 2m. This replaces 0020's deferred "75% of limit" alert with a tiered pair sized against the new ceiling.
- [ ] If the first cilium-agent restart under the new config interacts poorly with Multus (ADR 0017) — e.g., pods on the restarted node lose secondary CNI attachments — document it in plan 0009 Log and open a follow-up ADR.
- [ ] Verify in plan 0009 Phase 4 (controlled re-admission experiment) that this configuration holds under the same churn pattern that produced the 04-23 cascade.
