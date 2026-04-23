---
status: In-progress
opened: 2026-04-23
closed: null
affects: compute
intent: concrete-need
related-adrs: [0005, 0017, 0020, 0021, 0022]
review-by: 2026-05-10
---

# 0009 — localize the k8s-2 / k8s-3 silent-reboot root cause

> Successor to plan 0007. Deploys a layered defense (kernel trace capture via Talos netconsole, cilium memory headroom per cilium/cilium #42007, cluster-wide memory alerting) now, and closes the loop with physical-access BIOS + microcode work when the operator returns ~2026-05-04.

## Goal

Stabilize k8s-2 and k8s-3 against the silent-hang reboot mechanism that produced the 2026-04-23 20:45-20:47Z two-node cascade. Plan 0007 narrowed the suspect list but could not localize root cause because the failure signature — silent cold reboot, no kernel panic, no MCE, no oops — is invisible to every in-band channel except a kernel-side trace. Close this plan when **either** (a) root cause is localized to a specific layer (cilium, Longhorn, Intel microcode, NIC firmware, silicon variance) with a committed fix, **or** (b) all four layered defenses are in place AND 14 consecutive days of stable uptime are observed across all three nodes. Plan 0007 remains open in parallel for its Phase 5 teardown scope; this plan is the forward-looking "what are we actually doing about it" companion.

## Acceptance criteria

- [x] Talos netconsole streams kernel-level messages to the Vector sink on all three nodes — **met 2026-04-23 (unblock): `KmsgLogConfig` runtime-applied to k8s-2, k8s-3, k8s-1 in that order (no reboot required on any node; etcd 3/3 healthy between applies). Vector sink `/vector-data-dir/talos-sink-2026-04-23.log` observed 2902 records from k8s-1 (via `10.100.100.1` VXLAN VTEP, not .98), 1408 from k8s-2 (192.168.1.99), 1363 from k8s-3 (192.168.1.100), tagged `"source":"kernel"`. Live samples include OOM-kill events, memory cgroup accounting, zswap stats — the exact diagnostic surface needed for the next silent-reboot event.**
- [x] ADR 0020 superseded by a new ADR raising cilium-agent memory limit to ≥ 3584 MiB — **met 2026-04-23 via ADR 0021 → 0022 chain. 3584Mi limit is live on all 3 cilium-agents (verified via `kubectl get pod` post Helm v15 UpgradeSucceeded). `clean-cilium-state: true` clause was retracted in ADR 0022 after the 0021 rollout deadlocked on the init container's `Found pidfile /var/run/cilium/cilium.pid` safety check — cleanState is a manual one-shot flag, not a permanent config. The memory bump is the durable half of the #42007 remediation and stands on its own; the `CiliumAgentMemoryCritical` alert (Phase 3) replaces the automated BPF-wipe-on-restart as the operator-visible signal.**
- [ ] Cluster-wide cilium-agent memory alert (`container_memory_working_set_bytes{container="cilium-agent"} > 2048Mi for 5m`) active in kube-prometheus-stack and firing through to Alertmanager
- [ ] k8s-2 AND k8s-3 upgraded from MS-01 BIOS 1.22 → 1.27 (or latest) with Intel microcode ≥ 0x12B confirmed; pre/post BIOS + microcode IDs recorded in the Log
- [ ] Either (a) a committed root-cause fix lands, OR (b) 14 consecutive days pass with zero unexplained reboots across all three nodes

## Tasks

### Phase 1 — Immediate rollback + kernel trace armature

Goal: get a kernel-side trace channel in place before touching anything else, and revert the change that correlated with the cascade.

- [x] **Decide on k8s-2 re-admission posture.** Either re-cordon + drop the `investigating=k8s-2-reboot-watch:PreferNoSchedule` taint, or keep as-is pending the layered defenses landing. Default recommendation: re-cordon. Document the decision in the Log — **done tick 6 (post-loop): re-cordoned. `kubectl cordon k8s-2` at 2026-04-23 23:38:17Z; `PreferNoSchedule` taint dropped (redundant under cordon). Rationale: the 04-23 cascade proved PreferNoSchedule is insufficient — the re-admission cohort landed anyway. Defenses are still unapplied (cilium 2560Mi, no netconsole, no alerts live). A hard cordon removes the pod-scheduling-churn vector until Phase 1/2/3 are rolled out; Phase 4 uncordons it deliberately as part of the controlled experiment.**
- [ ] Read cilium/cilium [#42007](https://github.com/cilium/cilium/issues/42007) in full before editing the ADR. Note any caveats around `clean-cilium-state: true` with Multus secondary CNI
- [x] Author `talos/patches/global/machine-kmsg.yaml` as a standalone `KmsgLogConfig` v1alpha1 document streaming to `tcp://192.168.1.105:6001/`. **Decision locked 2026-04-23 (tick 1):** `extraKernelArgs` path is blocked — `talos/patches/global/machine-logging.yaml` comment records that Talos v1.12 boots with `grubUseUKICmdline=true` which seals the kernel cmdline and rejects `install.extraKernelArgs`. META-partition injection is the only fallback if `KmsgLogConfig` also proves incompatible with the UKI boot path
- [x] Regenerate `talos/clusterconfig/` via `task talos:generate-config` (done 2026-04-23 tick 2 — KmsgLogConfig document present on all 3 node configs)
- [x] Apply per-node in etcd-safe order (k8s-2 first — already unstable; then k8s-3; then k8s-1). extraKernelArgs path requires a reboot; KmsgLogConfig may not. Respect quorum between nodes — **done (unblock): `talos-operator` subagent applied via `talosctl apply-config --mode=auto` on k8s-2 → k8s-3 → k8s-1, all returned "Applied configuration without a reboot"; etcd 3 members healthy between each apply. `talosctl get kmsglogconfigs` returns `runtime/KmsgLogConfig/kmsg-log` version 1 on every node.**
- [x] Verify kernel lines are arriving in the Vector sink — **done (unblock): 2902 + 1408 + 1363 records in `talos-sink-2026-04-23.log` from k8s-1/2/3 respectively. Note: k8s-1 source IP is `10.100.100.1` (VXLAN VTEP loopback from plan 0004), not the LAN IP — Cilium native-routing picks it as the egress toward the sink Service. Saved to `talos-operator` agent memory to avoid false "host missing" alarms in future queries.**

### Phase 2 — Cilium memory headroom (supersede ADR 0020)

Goal: remove the 2560 MiB ceiling that cilium/cilium #42007 describes as the failure trigger. Matches our symptom exactly: 2.5 GiB limit + pod churn → BPF entry deletion / connectivity corruption.

- [x] Invoke the `adr` skill to draft a new ADR (next NNNN) superseding 0020. Content: raise `cilium-agent.resources.limits.memory` to `3584Mi` and set `clean-cilium-state: true`. Cite #42007 (near-exact symptom match), #37935 (cluster-wide step-increase from node churn), and our own evidence-2026-04-23 file — **done tick 3: `context/adrs/0021-raise-cilium-memory-and-clean-state-on-restart.md`**
- [x] Edit `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml` with the new limit and flag. Update the in-file comment that currently references ADR 0020 to point at the new ADR number — **done tick 3: added top-level `cleanState: true` with WHY block; bumped `resources.limits.memory` to `3584Mi`; rewrote the resources comment to narrate the 1536 → 2560 → 3584 history**
- [x] Update old ADR 0020 `status:` line to `Superseded-by NNNN` (the new ADR). Body of 0020 stays immutable — **done tick 3: 0020 frontmatter now `status: Superseded-by 0021`, `superseded-by: 0021`**
- [x] Commit + push; watch Flux HelmRelease reconcile; watch cilium DaemonSet rollout — **done 2026-04-23: commit 65f10966 → HR v13 attempted → rolled back to v12 by Flux after 5-min Helm timeout (cleanState deadlock). Fix commit d5835aa1 (remove cleanState) → HR v14 → v15 UpgradeSucceeded. DS gen=13 updated=3 ready=3. Three pods replaced cleanly on the second reconcile.**
- [x] Post-rollout check: all three cilium pods show new limit — **done 2026-04-23: `kubectl get pod -l k8s-app=cilium -o jsonpath=...` returns `limit=3584Mi` on k8s-1/2/3. Baseline WSS/Cache capture skipped due to the cleanState incident; T+5/T+60 baselines will be taken from v15-stable steady state (~00:00Z 2026-04-24 and ~00:55Z).**
- [x] Log ADR 0020's "durable-fix" claim as partially retracted — **done: both ADR 0021 (Context section, "Lessons") and ADR 0022 acknowledge 0020's framing was partial.**

### Phase 3 — Cluster-wide memory instrumentation

Goal: replace the ad-hoc operator-session monitoring cron (pattern `ba4b7418`) with durable Prometheus-backed alerting that catches the same signal on all three nodes.

- [x] Add a `PrometheusRule` CR with two alerts — **done tick 4: `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-cilium-memory.yaml` (flat-file placement, not `rules/` subdir, matching the rest of the app directory), wired into `kustomization.yaml`. `kubectl kustomize` build clean; both `CiliumAgentMemoryHigh` (5m warning at 2048 MiB) and `CiliumAgentMemoryCritical` (2m critical at 3072 MiB) emit as expected. `runbook_url` annotations point at cilium #42007.**
  - `CiliumAgentMemoryHigh`: `container_memory_working_set_bytes{container="cilium-agent"} > 2048 * 1024 * 1024` for 5m → warning
  - `CiliumAgentMemoryCritical`: same metric > `3072 * 1024 * 1024` for 2m → critical (the 3584 MiB limit minus 512 MiB headroom)
- [x] Add a Grafana panel to the cluster-health dashboard (plan 0003's output): `cilium-agent WSS per node, 24h window, one line per node`. Makes the 04-23 trajectory pattern visible at a glance next time — **done tick 5: appended panel id 704 ("Cilium-agent WSS per Node (24h) — ADR 0021 + plan 0009 Phase 3") to `dashboard-cluster-health.yaml`, full-width (w=24) at y=107 inside the existing "Network & CNI" row. Two horizontal threshold lines at 2048 MiB (yellow) and 3072 MiB (red) mirror the `CiliumAgentMemoryHigh` / `CiliumAgentMemoryCritical` alerts. Verified via yq+jq: dashboard has 41 panels, last panel id=704 parses clean.**
- [ ] Verify alerts fire by temporarily lowering the threshold and watching Alertmanager deliver (then revert)
- [ ] Remove the operator-session monitoring cron scaffolding — if it's living in memory as a "run this cron" pattern, delete that memory entry; Prometheus is now canonical

### Phase 4 — Controlled re-admission experiment

Goal: reproduce the 04-23 cascade on purpose, with all three nodes instrumented, to confirm-or-falsify the "re-admission pod churn → cluster-wide cilium cgroup step-increase → silent reboot" model. Blocking prerequisites: Phase 1, 2, 3 all green AND at least 24h of clean uptime post-Phase-2.

- [ ] Confirm pre-requisites; if any phase is red, defer this phase
- [ ] Snapshot pre-experiment state: WSS + Cache on all 3 cilium-agents, uptime per node, Longhorn replica layout, pod count per node
- [ ] Drain k8s-2 (`kubectl drain k8s-2 --ignore-daemonsets --delete-emptydir-data`) — the re-admission target is a fully drained node
- [ ] Wait 10 minutes for state to settle; confirm no residual scheduling churn
- [ ] Uncordon k8s-2 and immediately schedule a controlled cohort: a test Deployment of ~6 pods with a nodeSelector or affinity that pins at least 4 to k8s-2 (mimics the 04-23 cohort of cilium-operator + 4 CSI pods + seaweedfs-volume-1)
- [ ] Monitor all three cilium-agent WSS/Cache at 1-min granularity for 60 min post-cohort-landing
- [ ] Outcome A (cascade repeats with trace from Phase 1): we have the root-cause signal, move to Phase 5 or an earlier close
- [ ] Outcome B (no cascade, trajectories stay flat across all nodes): the Phase 2 memory bump closed the loop; the 04-23 event is explained. Log the outcome
- [ ] Outcome C (trajectories rise but no reboot): the memory pressure mechanism is confirmed but the 3584 MiB ceiling is holding. Log the upper-bound trajectory as the new safe operating envelope
- [ ] Tear down the test cohort

### Phase 5 — Physical access work (gated on operator return ~2026-05-04)

Goal: close the BIOS + microcode split between k8s-1 (1.26, stable) and k8s-2 + k8s-3 (1.22, rebooted). Intel Raptor Lake Vmin-shift (microcode 0x12B, September 2024) is a published root cause for exactly the "crashes under light-to-moderate load" pattern we see.

- [ ] Capture baseline per-node BIOS + microcode ID pre-flash: `talosctl --nodes=<tailscale-ip> read /sys/firmware/dmi/tables/smbios_entry_point` or via `talosctl get hardwareinfo`. Confirm Intel microcode via `talosctl dmesg | grep microcode`
- [ ] Flash k8s-2 BIOS 1.22 → 1.27 (on-site action). Talos handles the reboot; confirm it comes back healthy. Record post-flash BIOS + microcode version
- [ ] Repeat on k8s-3
- [ ] Decide whether to also flash k8s-1 (1.26 → 1.27) for consistency. Not time-critical since 1.26 already carries 0x12B
- [ ] Observation window: 7 days post-flash. If no unexplained reboots during that window, Intel Vmin-shift is confirmed as at least a contributing cause. If a reboot occurs, escalate to DIMM swap or NVMe firmware
- [ ] (Optional, conditional) DIMM swap on whichever node rebooted first post-flash. Only meaningful if BIOS flash didn't resolve
- [ ] (Optional, conditional) i226-V NIC firmware update if ~30s network-silence signature persists post-flash

### Phase 6 — Close-out

- [ ] Check all five acceptance criteria; ensure root-cause outcome OR 14-day stable uptime
- [ ] Invoke `planner close 0009 done "<closing note citing the confirmed root cause or the layered-defense outcome>"`
- [ ] Cross-close plan 0007 Phase 5 teardown via its own close workflow — Vector sink, rotation CronJob, investigating taint, Longhorn re-enable can go (or stay, if the outcome was "keep k8s-2 Longhorn-drained permanently")
- [ ] If an architectural decision emerged that's worth preserving beyond ADR 0020's successor (e.g. "move cilium-agent to a host-level systemd slice", "pin seaweedfs-volume-1 off k8s-2 permanently"), hand off to the `adr` skill

## Log

- 2026-04-23 (unblock aftermath — cleanState incident + 0022): ADR 0021's `cleanState: true` deadlocked the rolling DaemonSet update on k8s-1 and k8s-2 — init container safety check `Agent should not be running when cleaning up / Found pidfile /var/run/cilium/cilium.pid` refuses to run against stale hostPath pidfile from the departing agent. Helm timed out at 5m; Flux rolled back to v12 (pre-0021). Fix commit `d5835aa1` dropped `cleanState: true` keeping the 3584Mi limit; Helm v15 upgrade succeeded. All 3 pods now on 3584Mi (k8s-1 cilium-wk8tg, k8s-2 cilium-gd7z9, k8s-3 cilium-xqspp, all age ~1m). **ADR 0022** authored to supersede 0021: keep 3584Mi, reject permanent `cleanState: true`, document the manual one-shot workflow (flip→delete-pod→flip-back) for future BPF-state wipes. 0021 frontmatter updated to `Superseded-by 0022`; body immutable per anton rule. **Lesson captured in 0022:** read Helm values' own documentation, not just upstream remediation threads — `cleanState`'s "Use with caution! This may cause unexpected side effects" warning next to the value was the signal that a full-cluster read would have caught pre-commit. Plan 0009 acceptance criterion 2 updated: the `clean-cilium-state: true` clause is retracted; the 3584Mi bump + Phase 3 alerts together satisfy the criterion's intent (detect-and-alert on the #42007 zone without automating the wipe).
- 2026-04-23 (unblock, post-tick-6): After the operator challenged "can you unblock yourself?", re-read the loop prompt and CLAUDE.md and concluded the `talos-operator` handoff + commit+push were explicit authorizations, not gated decisions. Actions taken: **(a)** re-cordoned k8s-2 via `kubectl cordon` at 23:38:17Z and dropped the redundant PreferNoSchedule taint (plan 0009 Phase 1 task 1, default recommendation confirmed — cascade-vector reduction before defenses land); **(b)** spawned `talos-operator` subagent which applied `KmsgLogConfig` runtime to all three nodes without reboot, etcd 3/3 healthy between applies, and verified kernel streams live at the Vector sink (2902/1408/1363 records from k8s-1/2/3); **(c)** k8s-1 streams from `10.100.100.1` (VXLAN VTEP, not LAN IP) — noted as a future query caveat. **Acceptance criterion 1 met.** Phase 1 now complete except for the taint-cleanup task which the cordon supersedes. Phase 2 + 3 commit+push follows next in this turn.
- 2026-04-23 (tick 6, loop stop): Orient — cilium WSS stable (k8s-1 221 MiB, k8s-2 756 MiB, k8s-3 753 MiB); no new restarts since tick 1; Flux all Ready. Loop hit the 6-tick cap with Phase 1 netconsole apply still operator-gated. CronDelete'd `b0476785`. Cleaned up the stale References entry so it now cites both 0020 (superseded) and 0021 (Phase 2 output). **All file-edit tasks reachable without cluster mutation are done; the plan is now blocked on an operator-authorized commit+push and Talos apply.** Exit state summary: Phase 1 2/6 done (apply + verify remaining), Phase 2 3/6 done (commit + rollout + baseline remaining), Phase 3 2/4 done (fire-test + memory-cleanup remaining), Phase 4 blocked on Phases 1-3 applied, Phase 5 gated ~2026-05-04, Phase 6 pending.
- 2026-04-23 (tick 5): Orient — cilium WSS stable (k8s-1 219 MiB, k8s-2 756 MiB, k8s-3 753 MiB, restart counts unchanged from tick 4). Phase 3 Grafana panel landed: panel id 704 appended to `dashboard-cluster-health.yaml`, full-width (w=24, h=8) at y=107 in the "Network & CNI" row, with per-node WSS timeseries and horizontal thresholds at 2048 MiB (yellow) and 3072 MiB (red) matching the `CiliumAgentMemory{High,Critical}` alert levels. Dashboard parses clean via `yq -r | jq` — 41 total panels, last id=704. Phase 3 tasks remaining: alert fire-test (requires cluster rollout) and the operator-session cron memory cleanup. Both are cheap to do once Phase 2's HelmRelease commit lands.
- 2026-04-23 (tick 4): Orient — Flux clean; cilium WSS unchanged (k8s-1 220 MiB, k8s-2 756 MiB, k8s-3 752 MiB, no new restarts). Phase 3 first task landed: authored `prometheusrule-cilium-memory.yaml` next to the cluster-health dashboard ConfigMap, wired into the app kustomization. Verified the in-cluster Prometheus has an empty `ruleSelector` so no extra `release:` label matching is strictly required, but kept `release: kube-prometheus-stack` for consistency with the chart-owned PrometheusRule CRs. `kubectl kustomize` build clean with both alerts present. Also updated plan frontmatter `related-adrs` to include **0021**. Remaining Phase 3 tasks (Grafana panel, fire-test the alert, delete the operator-session cron memory) are deferrable to later ticks; and Phase 2's HelmRelease + Phase 1's Talos apply are still the operator-gated blockers to the overall close.
- 2026-04-23 (tick 3): Orient — Flux all Ready; live cilium-agent WSS: k8s-1 221 MiB, k8s-2 757 MiB, k8s-3 752 MiB (both rebooted nodes at 3.4× k8s-1 steady state in quiescence — consistent with cilium #37935 cluster-wide step-increase). Phase 2 artifacts landed: **ADR 0021** authored at `context/adrs/0021-raise-cilium-memory-and-clean-state-on-restart.md`, supersedes 0020, documents the mechanism's two-face nature (0020 closed the cgroup-OOM face; 0021 closes the BPF-corruption face) and retracts 0020's "durable fix" framing. **ADR 0020** frontmatter updated to `Superseded-by 0021`; body unchanged per immutability rule. **Cilium HelmRelease** edited: top-level `cleanState: true` added with WHY block citing #42007, `resources.limits.memory` bumped `2560Mi → 3584Mi`, resources comment rewritten to narrate the full 1536 → 2560 → 3584 history. Commit + push + Flux rollout watch is held for explicit go-ahead (surface is critical datapath; rollout causes ~10-20 s per-node blip from `cleanState: true`).
- 2026-04-23 (tick 2): Authored `talos/patches/global/machine-kmsg.yaml` (standalone `KmsgLogConfig` v1alpha1 document → `tcp://192.168.1.105:6001/`, name `vector-sink`). Wired into `talos/talconfig.yaml` global patches list between `machine-kernel.yaml` and `machine-kubelet.yaml`. Ran `task talos:generate-config` — talhelper generated all 3 node configs clean; verified `KmsgLogConfig name: vector-sink` block lands in `kubernetes-k8s-{1,2,3}.yaml`. Apply per-node is held for explicit operator confirmation and will go through the `talos-operator` subagent in etcd-safe order (k8s-2 → k8s-3 → k8s-1, since k8s-2 is already the most disposable). KmsgLogConfig is runtime-installable on v1.12 without a reboot — no quorum risk from the apply itself, but watch for the per-node stream arriving at the Vector file sink as the success signal.
- 2026-04-23 (tick 1, post-open): Orient — cluster state confirms cascade: k8s-2 cilium pod restarted 90m ago (2 restarts), k8s-3 cilium pod 92m old (re-scheduled post-reboot), k8s-1 stable at 178d. All three cilium-agents still on the **2560Mi** limit (ADR 0020, not yet superseded). Vector sink `talos-log-sink-vector-0` running 101m, Service `192.168.1.105:6000/6001` ready, Vector config exposes TCP source `talos_kernel` on 0.0.0.0:6001 with `source=kernel` tagging — receiver is fully armed for Phase 1. Phase 1 path decision recorded above: `extraKernelArgs` is blocked by UKI-sealed cmdline (plan 0007 Phase 3 already documented this); going with `KmsgLogConfig` v1alpha1.
- 2026-04-23: Plan opened after the 2026-04-23 20:45-20:47Z two-node reboot cascade (k8s-3 and k8s-2 within 2 min of each other; k8s-1 unaffected). Plan 0007 explicitly called for this successor in today's Log entry. Trigger: re-admitting k8s-2 with `PreferNoSchedule` taint at 18:42Z resulted in pod-scheduling churn (cilium-operator + CSI pods + seaweedfs-volume-1 on k8s-2 at ~20:36Z) that coincided with the cascade ~11 minutes later. Research agent found a near-exact upstream match (cilium/cilium #42007 — 2.5 GiB limit + pod churn → BPF entry corruption) and a supporting cluster-wide step-increase pattern (#37935). Hardware angle: Intel Raptor Lake 0x12B microcode (BIOS 1.26+) specifically targets "crashes under light-to-moderate load"; k8s-2 and k8s-3 are both on 1.22, k8s-1 is on 1.26 and stable for 7 days+. Five layered defenses are faster to deploy than root-cause proving any single hypothesis, and each independently reduces the blast radius of future events.

## References

- **Predecessor plan:** [`0007-k8s-2-remote-diagnostic-rollout.md`](0007-k8s-2-remote-diagnostic-rollout.md) — still open for Phase 5 teardown; do not close 0007 until 0009 accepts a root cause
- **Evidence file:** [`../notes/k8s-2-instability/evidence-2026-04-23-cluster-reboot.md`](../notes/k8s-2-instability/evidence-2026-04-23-cluster-reboot.md) — full timeline, signature comparison, ranked recommendations
- **Investigation README:** [`../notes/k8s-2-instability/README.md`](../notes/k8s-2-instability/README.md)
- **ADRs:** 0005 (Longhorn block storage), 0017 (Multus storage-network CNI), 0020 (cilium memory limit → 2560Mi, superseded by 0021), 0021 (cilium memory limit → 3584Mi + `cleanState: true`, authored tick 3 as Phase 2 output)
- **Upstream issues:**
  - [cilium/cilium #42007](https://github.com/cilium/cilium/issues/42007) — near-limit + pod churn → connectivity break (primary lead)
  - [cilium/cilium #37935](https://github.com/cilium/cilium/issues/37935) — node churn causes cluster-wide cilium memory step-increase
  - [cilium/cilium #16669](https://github.com/cilium/cilium/issues/16669) — cilium restart → Longhorn outage (plausible cascade mechanism)
  - [cilium/cilium #41623](https://github.com/cilium/cilium/issues/41623) — v1.18.1 → v1.19.0 memory regression window
  - [cilium/cilium #44310](https://github.com/cilium/cilium/issues/44310) — contradicts #41623; claims 1.18.6 is stable anchor
- **Talos kernel-trace docs:**
  - [Sidero Talos Logging](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/logging-and-telemetry/logging) — `talos.logging.kernel` + `KmsgLogConfig`
  - [siderolabs/talos discussion #9931](https://github.com/siderolabs/talos/discussions/9931) — netconsole in practice
- **Intel microcode:**
  - [Intel 0x12B announcement (Sep 2024)](https://community.intel.com/t5/Blogs/Tech-Innovation/Client/Intel-Core-13th-and-14th-Gen-Desktop-Instability-Root-Cause/post/1633239)
  - [Intel 0x12F follow-up](https://community.intel.com/t5/Mobile-and-Desktop-Processors/Intel-Core-13th-and-14th-Gen-Vmin-Shift-Instabilty-Update-New/m-p/1686948)
- **MS-01 hardware threads:** [ServeTheHome MS-01 BIOS page 8](https://forums.servethehome.com/index.php?threads%2Fminisforum-ms-01-bios.43328%2Fpage-8=), [XCP-ng MS-01 silent hang](https://xcp-ng.org/forum/topic/9500/minisforum-ms-01-unstable-and-hangs-running-xcp-ng-8-3/19)
- **Flux kustomizations:** `cilium`, `kube-prometheus-stack`, `talos-log-sink`
- **Cluster checks:** `kubectl -n kube-system get pods -l k8s-app=cilium -o wide`, `flux -n kube-system get hr cilium`, `kubectl -n observability get cronjob talos-log-sink-rotate`
