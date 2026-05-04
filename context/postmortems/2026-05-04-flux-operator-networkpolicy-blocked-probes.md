---
date: 2026-05-04
severity: low
component: flux-system / flux-operator
detected: 2026-05-04 ~19:30 UTC (visual review)
mitigated: 2026-05-04 20:10 UTC
resolved: 2026-05-04 20:13 UTC
duration-from-trigger: ~3d 14h (silent crashloop) + ~40 min (active remediation)
related-prs: [262]
related-commits: [24af3d58, 39a4f925]
---

# 2026-05-04 — flux-operator perma-CrashLoopBackOff post k8s 1.36 upgrade

> Chart-shipped NetworkPolicy left port 8081 (health probes) blocked. Kubelet probes started getting denied after Cilium / kubelet behavior changed in the Talos v1.13.0 / Kubernetes v1.36.0 upgrade, sending flux-operator into 1455 restarts over 3.5 days.

## Summary

The `flux-operator` Deployment crashlooped continuously from the **2026-05-01** Talos / Kubernetes upgrade until **2026-05-04 20:10 UTC**. Pod boot was healthy: leader lease acquired, FluxInstance reconciled in 3 s, controllers started. Then kubelet's `/healthz` probe on port 8081 silently failed and kubelet killed the container ~60 s into every cycle. The chart's `flux-operator-web` NetworkPolicy declared `policyTypes: [Ingress]` and listed allow rules for ports 8080 (metrics) and 9080 (web UI) only — port 8081 had **no allow rule**, so it was denied. Kubelet probes that had previously bypassed Cilium NP enforcement now got dropped at the CNI layer.

The fix was to disable the chart's NetworkPolicy via `web.networkPolicy.create: false` in the HelmRelease values. The flux-system namespace has no default-deny NP, so removal is safe; every other Flux controller has always run without one.

## Timeline (UTC)

| Time | Event |
|---|---|
| **2026-05-01** ~05:40 | Talos v1.13.0 / Kubernetes v1.36.0 rolling upgrade completed (commits `c5fb0d20`, `d60af8ab`). flux-operator and every other workload on k8s-1 restarted once. flux-operator failed to recover; all other Flux controllers came back clean. Restart count began climbing (~1 every 3.5 min). |
| **2026-04-29** | Renovate opened PR **#262** bumping flux-operator chart group `0.46.0 → 0.48.0`. Sat unmerged because `Flux Local Success` CI failure (pre-existing, unrelated `network/multus-upstream` path issue) flagged on every open PR. Not a blocker. |
| 2026-05-04 19:30 | User flagged "Unhealthy Workloads / Pods in Bad Waiting State / Restart Hotspots (1h)" dashboard alert showing `flux-operator-559cb46555-pxlmq` in CrashLoopBackOff with 1455 restarts. |
| 19:35–19:45 | Initial diagnosis. Pod logs showed clean startup → graceful SIGTERM at T+60s. Events showed `Liveness probe failed: ...8081/healthz: context deadline exceeded`. apiserver `/readyz` answered in 249 ms — apiserver-side fast. Other Flux controllers and other workloads on k8s-1 all healthy. **First hypothesis:** chart bumped recently broke something. |
| 19:50 | Bumped chart 0.46 → 0.48 by squash-merging PR #262 (commit `24af3d58`). Force reconcile. **First hypothesis falsified:** new pod (hash `7d976f6694`, image v0.48) crashlooped with the same signature within 2 min. |
| 19:55 | **Second hypothesis:** kubernetes default `timeoutSeconds: 1` too tight on k8s 1.36. Pushed override `timeoutSeconds: 5` for both probes (commit `8cd9707e`). |
| 20:03 | New pod (hash `699bcf4df4`) with 5 s timeout came up — same crashloop. **Second hypothesis falsified.** Direct curl from a same-namespace pod confirmed `/healthz` was network-unreachable (3 s connect timeout, no TCP handshake), not slow. |
| 20:08 | **Found it.** `kubectl -n flux-system get netpol` returned `flux-operator-web` allowing only ports 8080 + 9080. Port 8081 (health probes) had no allow rule. Pre-upgrade, kubelet probes apparently bypassed NP enforcement; post-upgrade Cilium enforces them. |
| 20:09 | Amended commit to disable chart NP via `web.networkPolicy.create: false` (commit `39a4f925`). Force-pushed. |
| 20:10:17 | Helm-controller stuck in 5 min upgrade → 5 min rollback retry cycles (each timing out waiting on the broken Deployment). Cut the loop by `kubectl delete networkpolicy flux-operator-web` directly. |
| **20:10:28** | Pod went `1/1 Ready`. Mitigation complete. |
| 20:13:51 | Helm-controller's next upgrade attempt picked up generation 5 (NP disabled), succeeded in 25 s. HR converged to `True` on chart 0.48.0 release v8. Resolution complete. |

## Root cause

Helm chart `flux-operator` v0.46/v0.48 ships a NetworkPolicy named `flux-operator-web` that selects the operator Deployment and applies `policyTypes: [Ingress]`. Once a NetworkPolicy with `policyTypes: [Ingress]` selects a pod, **all ingress traffic is denied except what's explicitly allowed**. The chart only allowed ingress to ports 8080 and 9080 — not the health probe port 8081 — so kubelet probes were silently dropped at the CNI layer.

Pre-upgrade, this misconfiguration was latent: kubelet's probe path either bypassed Cilium NP enforcement or the policy enforcement model worked differently. The Talos v1.13.0 / Kubernetes v1.36.0 upgrade changed kubelet → pod traffic to be subject to the same NP enforcement as pod → pod traffic. The misconfig became a hard failure.

The chart bug is upstream (controlplaneio-fluxcd/charts/flux-operator). Workaround is disabling the chart NP entirely.

## Detection

- **Detected by:** dashboard "Unhealthy Workloads / Pods in Bad Waiting State / Restart Hotspots (1h)" — visual review, no alert.
- **Time to detect:** ~3 d 14 h.
- **Why so slow:** No alert fires for `kube_pod_container_status_restarts_total > N`. PrometheusRule for restart hotspots exists per plan 0009 Phase 3 but only covers cilium-agent. Other Flux controllers were healthy, so flux-instance/cluster-apps reconciliation was unaffected and there was no GitOps stall to surface the issue.

## Resolution

Two-line fix in `kubernetes/apps/flux-system/flux-operator/app/helmrelease.yaml`:

```yaml
values:
  web:
    networkPolicy:
      create: false
```

Plus one operational shortcut to escape helm-controller's stuck retry/rollback cycles: `kubectl delete networkpolicy flux-operator-web`. Helm-controller's next upgrade attempt then re-deployed the chart with `create: false` and HR converged.

## False leads

We tried two fixes that didn't help, both of which look reasonable in isolation. Recording them so future-me doesn't repeat:

1. **Chart version regression.** Bumped `0.46.0 → 0.48.0` (PR #262). Made sense given the timing. Did not fix it because the NetworkPolicy template was unchanged across those versions.
2. **Probe `timeoutSeconds: 1` too tight on k8s 1.36.** Made sense given the symptom (`context deadline exceeded`). Did not fix it because the deadline was on the TCP connect, not on the HTTP handler — packets were never arriving.

The decisive test that should have come earlier: **probe `/healthz` from another pod**, separately from kubelet's view. Result was `5 s connect timeout` from a pod on a different node. That instantly distinguishes "slow handler" (would return quickly with a 503 or bad data) from "network blocked" (no TCP handshake at all).

## Why this didn't fail before the upgrade

The chart NP has been deployed 23 days without issue. Either:

- **(most likely)** Cilium's enforcement of NP against kubelet-source traffic changed semantics in the Cilium version that came with the k8s 1.36 stack. The recent Cilium upgrades (ADR 0021/0022 raised cilium-agent memory limit) coincide with this period.
- **(less likely)** Kubernetes 1.36 changed kubelet's probe source IP or socket behavior in a way that started matching the NP's deny path.

Either way, this was a latent misconfig that became visible after the upgrade.

## Prevention

### Detection improvements (high value, low cost)

- [ ] **Cluster-wide PrometheusRule for restart hotspots.** Plan 0009's `prometheusrule-cni-plumbing.yaml` covers CNI components only. Add a cluster-wide rule:
  - `CrashLoopBackOffHigh`: `rate(kube_pod_container_status_restarts_total[15m]) > 0.05` for 15 m → warning. Catches >3 restarts in 15 min on any container.
  - `CrashLoopBackOffCritical`: same metric > 0.1 for 30 m → critical. Catches sustained loops.
  - This single rule would have alerted within an hour of the Talos upgrade instead of 3.5 days later.
- [ ] **Dashboard panel: pods with `restartCount > 100` cluster-wide.** A Grafana panel on the cluster-health dashboard surfacing the long-tail. flux-operator at 1455 would have been impossible to miss in any dashboard glance.

### Process improvements (medium value, medium cost)

- [ ] **Chart NetworkPolicy audit at app-intake time.** When `cluster-intake-gatekeeper` accepts a new app, and `flux-app-author` scaffolds the HelmRelease, check whether the chart templates a NetworkPolicy and verify it allows ingress to **every container port**, especially probe ports. Easy check: `helm template <chart> | yq 'select(.kind == "NetworkPolicy") | .spec.ingress[].ports[].port'` against the Deployment's `spec.containers[*].ports` ∪ probes.
- [ ] **Talos / Kubernetes upgrade pre-flight: probe-reachability sweep.** Before a minor k8s upgrade, run a one-off sweep: for every pod selected by an in-namespace NetworkPolicy, curl its liveness/readiness probe URL from a test pod. Any unreachable probe is a latent NP misconfig that the upgrade may surface.

### Architectural choices (low value, low cost)

- [ ] **Default to disabling chart NetworkPolicies in this repo.** Anton has no namespace-default-deny policy and no internal threat model that the chart NPs are designed for (they assume zero-trust workload isolation). Anton's chart NPs have always been redundant with Cilium's default-allow stance. Disable by default at HR-author time; opt-in only when there's a real isolation requirement.

## Action items

1. **Author cluster-wide CrashLoopBackOff PrometheusRule.** Highest-leverage prevention. Should land in `kubernetes/apps/observability/kube-prometheus-stack/app/` next to the existing `prometheusrule-*` files.
2. **Audit other Helm charts in this repo for the same chart-NP misconfig pattern.** Survey: `helm template` each HR and `yq` for `kind: NetworkPolicy`; cross-check ingress ports against pod ports. Three NPs currently exist in the cluster (`csgoplant-default-deny`, `csgoplant-dragonfly`, `harbor-redis`); none are chart-managed so are out of scope. Future risk is in charts not yet adopted.
3. **Update `anton-repo-conventions` skill** with a "Chart NetworkPolicies are disabled by default; document explicitly when enabled" rule and the audit recipe.
4. **File an upstream issue / PR on `controlplaneio-fluxcd/charts/flux-operator`** to add port 8081 to the `web` NetworkPolicy ingress rules. Future operators on locked-down clusters will hit this same wall.

## Should this become an ADR?

**Yes — narrow scope, durable rule.** The forward-looking decision worth preserving is *"Chart-shipped NetworkPolicies are disabled by default in this repo; opt-in only when there's a documented isolation requirement, and any opt-in must be audited for kubelet-probe path completeness."* That's a recurring rule that affects every future app-intake decision and every k8s minor upgrade. It belongs in `context/adrs/` so `cluster-intake-gatekeeper` can cite it and `flux-app-author` can default to it.

ADR title (suggestion): **"Disable chart-shipped NetworkPolicies by default; explicit opt-in with kubelet-probe audit."** `affects: networking`. References this postmortem.

Out of scope for the ADR: the specific flux-operator chart bug (that's an upstream issue, not an architectural decision); the post-upgrade Cilium NP enforcement change (a cluster fact, not a decision).
