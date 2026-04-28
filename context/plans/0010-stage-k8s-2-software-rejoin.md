---
status: Done
opened: 2026-04-24
closed: 2026-04-28
affects: compute
intent: concrete-need
related-adrs: [0005, 0017, 0018, 0020, 0021, 0022]
review-by: 2026-05-15
---

> **Closed by abort, not by completion (2026-04-28).** Stage A passed its
> 24 h watch window cleanly, then k8s-2 produced 6 silent reboots in the
> following ~63 h with no in-cluster trigger. Software-side hardening
> spaced the failures out but did not suppress them. Per Phase 5's
> closing bullet, the abort handoff goes to plan 0009 (hypothesis
> ranking now leads with a k8s-2-specific DDR5/BIOS hardware delta) and
> a future physical-access plan. Multi-agent synthesis is at
> `context/notes/k8s-2-instability/evidence-2026-04-28-plan0010-four-agent-synthesis.md`.

# 0010 — stage k8s-2 software rejoin

> Re-admit k8s-2 as useful compute through software-only hardening, staged scheduling, and explicit burn-in gates before any physical hardware work.

## Goal

Return k8s-2 to serving compute capacity without touching hardware yet, while reducing the known pod-admission/CNI/control-plane stress paths that exposed the last silent reboot. Done means k8s-2 either completes a staged rejoin and 7-day burn-in under normal observability, or the plan captures a recurrence with enough evidence to block full rejoin and hand off to hardware or kernel/firmware work.

## Acceptance criteria

- [ ] k8s-2 is protected by a persistent hard rejoin gate (`NoSchedule` taint or equivalent) until selected workloads intentionally tolerate it.
- [ ] CNI plumbing, kubelet node reservations, and CNI/apiserver observability are hardened enough that a pod-creation burst is visible before it becomes a blind node-level event.
- [ ] k8s-2 stale kubelet/containerd state is either cleared by a planned software reset/rejoin or explicitly judged non-blocking with current evidence.
- [ ] k8s-2 completes staged re-admission: limited cohort for 24h, selected compute for 48h, then 7 consecutive days with no unexplained reboot, CNI restart spike, or relevant OOMKilled event.
- [ ] Abort criteria are documented and exercised if recurrence happens, including netconsole/vector capture and a clear handoff to plan 0009 or a hardware-access successor.

## Tasks

### Phase 0: Baseline and Scope Lock

- [x] Confirm current k8s-2 state: cordon/taints, `node_boot_time_seconds`, pod count, `Unknown`/`ContainerCreating` pods, Longhorn node/replica health, CNI DaemonSet restart counts, and Vector kernel sink health.
- [x] Update plan 0007 with a short log entry that k8s-2 rejoin execution moved to plan 0010; leave 0007 focused on diagnostic rollout and teardown.
- [x] Update plan 0009 stale framing only where it can mislead active work: k8s-3 was operator-rebooted, the +950MiB apiserver number was a duplicate-scrape artifact, and rejoin testing now belongs here.
- [x] Freeze unrelated high-churn cluster work during rejoin windows: no Harbor drain drills, Longhorn maintenance, Cilium upgrades, Talos upgrades, or broad Flux reconciliations unless they are part of this plan.

### Phase 1: Scheduling Guardrails

- [x] Add a persistent k8s-2 rejoin label and hard taint in Git-managed node config, e.g. `anton.io/rejoin=k8s-2` and `anton.io/rejoin=k8s-2:NoSchedule`.
- [x] Verify the rendered Talos config and live Kubernetes node state agree after apply; do not rely on an imperative taint that disappears after reset/rejoin.
- [x] Define the first tolerated workload cohort: low-risk compute only, no Harbor, CNPG, Dragonfly, SeaweedFS, Longhorn replica placement, observability singletons, or cluster-critical controllers.
- [ ] Add or verify topology spread / anti-affinity on high-churn stateful components so a drain cannot pile replicas or sidecars onto k8s-2 in one burst.

### Phase 2: Resource Headroom

- [x] Author and validate the existing Multus memory hardening (`256Mi` to `512Mi`); deployment remains pending.
- [ ] Deploy Multus memory hardening and verify the DaemonSet rolls cleanly.
- [x] Add Whereabouts memory request/limit headroom; current evidence does not prove OOM, but it is CNI-critical and was noisy in the 04-23 window.
- [x] Raise `storage-vxlan` from `32Mi/64Mi` to `64Mi/128Mi`, then verify its manifest renders cleanly.
- [x] Add `priorityClassName` to Multus, Whereabouts, storage-vxlan, and any required CNI-adjacent DaemonSets after checking rendered manifests.
- [x] Add kubelet reservations in `talos/patches/global/machine-kubelet.yaml`: initial target `systemReserved.memory=2Gi`, `kubeReserved.memory=2Gi`, `evictionHard.memory.available=2Gi`, plus conservative CPU reservations.
- [x] Apply Talos kubelet reservation changes per node with etcd quorum checks and record pre/post allocatable memory.

### Phase 3: Observability and Abort Signals

- [x] Add `prometheusrule-cni-plumbing.yaml` covering Multus, Whereabouts, and storage-vxlan restart spikes, memory-near-limit, and OOMKilled reasons.
- [ ] Add dashboard panels for CNI plumbing memory/restarts and per-apiserver watch pressure.
- [x] Add alerts or panels by apiserver instance for `apiserver_longrunning_requests`, `rate(apiserver_watch_events_total[1m])`, `apiserver_current_inflight_requests`, and `apiserver_flowcontrol_*`.
- [ ] Confirm the Vector/Talos kernel stream is still live for k8s-2 before any uncordon step.
- [x] Define abort criteria in the plan log before rejoin: any k8s-2 boot-time change, CNI restart spike, CNI OOMKilled event, unexplained apiserver WSS growth, Longhorn degraded-replica storm, or missing netconsole stream.

### Phase 4: Stale-State Cleanup Decision

- [x] Re-check whether k8s-2 still has stale kubelet/containerd sandbox-name or volume-reconciler state from the earlier reboot recovery.
- [ ] If stale state remains, draft an explicit Talos reset/rejoin runbook with etcd snapshot, etcd member health, Longhorn replica health, wipe scope, and rollback steps.
- [ ] Execute the reset/rejoin only after the runbook is reviewed in this plan; do not run ad hoc reset commands.
- [x] If reset is deferred, record why the remaining state is not a blocker for staged compute rejoin.

### Phase 5: Staged Rejoin

- [x] Stage A: uncordon k8s-2 while keeping the hard rejoin taint; schedule 5-10 low-risk tolerated compute pods and observe for 24h. — **Stage A passed cleanly. Launched 2026-04-24T18:31:52Z; 8 smoke pods on k8s-2; 24 h watch closed 2026-04-25T18:31:52Z with zero abort signals. Reboots resumed ~60 min after window close — see Phase 5 abort bullet below.**
- [ ] Stage B: allow selected compute workloads to tolerate k8s-2 for 48h; keep stateful/storage/observability-critical workloads excluded. — *Not reached; aborted before Stage B.*
- [ ] Stage C: remove or relax the hard rejoin taint only after Stage A/B pass and the operator accepts the residual risk. — *Not reached.*
- [ ] Burn in for 7 consecutive days after normal scheduling resumes. — *Not reached.*
- [x] If any abort criterion fires, immediately re-cordon k8s-2, preserve evidence, and decide whether recurrence belongs to plan 0009 or a new physical-access plan. — **Fired 2026-04-28T~14:59Z. Abort action executed: `kubectl cordon k8s-2`; Flux-managed smoke Deployment left wired as forensic evidence; abort note `evidence-2026-04-28-plan0010-stage-a-abort.md`; four-agent synthesis `evidence-2026-04-28-plan0010-four-agent-synthesis.md`. Recurrence handed off to plan 0009 and a future hardware-access plan.**

## Log

- 2026-04-24: Plan opened after the software-side rejoin review concluded that k8s-2 is not mitigated for normal scheduling, but can be brought back through staged scheduling, CNI hardening, node-reservation headroom, and burn-in gates before touching hardware.
- 2026-04-24: Cross-linked plan 0007 so the old remote-diagnostic rollout now points at this plan for k8s-2 rejoin execution.
- 2026-04-24: Phase 0 baseline captured in `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-baseline.md`. k8s-2 is `Ready,SchedulingDisabled`, has only the unschedulable taint, has 22 assigned pods all `Running`, no restart/OOM increments in the last 6h, Longhorn scheduling disabled due to cordon, and Vector is still receiving k8s-2 kernel-source records.
- 2026-04-24: Corrected stale plan 0009 framing that could mislead active work: k8s-3 was operator-rebooted, the +950MiB apiserver number was a duplicate-scrape artifact (corrected +456MiB WSS/+454MiB RSS), and k8s-2 rejoin execution now belongs to this plan.
- 2026-04-24: Authored and locally validated repo-side hardening, not yet deployed: Multus `512Mi` plus `system-node-critical`, Whereabouts `128Mi/512Mi` plus `system-node-critical`, storage-vxlan `64Mi/128Mi` plus `system-node-critical`, kubelet reservations/eviction headroom in Talos, and a CNI plumbing PrometheusRule. Validation included `kubectl kustomize` for touched app kustomizations, Talos config generation through `mise exec -- task talos:generate-config`, and `talhelper validate talconfig`.
- 2026-04-24: Added the persistent k8s-2-only rejoin gate in `talos/talconfig.yaml`: `anton.io/rejoin=k8s-2` label and `anton.io/rejoin=k8s-2:NoSchedule` taint. Generated Talos configs render the gate only in `kubernetes-k8s-2.yaml`; all three node configs validate with `talosctl validate --mode=metal`. Not applied live yet.
- 2026-04-24: Stale-state recheck recorded in `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-stale-state.md`. Current 04-20-style blocker is gone: no `Unknown` or `ContainerCreating` pods, and Talos/containerd has no non-ready sandbox/container states. Reset/rejoin is deferred before Stage A because the remaining Longhorn stopped replica CRs are a storage/full-rejoin gate, not a limited compute-only blocker.
- 2026-04-24: Added `prometheusrule-k8s-2-rejoin-abort.yaml` with k8s-2-specific abort/watch alerts: boot-time change, apiserver WSS growth over 384MiB/20m, apiserver longrunning jump, watch-event burst, and APF queue. PromQL expressions parsed successfully against live Prometheus. Abort criteria for Stage A/B: immediately re-cordon k8s-2 and stop staged scheduling if any critical abort alert fires, any CNI restart/OOM alert fires, Vector/Talos kernel stream is missing, Longhorn reports degraded/failed volume or rebuild storm tied to k8s-2, or kube-apiserver WSS/watch alerts coincide with new pod churn.
- 2026-04-24: Scheduling gates recorded in `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-scheduling-gates.md`. Freeze is active for unrelated high-churn work. Stage A cohort is low-risk stateless compute/test pods only, preferably a purpose-built `playground/k8s-2-rejoin-smoke` Deployment with 5-10 replicas, no PVCs, ordinary Cilium networking, explicit `anton.io/rejoin` toleration, and required k8s-2 placement. Existing stateful/storage/observability/control-plane workloads remain excluded until Stage C/full rejoin.
- 2026-04-24: Phase 2 Talos rolling apply of commit `1918ca07` complete across all three control planes in order k8s-2 → k8s-3 → k8s-1, each `--mode=auto` returning `Applied configuration without a reboot`. etcd quorum 3/3 held with leader k8s-1 and raft term 29 unchanged throughout; allocatable dropped cleanly to capacity − 6 GiB on all nodes (k8s-1 92279416Ki, k8s-2 92286412Ki, k8s-3 92239116Ki). k8s-2 now carries the persistent `anton.io/rejoin=k8s-2` label and `anton.io/rejoin=k8s-2:NoSchedule` taint on the live Node object in addition to the pre-existing cordon. No pod eviction storm, Flux all-Ready. Evidence: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-talos-apply.md`. Stage A uncordon remains a separate later gate.
- 2026-04-24: Phase 3 Vector/Talos kernel stream liveness re-verified for k8s-2 before uncordon: 15 `source:kernel` records from `192.168.1.99` in the last ~50 MB of the sink file, last burst captured the Talos apply's kubelet-restart sequence at `2026-04-24T17:49:{10,11,12}Z`. Pipe healthy.
- 2026-04-24: Phase 5 Stage A launched at 18:31:52Z. Wire step was a single-line append of `./k8s-2-rejoin-smoke/ks.yaml` to `kubernetes/apps/playground/kustomization.yaml` (commit `f69f6507`); cluster-apps rejected it with "namespace not specified" because the playground namespace kustomization was missing the top-level `namespace: playground` directive — fixed in `d8ae298d`. `kubectl uncordon k8s-2` dropped only the cordon taint; `anton.io/rejoin=k8s-2:NoSchedule` persisted. 8 smoke pods transitioned Pending → ContainerCreating → Running within seconds, all on k8s-2 with distinct Cilium IPs in 10.42.2.0/24. k8s-2 `node_boot_time_seconds` unchanged, no CNI restart spike, zero abort-relevant alerts active. Stage A 24 h watch window runs to 2026-04-25T18:31:52Z. Evidence: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-stage-a.md`.
- 2026-04-28: **Stage A abort fired and plan closed.** Stage A's 24 h watch window passed cleanly, but k8s-2 began rebooting silently ~60 min after window close and produced **6 silent reboots in ~63 h** (mean inter-reboot 10.5 h, dispersed in time-of-day; k8s-1 and k8s-3 had zero reboots in the same window). Trigger fired during a `/loop` tick: `changes(node_boot_time_seconds[3d])` reported 6 for k8s-2 vs 0 for k8s-1/k8s-3, and k8s-2 uptime was only 4.35 h. Abort action executed per the plan and per the standing `/loop` instruction: `kubectl cordon k8s-2` (cordon taint added 14:59:37Z; persistent `anton.io/rejoin=k8s-2:NoSchedule` retained). Flux-managed smoke Deployment **left wired** as forensic evidence; smoke pods all show 6 restarts with `lastTermination.reason=Unknown` synchronous with each boot. Abort evidence note: `context/notes/k8s-2-instability/evidence-2026-04-28-plan0010-stage-a-abort.md`. Spawned four read-only investigators (kernel-log miner against the Vector sink; Prometheus metric correlator; cluster-triage hardware/Talos angle; temporal pattern analyst); all four converged on hardware/firmware below the in-cluster observation horizon, with a k8s-2-only DDR5 SKU/speed delta (Mushkin 5200 MT/s vs Crucial 5600 MT/s on k8s-1/k8s-3) and BIOS AHWSA.1.22 as the strongest hooks. Synthesis: `context/notes/k8s-2-instability/evidence-2026-04-28-plan0010-four-agent-synthesis.md`. Plan status moves to `Done`; recurrence ownership moves to plan 0009 (hypothesis ranking updated there) and to a future physical-access plan once cheap in-band falsifiers (k8s-1 negative control + UDP netconsole) have run.

## References

- Software rejoin analysis: `context/notes/k8s-2-instability/2026-04-24-software-rejoin-options.md`
- Investigation workspace: `context/notes/k8s-2-instability/README.md`
- Corrected apiserver/whereabouts evidence: `context/notes/k8s-2-instability/evidence-2026-04-24-apiserver-and-whereabouts.md`
- Hardware/firmware survey: `context/notes/k8s-2-instability/evidence-2026-04-24-hardware-firmware-survey.md`
- Phase 0 execution baseline: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-baseline.md`
- Staged hardening evidence: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-staged-hardening.md`
- Stale-state recheck: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-stale-state.md`
- Scheduling gates: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-scheduling-gates.md`
- Phase 2 Talos apply: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-talos-apply.md`
- Stage A launch: `context/notes/k8s-2-instability/evidence-2026-04-24-plan0010-stage-a.md`
- Harbor drain/CNI OOM source: `context/plans/0006-adopt-harbor-seaweedfs.md`
- Prior diagnostic rollout: `context/plans/0007-k8s-2-remote-diagnostic-rollout.md`
- Silent-reboot follow-up: `context/plans/0009-k8s-2-k8s-3-silent-reboot-followup.md`
- CNI manifests: `kubernetes/apps/network/multus/`, `kubernetes/apps/network/whereabouts/`, `kubernetes/apps/network/storage-vxlan/`
- Talos kubelet config: `talos/patches/global/machine-kubelet.yaml`
