---
status: Published
incident: ../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md
opened: 2026-05-05T20:36Z
closed: 2026-05-05T21:00Z
related-plans: [0007, 0009]
related-adrs: []
severity: SEV-2
duration-public-impact: ~62 min (2026-05-05T19:33Z event → 2026-05-05T20:35Z `<public-site-A>` 200; first site `<public-site-B>` recovered at ~20:02Z, ~29 min)
---

# Postmortem — 2026-05-05 k8s-1 + k8s-3 sequential silent reboot

> Two of three Talos control-plane nodes silent-rebooted **sequentially, ~26 min apart** (originally framed as "simultaneous within ~28 s" — this was wrong, see Correction below) while the third (the historically-fragile node under active investigation) held cleanly. The reboot itself was small; the disproportionate public impact came from a 4-day-old latent ghost-pod accumulation that the reboot exposed.

## ⚠ Correction — 2026-05-05 evening

The original Summary and Timeline below claimed a **simultaneous within ~28 s** dual reboot at 19:33:54Z (k8s-3) → 19:34:22Z (k8s-1). Verification on the live cluster (`/proc/uptime` via privileged exec into the cilium-agent on each node, plus `Node.Ready.lastTransitionTime` from the API) shows the k8s-3 timestamp was wrong by ~26 minutes:

| Node | Original claim | Verified | Source |
|---|---|---|---|
| k8s-3 | 19:33:54Z | **19:07:13Z** | live `/proc/uptime`, boot ID `e55639d4…` |
| k8s-1 (silent) | 19:34:22Z | ~19:33Z (unverifiable; overwritten by 20:29Z reboot) | original estimate retained |
| k8s-1 (graceful) | 20:29Z | **20:29:07Z** | live `/proc/uptime`, boot ID `65fc58fd…` |
| k8s-2 | did not reboot | did not reboot | `/proc/uptime` confirms boot 2026-05-04T01:47:06Z |

The actual pattern is **sequential cascade with a ~26 min gap, k8s-3 first, k8s-1 second**. This materially changes the analysis: a "simultaneous external trigger" hypothesis (e.g., shared power, single DAC failure, single cluster-wide stimulus) does not fit sequential failures separated by 26 minutes. A **cascade** hypothesis (k8s-3 failure stresses something that takes 26 min to propagate to k8s-1) fits better.

**The Root Cause and Lessons sections below were written under the simultaneity framing and have not been re-derived.** Conclusions in those sections that lean on the simultaneity claim need re-examination. See `../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md` Correction section for the verified timeline.

## Summary

At 2026-05-05T19:07:13Z, k8s-3 unexpectedly rebooted (verified via `/proc/uptime`). Roughly 26 minutes later at ~19:33Z, k8s-1 also unexpectedly rebooted. k8s-2, the node we had been watching for the past 41 h after a BIOS flash on 2026-05-04, did not reboot. Both rebooted nodes returned to `Ready` cleanly at the Talos / Kubernetes layer within ~50 min of their respective events.

The rebooted-node API records contained a large set of pods stuck in `Unknown` phase (~50 pods, ages ranging 42 h to 4 d 15 h). These pods had stopped reporting to the API but their containers had continued serving traffic on containerd. When containerd reset during the reboots, the workloads disappeared while the Kubernetes ReplicaSets / StatefulSets / DaemonSets continued to count them as existing replicas. Public ingress (cloudflare-tunnel, envoy-external, envoy-gateway) and the Tailscale operator API proxy were among the affected pods; both critical paths went down.

Recovery required ~62 min of operator action: force-deleting the ghost pods in five batches, generating a direct kubeconfig to bypass the unreachable Tailscale-operator proxy, cordoning k8s-1 to escape a kubelet wedge, and a second graceful reboot of k8s-1 to clear stale containerd sandbox-name reservations. Both public sites returned 200 by T+62 min.

The trigger event — the simultaneous silent reboot — produced no kernel-side trace because the Vector kernel sink had been torn down ~30 h earlier as part of a planned tidy-up after the BIOS flash. The plan-0009 BIOS-fix hypothesis is materially weakened by this event: k8s-1 silent-rebooted for the first time in 190 days while still on the un-flashed BIOS version, and k8s-2 (the historically-fragile node) was the one that held.

## Impact

- **`<public-site-A>`** unreachable from ~19:33Z (data plane container died with the reboot) until ~20:13Z (~40 min); served 503 from ~20:02Z onward as ingress recovered ahead of backend
- **`<public-site-B>`** unreachable from ~19:33Z until ~20:02Z (~29 min); back to 200 with the first ghost-pod batch
- **Other public-facing HTTPRoutes** sharing the same `cloudflare-tunnel` — same window
- **Remote `kubectl` via Tailscale-operator proxy** unreachable for the entire incident window until ~20:01Z; operator used direct kubeconfig as workaround
- **Cluster control plane** never lost quorum — etcd 3/3 healthy throughout, k8s-2 leader at term 32 with all members at synchronized applied index
- **Storage data plane** degraded but not lost: SeaweedFS continued to serve from the surviving replica on k8s-2; one volume (`seaweedfs-volume-1`) was still recovering at the close of the incident due to a stale Longhorn `VolumeAttachment` from the wedge period
- **No data loss observed**

Severity: SEV-2 during public-site impact (~62 min); downgraded to SEV-3 at 20:13Z when public impact ended; closed at 20:36Z.

## Detection

The bastion-side `loop` cron job running the BIOS-flash watch (`1762a4f1`, 30-min cadence) caught the boot-ID baseline diff at its next tick after the event:
- detection: **T+~21 min** (event 19:33Z, detected 19:54Z)
- signal: 2/3 baseline boot IDs changed; k8s-2 unchanged
- behavior: loop output `ESCALATE`, ran `CronDelete`, sent `PushNotification`, appended a paragraph to plan 0009 Log

The push notification was suppressed by terminal focus (operator was actively in-session). The operator instead noticed the public sites were unreachable while the loop was reporting the boot-ID diff.

The standard in-cluster reboot alert is `K8s2UnexpectedReboot` — by name and label, k8s-2-specific. There is no matching alert for k8s-1 or k8s-3, so the cluster's own alerting stack would not have caught this event.

## Root cause

Two distinct failures stacked, with the second producing the public impact:

### 1. The trigger — simultaneous silent reboot of k8s-1 and k8s-3 (root cause **unknown**)

No kernel trace was captured. The Vector kernel sink that was set up specifically for this purpose had been torn down at 2026-05-04T~02:00Z (commit `4037deec`, plan 0007 Phase 5 file-side teardown), about 30 hours before the event. The trade-off was explicit at the time and is documented in plan 0009 Log entry "T+14h checkpoint — Vector sink torn down": *"if a silent reboot fires before the 2026-05-07T12:00Z watch ends, we lose the kernel-trace channel and fall back to Prometheus reboot detection + ring-buffer post-mortem on the next-up node — same forensic posture as before plan 0009 Phase 1 was applied. Acceptable trade given current >14 h clean uptime on k8s-2 and >14 h on k8s-3."*

That trade came due ~30 h later.

What we *can* say from the data we have:
- **k8s-1 had never silent-rebooted in 190 days of cluster age** — this is its first event
- **k8s-1 is on BIOS 1.26**, untouched by the 2026-05-04 flash; **k8s-3 is on BIOS 1.27** (post-flash); **k8s-2 is also on BIOS 1.27** (post-flash)
- The two rebooted nodes span both BIOS versions; the held node shares a BIOS version with one of the rebooted nodes — **BIOS version is not predictive of susceptibility**
- The reboots were within **~28 s** of each other — close enough to suggest a shared trigger rather than two independent random events
- k8s-2 (the historical reboot leader) **held cleanly** — the inverse of every prior silent-reboot incident in plan 0007 / 0009 / 0010

The plan 0009 hypothesis ranking ("single-unit k8s-2 hardware defect" at #1) is materially falsified by this event. New leading candidates given the 2026-05-05 signature:
1. **Cluster-wide kernel/network trigger** that affects ≥2 nodes when load distribution / pod-churn aligns
2. **Power or electrical event** affecting two of three Mini-PC chassis but not the third (PSU group, UPS topology, breaker?)
3. **Concurrent failure propagating via the data plane** (e.g., a Cilium / BPF event that took k8s-1 + k8s-3 kernels down while k8s-2 absorbed it)

The original plan-0009 evidence stack (microcode 0x12B, BIOS 1.22 differential, Mushkin DDR5 SKU, single-unit chassis defect) does not predict today's signature.

### 2. The amplifier — 4-day-old ghost-pod accumulation on k8s-1 (root cause **identified**)

At the moment k8s-1 rebooted, ~50 pods were in `Unknown` phase across more than a dozen namespaces — including `cloudflare-tunnel` (4 d 15 h), `envoy-external` × 2 (4 d 2 h and 42 h), `envoy-gateway` (42 h), `tailscale/operator` (4 d 15 h), and StatefulSet pods for SeaweedFS, Harbor Postgres / Redis, csgoplant.

`Unknown` is the phase the kubelet → API reporting goes into when the kubelet's status updates stop reaching the API server but the kubelet has not been confirmed dead. Kubernetes' replica controllers count `Unknown` pods as "exists, will be back" and **do not create replacements**. Meanwhile, the actual containers continue running on containerd, serving traffic.

This means the cluster had been operating with a **latent failure** for at least 4 days. Each affected Deployment showed `0/N` available in `kubectl get deploy` output, but the actual workload was being served by containers that the API didn't know were running. The system had silently lost the ability to recover from a kubelet/containerd reset on k8s-1.

When k8s-1 rebooted at 19:34Z, containerd reset, the actual containers died, and Kubernetes still did not create replacements because the API records were `Unknown`, not `Failed`. Every Deployment / StatefulSet whose only running replica was a ghost on k8s-1 went to zero ready.

The recovery procedure for this state — `kubectl delete pod ... --force --grace-period=0` to clear the API records and let ReplicaSets re-create the pods — is documented in plan 0007 day-1 Log (2026-04-20) from the same pattern. Pattern recognition was fast; the recovery sequence was the bottleneck (one batch per logical group, each with a settle-and-verify gate).

### 3. The recovery friction — k8s-1 kubelet/containerd wedge after force-deletes

After batches 1 and 2, several pods that the scheduler placed on k8s-1 sat in `Init:0/1` / `ContainerCreating` for minutes with no kubelet events after `Scheduled`. Cluster events showed `FailedKillPod` errors with `KillPodSandboxError: rpc error: code = DeadlineExceeded` on the deleted ghost pods. The kubelet was looping on `KillPodSandbox` calls to its own containerd that were hanging.

This matches the plan 0007 day-1 finding: containerd state can become wedged in a way that Talos' `service` view doesn't see (`STATE=Running HEALTH=OK`) but kubelet RPCs time out. The fix is a fresh reboot of the affected node. Recovery batches 3-5 cordoned k8s-1, rescheduled what could move to k8s-2 / k8s-3, then graceful-rebooted k8s-1 (boot ID `3d007d1c…` → `65fc58fd…`), uncordoned, and force-replaced the residual `Error` / `Completed` pods.

## Contributing factors

- **Forensic-channel teardown was premature.** The plan-0009 T+14h Vector-sink teardown was explicitly justified as an acceptable trade. The trade came due in <2 days. The first event after teardown is the one with no kernel trace.
- **No alert on `Unknown` phase pods.** Existing PrometheusRules cover Cilium memory, kube-apiserver, CNI plumbing, and node memory. Nothing fires for "this pod has been Unknown for 10 minutes." Ghost pods accumulated for 4 days unnoticed.
- **No reboot alert for k8s-1 or k8s-3.** `K8s2UnexpectedReboot` is k8s-2-keyed. The cluster's own alerting was structurally blind to the event we just experienced. Detection came from a bastion-side cron loop running for an unrelated reason (BIOS-flash watch) — i.e., a coincidence.
- **Tailscale-operator API proxy was a SPOF.** The operator pod was itself a ghost on k8s-1; tunneled `kubectl` was unreachable for the entire incident window until batch 1 cleared the ghost. The direct-kubeconfig workaround used was ad-hoc (generate from talosctl, sed-edit the server URL, `--insecure-skip-tls-verify` due to cert SAN mismatch) and is not in any runbook.
- **Single-replica critical-path deployments.** `cloudflare-tunnel`, `envoy-gateway`, and `tailscale/operator` all run with `replicas: 1`. Even a graceful single-node failure would take them down momentarily.
- **`envoy-external` anti-affinity was effectively defeated by ghost pods.** The Deployment had `replicas: 2` but both running pods were on k8s-1 because the prior pods (now Unknown ghosts) on other nodes had earlier been moved by previous churn. Anti-affinity is satisfied by Unknown-phase pods, which means a single-node failure can still take all replicas down.
- **Operator was remote.** Physical-access mitigations (BMC, console, hard reboot) were unavailable. Recovery had to happen via talosctl / kubectl over Tailscale + SSH.
- **PushNotification was suppressed by terminal focus.** The system did the right thing — the operator was watching the session — but it means the notification path is unreliable for "you should pay attention to this loop output" cases.

## Timeline (UTC)

| Time | Event |
|---|---|
| 2026-05-04T01:46Z | k8s-2 second post-flash boot (anchor for the BIOS-flash watch baseline that ran for the next 41 h) |
| 2026-05-04T15:30Z | T+14h checkpoint — Vector kernel sink torn down (commit `4037deec`); explicit trade-off note |
| ~~2026-05-05T19:33:54Z~~ → **2026-05-05T19:07:13Z** | **k8s-3 boots** (corrected from live `/proc/uptime`; original recovery-time dmesg estimate was wrong by ~26 min) |
| 2026-05-05T19:33Z (approx) | **k8s-1 silent-rebooted** (~26 min after k8s-3, **not** ~28 s; original 19:34:22Z claim was the recovery-time dmesg estimate and is approximately when k8s-1 finished its silent-reboot boot) |
| 2026-05-05T19:54Z | Bastion watch loop fires its 30-min tick, catches boot-ID diff, escalates and stops; appends paragraph to plan 0009 Log |
| 2026-05-05T19:54-20:00Z | Operator triages: kubectl-via-Tailscale times out, generates direct kubeconfig, confirms etcd 3/3 healthy, identifies ghost-pod recovery deadlock |
| 2026-05-05T20:01Z | Recovery **batch 1** — force-delete ingress + Tailscale-operator ghosts |
| 2026-05-05T20:02Z | `<public-site-B>` returns 200 (~29 min after event) |
| 2026-05-05T20:05Z | Recovery **batch 2** — bulk force-delete of all remaining `Unknown` ghosts (~50 pods) |
| 2026-05-05T20:09Z | Recovery **batch 3** — cordon k8s-1, force-delete pods stuck on k8s-1 to reschedule onto k8s-2 / k8s-3 |
| 2026-05-05T20:13Z | `<public-site-A>` returns 200 |
| 2026-05-05T20:29Z | Recovery **batch 4** — graceful reboot of k8s-1 via `talosctl reboot --mode=default` (etcd 3/3 confirmed); new boot ID `65fc58fd…` |
| 2026-05-05T20:30Z | Recovery **batch 5** — uncordon k8s-1, force-replace stale `Error` / `Completed` pods so DaemonSets / ReplicaSets create fresh ones |
| 2026-05-05T20:35Z | Steady-state confirmed: 3 nodes Ready, etcd 3/3 healthy, both public sites 200, only `seaweedfs-volume-1` still in stale-VA recovery |
| 2026-05-05T20:36Z | Stale Longhorn `VolumeAttachment` deleted to unblock `seaweedfs-volume-1` |
| 2026-05-05T~21:00Z | Postmortem published |

## What went well

1. **Bastion-side watch loop fired exactly as designed.** The 30-min cron loop running the BIOS-flash watch caught the event at its very next tick. Without that loop, detection would have come from the operator manually noticing public sites were down — substantially later.
2. **Etcd quorum held throughout.** Term 32, applied index synchronized across all 3 members, no leader election triggered. The cluster control plane remained writable for the entire incident.
3. **Pattern recognition was fast.** The ghost-pod recovery deadlock matched plan 0007 day-1 within seconds of seeing the pod listing. The recovery procedure was already documented; the operator did not have to invent it.
4. **Direct-kubeconfig workaround.** When the Tailscale-operator path was blocked, generating an admin kubeconfig from `talosctl` and editing the server URL to a Tailscale IP got remote `kubectl` working in <2 min.
5. **Cordon-and-evict containment.** Cordoning k8s-1 once the kubelet wedge was identified prevented further pods from getting trapped there, and let the StatefulSets escape to k8s-2 / k8s-3 cleanly.
6. **Real-time incident-file authoring.** Each recovery batch was captured as it happened; no information was lost to "I'll write it up later." The incident file became the source of truth for this postmortem.
7. **Public sites recovered before the deeper cluster issues were resolved.** Cloudflare-tunnel + envoy were the very first batch; users saw `<public-site-B>` come back within minutes of the first action, and both sites were back well before storage / Harbor / observability had finished settling.
8. **Two graceful reboots without loss.** Both the original silent reboot and the controlled batch-4 reboot of k8s-1 produced clean post-boot states with intact etcd participation.

## What went badly

1. **The forensic surface was gone when we needed it.** Vector kernel sink was torn down 30 h before the event. The plan-0009 trade-off was explicit but turned out to be premature. The first event after teardown is the one with no kernel trace.
2. **A 4-day-old latent failure went undetected.** ~50 pods had been in `Unknown` phase for days. The cluster looked healthy from `kubectl get nodes` and most monitoring views, but key Deployments were silently single-pointed on stale containerd state.
3. **Cluster's own alerting was blind to the event.** No `K8s1UnexpectedReboot` or `K8s3UnexpectedReboot` rule. No `KubeletStoppedReporting` / `PodPhaseUnknown` rule. Detection came from an external bastion loop running for unrelated reasons.
4. **Tailscale-operator was a single point of failure.** When the operator pod went down (as a ghost), remote `kubectl` was simply unavailable. The fallback (direct kubeconfig from `talosctl`) is not documented in any runbook.
5. **Single-replica critical-path deployments.** Cloudflare-tunnel, envoy-gateway, Tailscale operator — all 1-replica. A single node going down takes them down even without the ghost-pod amplifier.
6. **Anti-affinity assumption defeated by ghost pods.** `envoy-external`'s 2-replica anti-affinity didn't protect us because both running pods ended up on k8s-1 with their previous-node replicas as Unknown ghosts.
7. **k8s-1 needed a second reboot.** The first (silent) reboot left containerd in a state the kubelet couldn't drain. Plan 0007 day-1 history said this was possible, but we did not anticipate it during recovery and lost ~20 min on it.
8. **The push notification was suppressed.** The operator was actively in-session so the notification stayed silent. If the operator had been away from the terminal but with the session open, this would have been a worse outcome.
9. **Plan 0009's narrative is materially weakened.** The dual-node simultaneous reboot with k8s-1 (un-flashed BIOS, never-rebooted-before) and k8s-2 (post-flash, historically fragile) holding is not predicted by any of the plan's existing top-3 hypotheses. We may have spent significant effort on a fix that addresses at most a subset of the actual mechanism.

## Action items

| # | Action | Owner | Severity | Tracking |
|---|---|---|---|---|
| AI-1 | Re-stand up Vector kernel sink (or equivalent kernel-side trace channel) before the next plan-0009 watch tick | operator | P0 | revives plan 0009 Phase 1 — see related-plans |
| AI-2 | Add PrometheusRule on `kube_pod_status_phase{phase="Unknown"} > 0 for 10m` (warning) and `> 0 for 1h` (critical) cluster-wide | operator | P0 | new rule file |
| AI-3 | Generalize `K8s2UnexpectedReboot` rule into a `NodeUnexpectedReboot` family (`changes(node_boot_time_seconds[6h]) > 0` per-node, with `instance` label preserved) | operator | P0 | edit `prometheusrule-cilium-memory.yaml` siblings |
| AI-4 | Bump critical-path single-replica Deployments to ≥2 with topology-spread / anti-affinity: `network/cloudflare-tunnel`, `network/envoy-gateway`, `tailscale/operator` (verify operator chart supports HA before bumping) | operator | P1 | `kubernetes/apps/network/...` + `kubernetes/apps/tailscale/...` |
| AI-5 | Document the direct-kubeconfig fallback (talosctl kubeconfig + sed to Tailscale IP + `--insecure-skip-tls-verify`) in `anton-remote-access` skill / runbook | operator | P1 | `.claude/skills/anton-remote-access/` |
| AI-6 | Reopen plan 0009 with revised hypothesis ranking; author evidence note `evidence-2026-05-05-dual-silent-reboot.md` summarizing this event's signature | operator | P1 | plans + notes/k8s-2-instability/ |
| AI-7 | Investigate ghost-pod accumulation root cause: why did the kubelet on k8s-1 stop reporting on those specific pods 4 d 15 h ago? Was there a prior partial event we missed? | operator | P2 | journal / dmesg from k8s-1 ring buffer (post-reboot — gone, but timeline correlates against Talos service events) |
| AI-8 | Add a quarterly chaos-engineering drill: rotate one node's pods (cordon + drain) and verify all critical paths remain serving. Would have surfaced this latent failure days earlier | operator | P2 | new task / doc |
| AI-9 | Revisit `envoy-external` topology-spread to ensure anti-affinity is enforced even when peer pods are in `Unknown` phase (likely needs `whenUnsatisfiable: DoNotSchedule` + label exclusion of Unknown-phase pods, may not be expressible — investigate) | operator | P2 | `kubernetes/apps/network/envoy-gateway/` |
| AI-10 | Add an external uptime probe (Cloudflare Workers, GitHub Action, or similar) for `<public-site-A>` and `<public-site-B>` so the platform learns about user-facing outages independently of cluster health | operator | P2 | new repo or existing CI |
| AI-11 | Document the post-reboot ghost-pod recovery procedure as a runbook (`unwedge-after-node-reboot.md`) with the batched force-delete sequence, since this is the second time it has been needed (plan 0007 day-1 + this incident) | operator | P3 | `docs/` or skill |
| AI-12 | Investigate `seaweedfs-volume-1` PVC pinning to k8s-1 — should this volume be free to attach anywhere, or is the pin intentional? Stale `VolumeAttachment` deletion was needed to unblock recovery | operator | P3 | follow-up or absorbed into AI-7 |

## Lessons learned

1. **`Unknown` phase pods are a leading indicator, not steady state.** They mean kubelet→API reporting has degraded for those specific containers. Allowing them to persist for days is allowing a latent failure to accumulate. Treat them like CrashLoopBackOff: alert on duration, investigate, repair.
2. **Reboot exposes latent state.** What looks stable for days can be a façade if the API and reality have diverged. A periodic "rotate one node's workloads" drill would surface this kind of accumulation early, when there's no urgency.
3. **Forensic surfaces should not be torn down before the incident window closes.** The plan-0009 T+14h teardown was justified on tidiness grounds with an explicit trade-off; the trade came due in <2 days. Future similar plans should keep the trace channel alive through the *entire* watch window, with teardown as part of close-out, not mid-watch tidy-up.
4. **Remote-access has a hard dependency loop.** When the Tailscale operator pod goes down, the standard kubectl path is gone. The direct-kubeconfig fallback works but should be a documented runbook step, not an ad-hoc improvisation under pressure.
5. **Single-replica matters.** Anywhere we have a 1-replica Deployment on the critical user-facing path, a single node failure is a user-visible outage. Even with 3-node redundancy at the Kubernetes layer, application-layer redundancy is what protects users.
6. **Anti-affinity is satisfied by ghost pods.** This is a Kubernetes correctness gap (or at least a non-obvious behavior). `topologySpreadConstraints` with `whenUnsatisfiable: DoNotSchedule` plus careful label-exclusion may help; needs investigation.
7. **The plan-0009 BIOS-fix narrative does not survive 2026-05-05 cleanly.** k8s-1 silent-rebooted for the first time in 190 days while still on un-flashed BIOS 1.26, and the historically-fragile k8s-2 (now on BIOS 1.27) held. Either BIOS is partially-mitigating but not eliminating the root cause, or BIOS was never the determining variable. The plan's hypothesis ranking needs a full re-cut.
8. **Bastion-side watch loops earn their keep.** A 30-min cron running off-cluster caught an event the in-cluster alerting stack was structurally blind to. The pattern is worth generalizing — a small set of "is the cluster alive in the way I expect" probes running outside the cluster catches failure modes the cluster cannot self-detect.
9. **Pattern libraries pay off.** Plan 0007 day-1 Log was directly applicable; recognition of the ghost-pod recovery deadlock took seconds, not hours. Continuing to write up incident-style entries in plans (rather than only in postmortems) compounds the operator's pattern library.

## References

- Incident: [`../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md) — full operational timeline including each `kubectl` invocation
- Plan 0007 (k8s-2 remote diagnostic rollout): [`../plans/0007-k8s-2-remote-diagnostic-rollout.md`](../plans/0007-k8s-2-remote-diagnostic-rollout.md) — original ghost-pod recovery deadlock pattern (day-1 Log, 2026-04-20)
- Plan 0009 (k8s-2 silent-reboot follow-up): [`../plans/0009-k8s-2-k8s-3-silent-reboot-followup.md`](../plans/0009-k8s-2-k8s-3-silent-reboot-followup.md) — BIOS-flash watch and the T+14h Vector-sink teardown trade-off
- Vector kernel sink teardown commit: `4037deec`
- BIOS-flash evidence (k8s-2 + k8s-3): [`../notes/k8s-2-instability/evidence-2026-05-04-bios-1.27-flash.md`](../notes/k8s-2-instability/evidence-2026-05-04-bios-1.27-flash.md)
