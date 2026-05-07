---
status: Accepted
date: 2026-05-07
deciders: ['@wcygan']
affects: all
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0027 — Every Flux app that authors a CRD-instance MUST `dependsOn` its platform Kustomization

> Cope-side architectural rule emerging from PR #282 / plan 0016. Every Flux Kustomization that authors resources of a CRD installed by another Kustomization MUST declare a `dependsOn` edge to the upstream — and every upstream that downstreams may depend on MUST set `wait: true` (or `healthChecks` / `healthCheckExprs`).

## Status

`Accepted`

## Context

Anton's reset rebuilt around Flux Kustomizations as the unit of in-cluster state. Until 2026-05-07 only 7 of 37 Kustomizations declared `dependsOn`, and 3 of those edges were weak (`wait: false` on the upstream made the dep resolve at "ks applied" rather than "Ready"). On a cold-start (3-node simultaneous reboot, recurring per the MS-01 silent-reboot pattern in plans 0013/0014/0015), reconcile order relied on Flux's 1h retry interval to converge — every retry was a CRD race, an `ExternalSecret`-not-resolved Secret, an `HTTPRoute`-without-Gateway, a `NetworkAttachmentDefinition`-applied-before-Multus.

Plan 0016's PR #282 audited the 37 Kustomizations and added 5 platform-layer `wait: true` flips and 11 consumer `dependsOn` additions. After it landed, the cluster reconciled to convergence in ~5 minutes instead of relying on the retry interval. The 2026-05-06/07 harbor-postgres incident confirmed the value of the wait-true-everywhere posture: `harbor-config` correctly stayed in `HealthCheckFailed` waiting for `harbor-postgres-2` to come up, instead of silently applying broken state.

The pattern was working, but only because PR #282 happened to inventory every existing consumer. Every NEW app added by future-me or future-Renovate would have to remember to declare the right `dependsOn` — and every NEW platform-layer Kustomization would have to remember to set `wait: true`. Without an explicit rule, drift is inevitable.

## Decision

Two enforceable rules:

**Rule A — Consumer must declare `dependsOn`.** Any Flux Kustomization that authors a resource of a CRD installed by another Kustomization MUST declare a `dependsOn` to that upstream. Cross-namespace deps require explicit `namespace:` (because the namespace `kustomization.yaml` patches every Flux Kustomization into the namespace). Concrete cases observed in anton today:

| Consumer authors | Must `dependsOn` | Upstream Kustomization |
| --- | --- | --- |
| `HTTPRoute` (gateway.networking.k8s.io) | the Gateway controller | `network/envoy-gateway` |
| `DNSEndpoint` (externaldns.k8s.io) | the external-dns controller | `network/cloudflare-dns` |
| `ExternalSecret` (external-secrets.io) | the ESO controller | `external-secrets/external-secrets` |
| `NetworkAttachmentDefinition` (k8s.cni.cncf.io) | Multus | `network/multus` |
| `Cluster` (postgresql.cnpg.io) | CNPG | `databases/cloudnative-pg` |
| `Dragonfly` (dragonflydb.io) | the Dragonfly operator | `databases/dragonfly-operator` |
| `Seaweed` (seaweed.seaweedfs.com) | the SeaweedFS operator | `storage/seaweedfs` |

**Rule B — Platform Kustomization must signal Ready.** Any Kustomization that downstream consumers will depend on MUST set `wait: true` (default kstatus health-checks) or — for richer signal — `healthChecks` (resource-name list) or `healthCheckExprs` (CEL on specific GVKs, like `cert-manager` does). Without one of these, downstream `dependsOn` collapses to "ks-applied" and the Rule A edge is nominal.

The two rules are inseparable: Rule A without Rule B silently doesn't work; Rule B without Rule A just deepens the reconcile chain without payoff.

## Consequences

- **Cold-start reconcile order is deterministic.** The post-PR-#282 measurement showed 39 of 40 Kustomizations Ready=True within ~5 min of merge — the chain depth is acceptable.
- **Steady-state `task reconcile` is slightly slower** (tens of seconds added) because every chain element actually waits for the previous to be Ready. Accepted price.
- **New apps are review-gated against the rule.** A new consumer that omits the `dependsOn` is review-rejected; a new platform layer with `wait: false` is review-rejected. Reviewers cite this ADR.
- **Cilium and CoreDNS remain exceptions.** They are bootstrapped by Helmfile (not Flux) so they cannot be `dependsOn`'d. Per plan 0016 Phase 3 task #4, migrating them under Flux is its own plan-sized initiative; until then their cold-start timing is the floor of cluster recovery.
- **`add-flux-app` and `flux-app-author` should encode this rule.** When scaffolding a new app, the skill/agent prompts should ask "does this app author HTTPRoutes, DNSEndpoints, ExternalSecrets, or any custom resource of an operator installed elsewhere?" and add the matching `dependsOn` edges automatically.

## Alternatives considered

- **Loose dependsOn (`wait: false` on upstream).** What we had pre-PR-#282. Rejected: the dep is nominal; downstream reconciles before the upstream's CRDs/controllers exist, generating cascade failures that only resolve via Flux's 1h retry interval.
- **Single global dependency tree** (e.g., a top-level Flux Kustomization that lists every leaf in topological order). Rejected: brittle (every new app requires editing the global file), conflicts with anton's per-namespace decomposition.
- **Mutating-webhook-based auto-dependency** (a webhook that scans authored resources and rewrites `dependsOn`). Rejected: invisible at review time, hard to debug, layer-of-abstraction that hides the actual ordering.

## References

- Plan 0016 — `context/plans/0016-harden-flux-cold-start-ordering.md`
- PR #282 (the 15-file changeset that operationalized the rule)
- 2026-05-06/07 harbor-postgres incident — the post-incident validation that the rule's `wait: true` semantics gate downstream reconcile correctly
- ADR 0017 (Multus CNI for Longhorn storage network), ADR 0018 (install-cni init container), ADR 0019 (SeaweedFS chart 0.1.14 with `spec.s3`) — the storage-fabric ADRs whose dependency chains the rule operationalizes
