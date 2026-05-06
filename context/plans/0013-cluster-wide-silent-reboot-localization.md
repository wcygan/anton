---
status: In-progress
opened: 2026-05-05
closed: null
affects: compute
intent: concrete-need
related-adrs: [0017, 0021, 0022]
related-postmortems: [2026-05-05-k8s-1-k8s-3-dual-silent-reboot]
supersedes-plan: 0009
review-by: 2026-06-05
---

# 0013 — localize cluster-wide silent-reboot mechanism (successor to 0009)

> Re-cut of the silent-reboot investigation after the 2026-05-05 dual-node event falsified plan 0009's k8s-2-only premise. Closes the postmortem's 12 action items and decides between localized fix, layered-defenses + extended uptime, or accept-and-mitigate.

## Goal

Following the 2026-05-05T19:33Z dual silent-reboot of k8s-1 + k8s-3 (with k8s-2 holding cleanly), localize the actual silent-reboot mechanism — now known to be cluster-wide capable, with dual-node simultaneous expression on offer, and with BIOS version not predictive of susceptibility. Drive the 2026-05-05 postmortem's 12 action items to closure. End in one of three terminal states: **(a)** a localized root cause is identified and a committed fix lands, OR **(b)** the layered defenses (kernel-side trace surface, per-node reboot detection, Unknown-pod alerting, HA on critical-path Deployments) are in place and 14 consecutive days of zero unexplained reboots are observed across all three nodes, OR **(c)** mechanism remains unlocalized after the watch window AND mitigations are sufficient — explicitly accept and live with it, document the residual risk.

## Acceptance criteria

- [ ] Vector kernel sink demonstrably captures kernel-side trace through the *next* silent-reboot event on whichever node(s) it hits — closes the AI-1 forensic gap that bit us on 2026-05-05 (sink torn down at `4037deec`, restored at `35533bdb`)
- [ ] Cluster self-detects any-node unexpected reboot AND `Unknown`-phase pod accumulation via PrometheusRules firing through to Alertmanager — closes the AI-2 + AI-3 detection blindness exposed when `K8s2UnexpectedReboot` was the only reboot rule and detection came from an off-cluster bastion loop
- [ ] Physical power topology (PDU port / outlet / breaker / UPS group per MS-01) is documented; the dual-node-shared-power hypothesis (postmortem trigger candidate 2 / evidence-2026-05-05 candidate 2) is resolved as confirmed or refuted
- [ ] Critical-path single-replica Deployments (`network/cloudflare-tunnel`, `network/envoy-gateway`, `tailscale/operator`) are HA *or* explicitly accepted as 1-replica with documented rationale; if HA, anti-affinity / topology-spread is verified to behave correctly when peer pods are in `Unknown` phase (AI-4 + AI-9)
- [ ] One of: **(a)** localized root cause identified with committed fix landed; **(b)** 14 consecutive days of zero unexplained reboots across all three nodes with the new forensic surface live; **(c)** explicit accept-and-mitigate decision recorded as an ADR with the residual-risk rationale

## Tasks

### Phase 1 — Forensic surface live and self-detection in place (P0, mostly done)

- [x] AI-1: Restore Vector kernel sink — commit `35533bdb`. (Verification of through-event capture is the open-ended Phase 4 task, not this checkbox.)
- [ ] AI-1 verification: confirm `KmsgLogConfig` runtime resource present on all 3 nodes (`talosctl get kmsglogconfigs`), Vector receiver Service has endpoints, kernel records arriving in the daily sink file from k8s-1 (note: k8s-1 source is VTEP `10.100.100.1` per cilium native-routing, not LAN IP), k8s-2, k8s-3
- [x] AI-2: PrometheusRule on `kube_pod_status_phase{phase="Unknown"}` — commit `40bb66a6`
- [ ] AI-2 fire-test: synthetic Unknown pod (force-pause kubelet on a sacrificial workload, or use the existing investigation playground) → alert lands in Alertmanager → cleared
- [x] AI-3: Generalize `K8s2UnexpectedReboot` to per-node `NodeUnexpectedReboot` family — commit `40bb66a6`
- [ ] AI-3 fire-test: a controlled `talosctl reboot --mode=default` on one node → all three of the new per-node series exercised at least once → confirm the right one fires and the other two do not
- [ ] Carry-over from plan 0009 acceptance criterion 3: cluster-wide cilium-agent memory alert (`container_memory_working_set_bytes{container="cilium-agent"} > 2048Mi for 5m`) verified end-to-end through to Alertmanager. The rule lives in `prometheusrule-cilium-memory.yaml` per plan-0009 tick-4 2026-04-23, but the fire-test was never run

### Phase 2 — Cheap retrospective passes against the held node's data (P1, software-only, no physical access required)

- [ ] Retrospective Prometheus pass over 19:30–19:34Z 2026-05-05 across all 3 nodes' node-exporter / Cilium / Multus / kube-state / kube-apiserver / etcd metrics. Look for: pre-event memory step, CNI restart, IRQ storm, network burst, BPF map operation spike, eviction signal, anything that crosses a node boundary. The held node's TSDB covers the entire window
- [ ] AI-7: Investigate ghost-pod accumulation root cause on k8s-1. Why did kubelet stop reporting on those specific pods 4 d 15 h before the reboot (i.e. ~2026-05-01T05Z)? Check the Vector log sink (which *was* live in that window) and journalctl/talosctl logs from k8s-1 around 2026-05-01T04–06Z. If a partial event went unnoticed and is on the same mechanism as 2026-05-05, that earlier event's timeline could be the missing data point
- [ ] Cross-correlate plan 0007 / plan 0009 ring-buffer dmesg evidence from prior k8s-2 silent reboots against the new dual-node fingerprint. Are there shared signals (network-silence cliffs, specific kernel subsystems quiet) that would have been visible on 2026-05-05 if the kernel sink had been live?

### Phase 3 — Discriminating tests for the next event (P1, mix of cheap and physical-access-gated)

- [ ] **Power topology audit** (cheapest discriminator for postmortem-trigger-hypothesis 2). Write down exactly which outlet / PDU port / breaker / UPS each MS-01 is on. Capture as `context/notes/k8s-2-instability/evidence-2026-05-XX-power-topology.md`. Outcomes: (i) k8s-1 and k8s-3 share a power group that k8s-2 is not on → hypothesis 2 jumps to #1, propose UPS or PDU isolation; (ii) all three on independent paths → hypothesis 2 drops materially
- [ ] Off-cluster reboot probes for k8s-1 and k8s-3 in the bastion `loop` style, distinct from the now-done in-cluster `NodeUnexpectedReboot` rule. Belt-and-suspenders against cluster-wide failure modes that could impact the cluster's own alerting
- [ ] Controlled data-plane mesh stress test with kernel sink live: scale a workload that exercises VXLAN-storage-overlay traffic across all three nodes, looking for the pre-reset signature directly. Tests cluster-wide candidate 1b (Multus / VXLAN overlay)
- [ ] Controlled Cilium / eBPF heavy code-path test with kernel sink live: scale a workload that exercises a known-heavy BPF path (service-mesh / encryption / large endpoint churn). Tests cluster-wide candidate 1a (Cilium / eBPF)
- [ ] Carry-over from plan 0009 Phase 5: i226-V NIC firmware survey across all 3 nodes. Read current firmware version, check vendor for stability-relevant releases. Was promoted in plan 0009 tick-2 2026-04-24 to "first-class because the ~30 s network-silence signature is an ethernet-path fingerprint" — that signature is now part of a dual-node event, which makes the ethernet-path angle stronger, not weaker
- [ ] (Deprioritized but not discarded) DIMM swap on whichever node next presents during a physical-access window. k8s-2 was the prior target under the now-falsified single-unit hypothesis; under the cluster-wide hypothesis space, no specific node is privileged. Cheap to do during the next physical visit, but no longer plan-critical

### Phase 4 — Wait-for-next-event capture (open-ended, runs continuously)

- [ ] Maintain the bastion-side off-cluster watch loop indefinitely (the 30-min cron loop that caught 2026-05-05 was running for an unrelated reason). Promote it from "per-investigation prop" to a permanent fixture
- [ ] When the next event fires: capture kernel-side trace from the Vector sink (now live), capture per-node reboot alert from the in-cluster path (now live), capture Unknown-pod alert if/as ghosts re-accumulate (now live). Write up as `context/incidents/<date>-...` + `context/postmortems/<date>-...` + `context/notes/k8s-2-instability/evidence-<date>-....md` per the established convention
- [ ] If a kernel trace *is* captured: localize the failure mechanism to the named subsystem in the trace; propose targeted fix; close criterion (a)
- [ ] If kernel sink stays silent through the next event: the failure happens below kernel logging horizon (hard CPU wedge / microcode-induced reset / power event). Promote the power-topology + NIC-firmware paths to top priority; reconsider whether DIMM swap on the next-presenting node moves up

### Phase 5 — HA on critical-path Deployments (P1, software-only)

- [ ] AI-4 — `network/cloudflare-tunnel`: bump to ≥2 replicas with topology-spread / anti-affinity. Verify Cloudflare side accepts multiple connector replicas to the same tunnel (it does — Cloudflare load-balances across them)
- [ ] AI-4 — `network/envoy-gateway`: bump to ≥2 replicas with topology-spread / anti-affinity. Verify the Envoy Gateway controller chart supports HA without leader-election conflicts
- [ ] AI-4 — `tailscale/operator`: bump to ≥2 replicas if the operator chart supports HA. If it does not, document the constraint and accept the 1-replica posture explicitly
- [ ] AI-9: Investigate `envoy-external` topology-spread interaction with `Unknown`-phase peer pods. The 2026-05-05 incident showed both running replicas ended up on k8s-1 because the prior peers (now Unknown ghosts) on other nodes were satisfying anti-affinity from the API's perspective. Likely needs `whenUnsatisfiable: DoNotSchedule` plus careful label-exclusion of Unknown-phase pods; may not be expressible — investigate and document the result either way

### Phase 6 — Operator runbooks and chaos drill (P2/P3)

- [ ] AI-5: Document the direct-kubeconfig fallback (`talosctl kubeconfig` → sed server URL to a Tailscale IP → `--insecure-skip-tls-verify` due to cert SAN mismatch) in the `anton-remote-access` skill. The 2026-05-05 incident used this workaround for ~30 min; it should not be ad-hoc
- [ ] AI-11: Author `unwedge-after-node-reboot.md` runbook documenting the batched force-delete + cordon + graceful-reboot recovery sequence. This is the second time it has been needed (plan 0007 day-1 + 2026-05-05); promote from pattern recognition to documented procedure
- [ ] AI-8: Add a quarterly chaos-engineering drill — rotate one node's pods (cordon + drain) and verify all critical paths remain serving. Would have surfaced the latent ghost-pod accumulation days earlier on 2026-05-05
- [ ] AI-10: External uptime probe (Cloudflare Workers / GitHub Action / Hetzner cron) for `<public-site-A>` and `<public-site-B>`. Closes the gap where the platform learns about user-facing outages independently of cluster health
- [ ] AI-12: Investigate `seaweedfs-volume-1` PVC pinning to k8s-1 — should this volume be free to attach anywhere, or is the pin intentional? Stale `VolumeAttachment` deletion was needed to unblock recovery on 2026-05-05

### Phase 7 — Decision gate and close-out

- [ ] At T+14d post-Phase-1 (~2026-05-19) OR at next unexplained reboot, whichever comes first: re-evaluate. Choose terminal state (a) localized fix, (b) extended clean uptime, or (c) accept-and-mitigate
- [ ] If (c): author an ADR via the `adr` skill capturing the accept-and-mitigate decision, the residual-risk rationale, and the mitigations that are load-bearing (kernel sink, alerts, HA, runbooks). Link the ADR back here
- [ ] **Cross-close plan 0007.** Its Phase 5 teardown task was specifically the kernel sink that we just restored — that task is moot. Close 0007 as Done, citing this plan as the new home for the kernel-sink ownership, or as Abandoned if the framing no longer fits
- [ ] Invoke `planner close 0013 done "<closing note>"` (or `abandoned` if criterion (c) applies but no ADR was warranted)
- [ ] If a durable architectural decision emerged that's worth preserving (e.g. "permanent kernel-sink ownership", "external uptime probe is non-optional infrastructure", "1-replica is unacceptable for path X"), hand off to the `adr` skill

## Log

- 2026-05-05: Plan opened from plan 0009 abandonment after the 2026-05-05T19:33Z dual silent-reboot of k8s-1 + k8s-3 (k8s-2 held). The k8s-2-only framing 0009 was scoped against is falsified; this plan picks up under the cluster-wide / dual-node-capable hypothesis space. Hypothesis re-cut and discriminating-test backlog drawn from `context/notes/k8s-2-instability/evidence-2026-05-05-dual-silent-reboot.md` and the 12 prioritized action items in `context/postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`. Three of the postmortem's P0 items (AI-1 kernel sink restore, AI-2 Unknown-pod alert, AI-3 per-node reboot alert) are already committed (`35533bdb` + `40bb66a6`); their fire-test verifications are open Phase 1 tasks. Plan 0007 Phase 5 cross-close is tracked as a Phase 7 task here rather than re-opening 0007.

## References

- **Predecessor plan:** [`0009-k8s-2-k8s-3-silent-reboot-followup.md`](0009-k8s-2-k8s-3-silent-reboot-followup.md) — closed Abandoned 2026-05-05; contains the full pre-2026-05-05 investigation history, hypothesis evolution, and the salvage-vs-carry-over notes
- **Cross-open plan:** [`0007-k8s-2-remote-diagnostic-rollout.md`](0007-k8s-2-remote-diagnostic-rollout.md) — Phase 5 teardown moot post-restore; cross-close tracked in Phase 7 here
- **Postmortem:** [`../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md) — root-cause analysis, 12 action items, lessons learned
- **Incident:** [`../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md) — operational timeline, every recovery batch
- **Driving evidence note:** [`../notes/k8s-2-instability/evidence-2026-05-05-dual-silent-reboot.md`](../notes/k8s-2-instability/evidence-2026-05-05-dual-silent-reboot.md) — per-node BIOS/boot-ID matrix, forensic posture, hypothesis re-cut, discriminating-tests table
- **Investigation README:** [`../notes/k8s-2-instability/README.md`](../notes/k8s-2-instability/README.md) — needs update to reflect the new hypothesis ranking; that update is implicit Phase 2 housekeeping
- **ADRs:** 0017 (Multus storage-network — relevant to dual-node candidate 1b), 0021 (cilium memory limit → 3584Mi — relevant to dual-node candidate 1a), 0022 (cilium cleanState retraction)
- **Commits already landed against this plan's scope:**
  - `35533bdb feat(observability): restore Vector kernel sink (revert plan-0007 teardown)` — AI-1
  - `40bb66a6 feat(observability): alert on Unknown-phase pods + per-node reboot` — AI-2 + AI-3
  - `b758fd78 docs(incidents): 2026-05-05 k8s-1 + k8s-3 dual silent reboot`
- **Cluster checks:**
  - `talosctl get kmsglogconfigs` (per node) — Phase 1 verification
  - `kubectl -n observability exec talos-log-sink-vector-0 -c rotator -- ls -la /vector-data-dir/` — Phase 1 verification
  - `kubectl get prometheusrules -A | grep -E 'unknown|reboot'` — Phase 1 verification
  - `flux get hr -A` and `flux get ks -A` — standard Flux readout
