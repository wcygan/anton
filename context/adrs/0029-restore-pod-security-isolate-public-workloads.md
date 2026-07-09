---
status: Accepted
date: 2026-07-09
deciders: ['@wcygan']
affects: security
intent: concrete-need
supersedes: [0025]
superseded-by: null
retrospective: false
---

# 0029 — Restore Pod Security and isolate public workloads

> Anton restores Talos's default Pod Security Admission policy and applies targeted default-deny isolation to externally routed workloads, with explicit infrastructure and probe exceptions.

## Status

Accepted

## Context

This supersedes ADR 0025 because the threat model has changed. The 2026-07-09
security audit found that Anton deletes Talos's default PodSecurity admission
configuration, leaves several namespaces unlabeled, and has only two live
NetworkPolicies despite multiple Cloudflare-routed workloads. It also found an
ingress rule in cs2plant that allows its application port from every source.

ADR 0025 correctly kept chart-shipped NetworkPolicies enabled, but deferred
targeted default-deny isolation and treated Cilium's `allowLocalhost: always`
as the sole probe guarantee. Anton's May 2026 Flux operator incident showed
that assumption is not sufficient operational protection. Policy rollout must
therefore make probe paths explicit and test them before expansion.

## Decision

We will restore Talos's default PodSecurity policy: `baseline` enforcement with
`restricted` audit and warning, retaining Talos's `kube-system` exemption.
Namespaces that require host access, elevated capabilities, or privileged
storage/network agents will be labeled explicitly as `privileged`; ordinary
namespaces will enforce at least `baseline`, and will move to `restricted`
where their rendered workloads pass a server-side admission dry run.

Chart-shipped NetworkPolicies remain enabled. In addition, each externally
routed workload will receive a pod-selective default-deny policy with only its
required Envoy, DNS, metrics, backend, and egress paths. Kubelet probe traffic
will be allowed explicitly with namespaced Cilium policies using the `host` and
`remote-node` entities. Policies roll out one workload at a time and must pass
route, probe, metrics, and dependency checks before the next workload changes.

## Alternatives considered

- **Keep admission and network defaults unchanged** — rejected because a compromised public workload retains unnecessary lateral-movement paths and unlabeled namespaces default to privileged admission.
- **Apply namespace-wide default deny everywhere** — rejected because CNI, observability, ClickStack, and Longhorn have broad, load-bearing traffic paths; a blanket policy has disproportionate outage risk.
- **Rely only on Cilium's inherited localhost allowance for probes** — rejected because Anton has already experienced a probe regression while that default was expected to protect the path.

## Consequences

### Accepted costs

- Infrastructure namespaces keep an explicit privileged exception until their
  host-level workloads are redesigned; admission audit/warn results remain a
  hardening backlog rather than silent defaults.
- Every public workload policy needs an application-specific connectivity
  contract and live negative test, increasing manifest and upgrade-review tax.
- Talos admission changes and network policies require staged rollouts with
  immediate rollback if probes, routes, metrics, storage, or backend traffic
  regress.
- No new component or stateful restore obligation is introduced.

## Follow-ups

- [ ] Label all committed namespaces and restore Talos's default PodSecurity configuration.
- [ ] Add and validate targeted isolation for cs2plant, bakery, echo, homepage, and the Flux webhook.
- [ ] Track privileged namespace exceptions in plan 0019 and narrow them as host workloads are redesigned.
