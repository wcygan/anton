---
status: Accepted
date: 2026-05-04
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0025 — Chart-shipped NetworkPolicies are disabled by default; opt-in only with kubelet-probe audit

> Anton's HelmRelease values disable chart-managed NetworkPolicies by default. Re-enabling one is allowed but must be audited: the policy must allow ingress from the kubelet probe path to every container port that any liveness, readiness, or startup probe targets — otherwise the next Cilium / kubelet upgrade silently turns the workload into a CrashLoopBackOff.

## Status

Accepted

## Context

On **2026-05-01**, the Talos v1.13.0 / Kubernetes v1.36.0 rolling upgrade landed (commits `c5fb0d20`, `d60af8ab`). Every node rebooted once. All workloads on k8s-1 restarted; all but one recovered cleanly. `flux-operator` entered a perma-CrashLoopBackOff and stayed there for ~3 days 14 hours before the dashboard alert surfaced it on **2026-05-04**.

The chart `controlplaneio-fluxcd/charts/flux-operator` (versions 0.46.0 and 0.48.0) ships a NetworkPolicy named `flux-operator-web` that selects the operator Deployment with `policyTypes: [Ingress]`. The allow rules cover ingress to ports 8080 (metrics) and 9080 (web UI). Port **8081 (controller-runtime health probes)** has no allow rule. Once a NetworkPolicy with `policyTypes: [Ingress]` selects a pod, all ingress is denied except what's explicitly allowed — so kubelet's probes to `/healthz` on port 8081 were dropped at the CNI layer.

The misconfig was latent for 23 days. Pre-upgrade, kubelet's probe traffic against this cluster's Cilium build evidently bypassed NP enforcement (or matched a path that Cilium did not enforce). Post-upgrade it didn't — most likely because the Cilium version that came with the k8s 1.36 stack changed the enforcement surface for kubelet → pod traffic. The exact upstream change is not pinned down; what matters is the **rule that protects against the next such change**, regardless of whether it lands in Cilium, kubelet, or the kube-proxy replacement layer.

The fix was two lines in the HelmRelease values: `web.networkPolicy.create: false`. Anton's `flux-system` namespace has no default-deny policy, no Cilium cluster-wide policy, and no internal threat model that the chart NPs are designed for. The chart NP was strictly redundant — and broken — from day one.

A survey of the cluster at fix time showed three other NetworkPolicies (`csgoplant/csgoplant-default-deny`, `csgoplant/csgoplant-dragonfly`, `registries/harbor-redis`). All three are intentionally hand-authored and none restrict probe ports — so no other workload was at latent risk on 2026-05-04. The risk is forward-looking: every future chart adoption may ship its own NetworkPolicy.

Full incident detail and root-cause analysis: [`context/postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md`](../postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md).

## Decision

For every Anton HelmRelease, **chart-managed NetworkPolicies are disabled by default**. When a chart exposes a values switch (commonly `<component>.networkPolicy.create`, `networkPolicy.enabled`, `policies.networkPolicy.enabled`, or similar), set it to `false` at HR-author time.

If a specific app *needs* its chart's NetworkPolicy (real isolation requirement, documented threat model, or a chart that wires NP into its own RBAC enforcement path), enabling it requires:

1. **Inline comment in the HelmRelease values** explaining *why* the NP is on for this app, and what gets isolated from what.
2. **Explicit kubelet-probe audit**: render the chart with `helm template` and verify that the NP's ingress rules cover **every container port that any `livenessProbe`, `readinessProbe`, or `startupProbe` targets**, across every container in the chart's Deployments / StatefulSets / DaemonSets. The audit recipe is in the `anton-repo-conventions` skill (see Follow-ups below).
3. **A note in the HR-adjacent comment** of which Cilium / kubelet versions the audit was performed against, so the next k8s minor upgrade can re-audit if enforcement semantics change.

The default-disable rule applies even to charts whose NPs *currently* allow probe ports. Future chart upgrades may regress; defaulting to off removes the risk entirely. Charts that want to claim "secure by default" can demonstrate it without forcing every adopter to audit a YAML doc they didn't write.

`flux-app-author` will scaffold new HRs with the disable switch (or a TODO comment naming the values key, when the key isn't a stable name across charts). `cluster-intake-gatekeeper` will name this ADR in any verdict that adopts a chart known to ship an NP.

## Alternatives considered

- **Status quo (chart NPs left on, audited case-by-case post-deploy).** Rejected — that is the policy that produced the 2026-05-04 incident. The audit step was never performed because the chart NP was invisible at HR-author time (not in the values, not in the manifest, only in the rendered output). Three days of CrashLoopBackOff is more than enough evidence that "we'll catch it in monitoring" doesn't actually catch it.
- **Adopt a default-deny NetworkPolicy in every namespace and require explicit allow lists.** Out of scope. Anton has no internal threat model that justifies the operational tax. This is not a multi-tenant cluster, every namespace is operator-managed, and the cost of getting per-app allow lists right (especially for Flux controllers' watch-traffic patterns) is much higher than the cost of accepting a homelab-grade trust model. Defer until anton ever runs untrusted workloads.
- **Audit chart NPs at intake time and accept the ones that look correct, leaving them on.** Rejected as the primary policy because it doesn't survive chart upgrades. A chart that ships a correct NP at adoption time can ship a regression in any future minor version, and Renovate auto-merges (or the operator merges) without re-auditing the templated NP. Default-disable removes the dependency on continued vigilance.
- **Author a CiliumClusterwideNetworkPolicy that explicitly allows kubelet → pod probe traffic on common probe ports cluster-wide.** Tempting (it would have prevented the incident regardless of chart NPs) but rejected because (a) "common probe ports" is unbounded — controller-runtime defaults to 8081, but charts pick anything from 1024 upward; (b) it adds a perpetual cluster-wide rule that future-me has to keep correct against future kubelet probe-source changes; (c) it doesn't address the broader principle that chart NPs in this homelab are dead weight. Default-disabling the chart NPs is simpler and dominates this alternative for anton.

## Consequences

### Accepted costs

- HR-author time grows by the few minutes needed to find each chart's NP-disable values key. The names are inconsistent (`networkPolicy.create`, `networkPolicy.enabled`, `web.networkPolicy.create`, `policies.enabled`, …) so the right move is "search the values for `networkPolicy` or `netpol` and set every relevant key false."
- Charts that wire NetworkPolicy into their own deployment-time correctness checks may complain. None observed in the current Anton stack; revisit if a chart fails to install with NP disabled.
- Forfeits the upstream chart maintainer's threat model. Acceptable: that threat model is for multi-tenant production clusters, not a single-operator homelab.

### Renovate-PR tax

None — no new component. The audit obligation only kicks in if a chart bump introduces a *new* NetworkPolicy that wasn't there before, or a *new* probe port that the existing NP would block. Both are rare and visible in the chart values diff.

### Restore-runbook obligation

None additional — disabling a chart NP is reversible by removing the disable line from the HR values; the chart will re-create the NP on the next reconcile.

## Follow-ups

- [ ] Add the kubelet-probe audit recipe to the `anton-repo-conventions` skill: a one-liner along the lines of `helm template <chart> <args> | yq 'select(.kind == "NetworkPolicy")'` paired with `yq '.spec.containers[].livenessProbe.httpGet.port, .spec.containers[].readinessProbe.httpGet.port, .spec.containers[].startupProbe.httpGet.port'` against the rendered Deployments, with a manual cross-check that every probe port has a corresponding NP allow rule.
- [ ] Survey existing HelmReleases for chart-managed NPs that may be enabled today. Three NPs currently exist in the cluster; spot-check them against this ADR. The expectation is that they are all hand-authored (intentional opt-ins under this ADR) but the survey closes that loop.
- [ ] File an upstream issue / PR on `controlplaneio-fluxcd/charts/flux-operator` to add port 8081 to the `web` NetworkPolicy ingress rules. Future operators on locked-down clusters will hit this same wall; fixing the upstream chart benefits the wider community even though anton itself defaults the NP off.
- [ ] Author a cluster-wide `CrashLoopBackOffHigh` PrometheusRule (see postmortem). Independent of this ADR but motivated by the same incident — would have caught the symptom regardless of the cause. Belongs in a separate plan / commit.
