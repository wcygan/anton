# 30-second triage heuristics

The short-circuit filter invoked before the full rubric. If any of these fires, stop — reject, defer, or (for several of them) ask whether this is actually a learning intake. The whole point of heuristics is to avoid spending 15 minutes on a decision that should take 30 seconds, but not at the cost of silently vetoing honest learning intake.

## Ask-first triggers (not auto-reject)

These *look* like auto-rejects but almost always have a legitimate learning-intake path. Ask the user whether they meant to declare learning intent before rejecting:

- **"Solves a problem you don't have today" / can't finish the "I cannot ___" sentence.** This is the default shape of a learning intake. Ask: *"Is this learning intake? If so, give me a timebox and exit plan and we'll evaluate it that way."* Reject only if the user insists it's concrete need when it isn't.
- **<50 stars + single maintainer + no release in 6 months.** Under concrete-need intent this is a reject (sustainability). Under learning-intake intent it's fine — abandoned projects are perfectly good to learn from. Ask which intent before concluding.
- **HA variant of something that could run single-instance.** "HA Postgres on 3 nodes" is a known landmine as a production need — but as a learning experiment, it's one of the most *useful* things you can put on a homelab cluster to understand distributed systems failure modes. Ask the intent.
- **Requires its own Postgres / Redis / MinIO / Kafka as a prerequisite.** Two intakes in one under concrete need. Under learning, it's a package deal and you'd be learning all of it at once — which may or may not be the point. Ask.
- **Already in the removal graveyard.** Under concrete need, demand a delta. Under declared learning intake *with a new angle the user wants to learn*, the graveyard hit is itself sometimes the reason — "I want to understand why it didn't work last time." That's valid. Ask.

## Reject-on-sight (no learning carve-out)

These remain auto-reject under every intent because they break containment or fork the cluster:

1. **Overlaps something already installed** at the Tier-0 layer. Two of anything — two ingress controllers, two secret stores, two cert issuers, two monitoring stacks, two service meshes, two CNIs — is a reject until one is removed first. Anton already has Cilium, envoy-gateway, ESO, cert-manager, external-dns, cloudflared. If the candidate duplicates any of these *as an alternative rather than a replacement*, stop. (Replacing one of these is not an intake — it's a Tier-0 rebuild and belongs in a separate decision.)

2. **Installs a mutating webhook that matches `*` AND replaces a Tier-0 component** (CNI, DNS, CSI, ingress, cert issuer, secret store). Blast radius is the entire cluster. Even as a learning experiment this is a cluster rebuild, not a namespace-scoped add.

3. **Ships sealed-secrets, vault-operator, or its own secret CRD** and cannot be configured to read from a standard `Secret`. Forks the secrets story regardless of why it was added. Reject.

4. **Uninstall leaves orphaned finalizers or CRDs that other apps depend on.** Containment gate failure — this is how learning experiments become permanent against the user's will.

## Downgrade-to-yellow-on-sight

These don't auto-reject but force extra scrutiny under concrete-need intent. Under learning intent they are non-issues — feel free to pass through:

- **Community helm chart (not in-repo).** k8s-at-home/charts was the cautionary tale — it's deprecated. Community charts lag, break, and orphan. Downgrade `Integration fit` to yellow at best. (Learning intent: fine.)
- **No `/metrics` endpoint.** Under concrete need, downgrade `Observability hooks` to red. (Learning intent: fine — you're not trying to operate it long-term.)
- **Values schema churns between minors.** Renovate + Flux will fight you every upgrade. Downgrade `Maintenance burden` to yellow under concrete need. (Learning intent: fine — your timebox is shorter than the churn.)
- **Chart's `resources:` defaults are either missing or set to `{}`.** Under every intent, demand explicit requests/limits before install. For learning intent this becomes the "resource ceiling set?" containment check, not a yellow — it's a pass-or-defer.

## The one hard stop that isn't a heuristic

Gate 6 (tested restore runbook for stateful *concrete need*) is not a heuristic, it's a hard gate. Don't try to short-circuit it here. If the user says "I'll write the runbook after install," that isn't a yellow — it's a reject under concrete-need intent. **But under learning intent**, state can be throwaway with an explicit acknowledgement — see the contained-learning variant in [rubric](rubric.md#contained-learning-variant).

## Budget for the whole filter

30 seconds. If you're reading the upstream README to answer a heuristic, you're already past the heuristic phase and into the rubric. That's fine, but know which phase you're in.

## Downgrade-to-yellow-on-sight

These don't auto-reject but force extra scrutiny:

- **Community helm chart (not in-repo).** k8s-at-home/charts was the cautionary tale — it's deprecated. Community charts lag, break, and orphan. Downgrade `Integration fit` to yellow at best.
- **No `/metrics` endpoint.** You will never know when it breaks. Downgrade `Observability hooks` to red regardless of anything else.
- **Values schema churns between minors.** Renovate + Flux will fight you every upgrade. Downgrade `Maintenance burden` to yellow.
- **Single binary with config baked in at build time.** Hard to integrate with ESO / ConfigMap patterns. Downgrade `Integration fit` to yellow.
- **Chart's `resources:` defaults are either missing or set to `{}`.** Someone will hit OOMKilled at 2am. Downgrade `Resource footprint` to yellow and demand user set explicit requests before install.

## The one hard stop that isn't a heuristic

Gate 6 (tested restore runbook for stateful) is **not** a heuristic, it's a hard gate. Don't try to short-circuit it here. If the user says "I'll write the runbook after install," that isn't a yellow — it's a reject. Put it here as a reminder, not as a downgrade.

## Budget for the whole filter

30 seconds. If you're reading the upstream README to answer a heuristic, you're already past the heuristic phase and into the rubric. That's fine, but know which phase you're in.
