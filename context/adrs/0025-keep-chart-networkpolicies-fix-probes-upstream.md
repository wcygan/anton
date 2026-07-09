---
status: Superseded-by 0029
date: 2026-05-04
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0025 — Keep chart-shipped NetworkPolicies enabled; rely on Cilium `allowLocalhost: always` and fix probe gaps upstream

> Anton keeps chart-managed NetworkPolicies enabled by default, in line with the industry-standard default-deny posture. Cilium's `allowLocalhost: always` (the cluster's current setting) is the load-bearing mechanism that lets kubelet probes succeed even when an `Ingress`-typed NetworkPolicy selects the pod. When a chart NP regresses that contract, the durable fix is filing an upstream issue or PR; a per-HelmRelease `networkPolicy.create: false` override is allowed only as a tactical opt-out, not as a precedent.

## Status

Accepted

## Context

This ADR replaces an earlier same-day draft (also numbered 0025, slug `disable-chart-networkpolicies-by-default`) that recommended the opposite policy. The earlier draft was overwritten in place after web research showed it conflicted with industry consensus, mischaracterized the underlying mechanism, and overcorrected for a single chart bug. The pre-overwrite content is recoverable from `git log` if needed; ADR immutability is set aside in this one case because the draft had not yet been cited or acted on, and the operator explicitly authorized the in-place overwrite.

The triggering incident is fully documented in [`context/postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md`](../postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md). Summary: the `controlplaneio-fluxcd/charts/flux-operator` chart (versions 0.46.0 and 0.48.0) ships a NetworkPolicy named `flux-operator-web` with `policyTypes: [Ingress]` that allows ingress to ports 8080 and 9080 only. Port 8081 (controller-runtime health probes) has no allow rule. Post Talos v1.13.0 / Kubernetes v1.36.0 upgrade on 2026-05-01, kubelet probes started getting denied; flux-operator entered perma-CrashLoopBackOff for ~3.5 days until detected. The tactical fix was disabling the chart NP via `web.networkPolicy.create: false`.

The research that informed this ADR found:

- **Industry consensus is default-deny.** [Calico docs](https://docs.tigera.io/calico/latest/network-policy/get-started/kubernetes-default-deny), [Kubernetes Security Best Practices 2026](https://devops.gheware.com/blog/posts/kubernetes-security-best-practices-2026.html), [ARMO](https://www.armosec.io/blog/kubernetes-network-policies-best-practices/), and multiple 2026 hardening guides recommend default-deny as the foundation. Default-disabling chart NPs in this repo would cut against that consensus without anton-specific justification.
- **Cilium auto-allows kubelet probes via `allowLocalhost: always`.** Per the [Cilium concepts docs](https://docs.cilium.io/en/stable/network/kubernetes/concepts/) and [oneuptime's writeup](https://oneuptime.com/blog/post/2026-03-13-cilium-default-ingress-allow-localhost/view): "by default, Cilium will always allow all ingress traffic from the local host to each pod" — even when an Ingress NP selects the pod. Anton uses Cilium 1.18.6 with this default. The 2026-05-04 incident is therefore evidence of a Cilium-side enforcement regression or a chart-shape edge case, **not** evidence that NPs are fundamentally hostile to homelab operations.
- **The "egress NP blocks probe" pattern is well-known and ecosystem-wide**, with established workarounds. See [fluxcd/flux2 #3173](https://github.com/fluxcd/flux2/discussions/3173) (experienced operators add targeted allow rules, not disable NPs), [fluxcd/flux2 #5218](https://github.com/fluxcd/flux2/issues/5218) (open chart improvement), [kubernetes/kubernetes #111581](https://github.com/kubernetes/kubernetes/issues/111581), and [projectcalico/calico #6476](https://github.com/projectcalico/calico/issues/6476). Two known Cilium kubelet-probe bugs ([cilium #34042](https://github.com/cilium/cilium/issues/34042) — netkit, fixed in 1.16.4; [cilium #37317](https://github.com/cilium/cilium/issues/37317) — k3s + 1.16.6, closed not-planned, fixed by 1.17) are not anton's specific failure path: anton runs Cilium 1.18.6 with veth, not netkit, and not k3s.
- **Anton's threat model is not single-trust.** Public ingress via the shared Cloudflare Tunnel (ADR 0023) exposes `bakery-server`, `homepage`, `csgoplant`, and others. A compromised public-facing pod has lateral-movement value into adjacent namespaces. CLAUDE.md also calls anton partly a learning cluster — codifying "always disable NPs" would teach a pattern that doesn't generalize.

## Decision

1. **Chart-managed NetworkPolicies stay enabled by default** in HelmRelease values across the repo. This is the inverse of the overwritten draft.
2. **Cilium's `allowLocalhost: always` is the load-bearing default** that ensures kubelet probes always reach pods regardless of NP shape. The setting is currently inherited (not explicitly set in `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`); it should stay inherited unless future Cilium release-notes indicate the default is changing, in which case make it explicit.
3. **When a chart NP regresses kubelet probes, the durable fix is upstream.** File an issue or PR against the chart's repo. Anton's local mitigation while the upstream fix is in flight is one of:
   - Add a sibling NetworkPolicy under the app's `app/` directory that explicitly allows ingress to the missing probe port from the host. The chart's NP stays in place; the gap is patched with an in-repo overlay.
   - Set `<component>.networkPolicy.create: false` on the offending HelmRelease as a tactical, comment-documented opt-out (the path taken for `flux-operator` on 2026-05-04). This is allowed but is **not** a default; each opt-out must (a) carry an inline comment naming the upstream issue/PR and the date the override was applied, and (b) be revisited when the chart bumps.
4. **`flux-app-author` does not scaffold `networkPolicy.create: false` by default.** New apps adopt their chart's shipped NP as-is. If the chart NP is later found to be misconfigured, that's caught by the audit step in (5) or by alerting in (6).
5. **`cluster-intake-gatekeeper` adds one line to its acceptance checklist** for any chart known to ship a NetworkPolicy: render `helm template` and confirm every container's `livenessProbe`, `readinessProbe`, and `startupProbe` port is covered by an allow rule (or by the chart relying on Cilium's host-allow). This is a one-time check at adoption, not a per-bump audit.
6. **A cluster-wide CrashLoopBackOff PrometheusRule is the safety net.** Independent of this ADR but motivated by the same incident: an alert on `rate(kube_pod_container_status_restarts_total[15m]) > 0.05` for 15 m would have caught the flux-operator regression in <1 h instead of 3.5 days. Tracked as a follow-up below.

## Alternatives considered

- **Default-disable chart NPs in HelmRelease values (the overwritten draft's position).** Rejected after research. Cuts against industry default-deny consensus, treats a single upstream chart bug as a forever-policy, and ignores the fact that Cilium's `allowLocalhost: always` already guards the kubelet path. Disabling cluster-wide makes anton less secure to fix a single reliability incident — wrong trade.
- **Adopt namespace default-deny NetworkPolicies and require explicit allow lists per namespace.** Out of scope. Would meaningfully tighten lateral-movement risk but adds an operational tax that anton hasn't justified yet (no untrusted workloads, single operator, no internal compliance ask). Defer until the threat model changes.
- **Author a CiliumClusterwideNetworkPolicy that explicitly allows kubelet → pod ingress on common probe ports cluster-wide.** Tempting as belt-and-braces against future Cilium regressions of `allowLocalhost: always`. Rejected for now because (a) common probe ports are unbounded across charts; (b) the CCNP becomes another perpetual rule to maintain; (c) duplicates what `allowLocalhost: always` already provides. Worth revisiting if `allowLocalhost: always` ever fails again — at that point, the CCNP is a clearer mitigation than a per-chart override.
- **Status quo (no ADR; the postmortem alone is the artifact).** Considered. Rejected because the postmortem records *what happened* but not *the policy going forward*. Future-me (or future Claude) needs a durable signal that "default-disable chart NPs" was considered and rejected, otherwise the next similar incident risks resurrecting the wrong fix.

## Consequences

### Accepted costs

- Future chart bumps that ship a regressed NP will surface as CrashLoopBackOff, not as a build-time failure. The follow-up cluster-wide CrashLoopBackOff alert is the planned safety net.
- The upstream-first commitment means anton accepts the lag between identifying a chart-NP bug and the chart maintainer shipping a fix. During that lag, the local in-repo NP-overlay or `networkPolicy.create: false` override is the bridge.
- Each tactical override (e.g. the current flux-operator one) becomes a small piece of technical debt that needs revisiting when the chart bumps. That's bounded — currently exactly one app — and the override comment will name the upstream tracker so re-evaluation is mechanical.

### Renovate-PR tax

None — no new component. The audit obligation in decision (5) is one-time at adoption.

### Restore-runbook obligation

None additional. Cilium's `allowLocalhost: always` is already in place via inheritance; if a future bump flips the default, the chart bump diff will surface it during PR review and an explicit `allowLocalhost: always` setting goes into Cilium's HelmRelease at that time.

## Follow-ups

- [ ] **Author cluster-wide CrashLoopBackOff PrometheusRule** in `kubernetes/apps/observability/kube-prometheus-stack/app/`. Two thresholds: `CrashLoopBackOffHigh` (warning at >0.05 restarts/s for 15 m) and `CrashLoopBackOffCritical` (critical at >0.1 restarts/s for 30 m). Highest-leverage prevention; would have caught 2026-05-04 in <1 h.
- [ ] **Add audit recipe to `anton-repo-conventions` skill** (decision step 5): `helm template <chart> <args> | yq 'select(.kind == "NetworkPolicy") | .spec.ingress[].ports'` cross-checked against probe ports in the rendered Deployments/StatefulSets/DaemonSets. One-time check at chart adoption, executed by `cluster-intake-gatekeeper`.
- [ ] **Survey the cluster's existing NetworkPolicies** (currently `csgoplant/csgoplant-default-deny`, `csgoplant/csgoplant-dragonfly`, `registries/harbor-redis`) and verify each allows ingress to the probe ports of its selected pods, or that the selected pods have no probes. Spot-check, not an ongoing obligation.
