---
status: Superseded-by 0019
date: 2026-04-18
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: [0006]
superseded-by: 0019
retrospective: false
---

# 0016 — Adopt SeaweedFS today on chart 1.0.11 via embedded `FilerSpec.S3`

> Supersedes 0006. Ship SeaweedFS on the released chart (`1.0.11` / operator `0.1.13`) using `FilerSpec.S3` embedded S3 with `filer.replicas: 2`. Drop the "wait for a chart after 1.0.11" gate. Migration to PR #200's standalone-S3 Deployment becomes a future plan when a chart release ships it.

## Status

Accepted

## Context

This supersedes ADR 0006, which gated SeaweedFS install on "the first seaweedfs-operator Helm chart release after 1.0.11" — one that ships PR #200's standalone-S3 CRD field. Upstream verification on 2026-04-18:

- Latest chart release is still `1.0.11` (2026-02-03); operator binary `0.1.13` (2026-02-03).
- PR #200 merged to `pr5-ingress` 2026-04-09 and landed on master via PR #202 on 2026-04-10. No subsequent chart release.
- Prior cadence was ~monthly (Jan/Feb 2026). We are now 2.5 months past `1.0.11` with no release-prep signal — no milestone, no draft release, no release-branch PR.
- ADR 0015 made Harbor the concrete-need anchor for unblocking SeaweedFS. Harbor restoration is delayed for every day SeaweedFS is deferred.

Re-reading PR #200 surfaces a factual correction to ADR 0006's framing: the standalone-S3 path reconciles a stateless Deployment **"in front of the filer"** — the filer is still deployed. The difference between `FilerSpec.S3` and PR #200's standalone-S3 is *where the S3 process runs* (embedded in the filer pod vs. a separate Deployment), not whether a filer exists. Both shapes deploy master + volume + filer + S3. ADR 0006's "no filer" shape was not implementable on the released chart and would not be implementable on PR #200 either.

Re-examining ADR 0006's three architectural arguments against `FilerSpec.S3` at anton's actual scale (LGTM 100–300 GB + Harbor, internal consumers only):

1. **"Scale wall on single S3 pod" regret** — hypothetical at this scale. `filer.replicas: 2` provides S3 endpoint HA that exceeds the interviewed need.
2. **Anti-completionism (no filer without a consumer)** — misapplied. The filer is a required component of both shapes. It is not speculative completionism.
3. **Cheap wholesale swap to Garage** — weaker than claimed. Filer-state for a pure-S3 deployment is bucket configs + keys, trivially recreatable. Volume-server data is the real state and is identical in both shapes.

`replication='000'` / 1 Gbit discipline (ADR 0005) holds in both shapes and carries forward unchanged.

## Decision

Adopt SeaweedFS via seaweedfs-operator chart `1.0.11` / binary `0.1.13` **today**, with:

- **S3 path**: `FilerSpec.S3` embedded. `filer.replicas: 2` for S3 endpoint HA.
- **SeaweedFS replication**: `000`. Longhorn owns durability.
- **Master**: `replicas: 3`, one per node.
- **Volume servers**: one per node on Longhorn-backed PVCs. `volumeSizeLimitMB` and per-pod request sized at scaffold time against the Harbor + LGTM budget.
- **Backing storage**: Longhorn `longhorn` StorageClass per ADR 0005.
- **Webhook bootstrap**: initial `webhook.enabled: false`, follow-up commit to flip after first reconcile.
- **IAM**: off. ESO pulls a static access-key/secret-key pair from 1Password vault `anton`.
- **S3 endpoint**: `HTTPRoute` on `envoy-internal`. Internal-only.
- **Consumer anchor**: Harbor per ADR 0015 is the first concrete consumer; LGTM follows in a successor plan.
- **Migration tracker**: when a chart release ships PR #200, open a successor plan to migrate `FilerSpec.S3` → top-level `spec.s3`. Not blocking.

## Alternatives considered

- **Continue waiting per ADR 0006** — rejected. Upstream delay is unbounded; 2.5 months past `1.0.11` with no release signal. Harbor restoration is the direct cost.
- **Pin chart / operator image to master sha `2682e41a`** — rejected. Relaxes release-tag discipline for an architectural benefit (S3 as stateless Deployment) that doesn't materially change outcomes at anton's scale. Renovate tracking of a commit-pinned chart is fragile. A pre-1.0 tagged chart is better operational hygiene than pre-1.0 master at an arbitrary commit.
- **Raw SeaweedFS Helm chart without the operator** — rejected. ADR 0006 already addressed this; the operator remains substantively healthier than the pre-ADR memo reported, and the raw-chart path loses CRD-driven upgrades and embedded IAM.

## Consequences

### Accepted costs

- **Deprecation tax**: `FilerSpec.S3` is upstream-deprecated per PR #200. Admission-webhook warning on `kubectl apply`. Migration to `spec.s3` is future work.
- **Filer HA open question**: filer runs with default embedded leveldb per pod. Filer HA semantics under `filer.replicas: 2` **must be verified at scaffold time** — some SeaweedFS filer HA modes require a shared backend (MySQL/Postgres/Redis) rather than per-pod leveldb. If leveldb-per-pod does not provide the expected metadata-sync behavior, options are `filer.replicas: 1` (accept S3 endpoint outage during filer restart) or add an external filer store. Flagged as a scaffold-time decision, not a new ADR.
- **Future migration cost**: `FilerSpec.S3` → standalone-S3 when the chart lands PR #200. One planned maintenance window; volume-server data preserved.
- **Tier-0 dependency** once installed. SeaweedFS down = every S3 consumer breaks. Same as ADR 0006.
- **Pre-1.0 operator CRD surface**. Scratch-namespace testing before production promotion remains mandatory.
- **Renovate-PR tax** — one more chart tracked; unchanged from ADR 0006.

### What this preserves (from ADR 0006)

- ADR 0004's best-of-breed split (Longhorn Block, SeaweedFS Object).
- ADR 0005's 1 Gbit discipline (`replication='000'`).
- Garage as first-class fallback if SeaweedFS regresses.
- `master.replicas: 3` HA and Longhorn-backed PVCs.
- No IAM, no external exposure, no speculative RWX.

### What this changes (from ADR 0006)

- **The "chart > 1.0.11" install gate is dropped.** Install now gates on Harbor as consumer + Longhorn green (both already satisfied as of this ADR).
- **"No filer" framing is retired** as factually unimplementable on either the current or the PR #200 path. Filer is explicitly part of the deployed shape.
- **Consumer anchor**: Harbor (ADR 0015), not LGTM.

## Re-adoption guidance

Supersession triggers specific to this ADR (in addition to ADR 0006's, which carry forward):

1. **Chart release ships PR #200** — migrate `FilerSpec.S3` → `spec.s3` in a successor plan. Not an ADR supersession; architecture unchanged.
2. **Filer HA under `filer.replicas: 2` proves unstable** — fall back to `filer.replicas: 1` or add an external filer store via successor plan.
3. **SeaweedFS proves operationally heavier than expected** within 6 months — successor ADR swaps to Garage v2.x per ADR 0006's existing Garage-fallback framing.

## Follow-ups

- [ ] Update plan 0004 Phase 1 gates: drop the "chart > 1.0.11" re-verify task; replace with "scaffold against chart 1.0.11 with `filer.replicas: 2`."
- [ ] Verify at scaffold time: does `filer.replicas: 2` with embedded leveldb provide the expected S3 HA semantics, or is an external filer store required? Decision captured in the scaffold PR description.
- [ ] Open a successor plan post-install: "Migrate SeaweedFS from `FilerSpec.S3` to standalone-S3 when chart release ships PR #200."
- [ ] Carry forward ADR 0006's still-active follow-ups: Seaweed CR authoring, ExternalSecret from 1Password, HTTPRoute on `envoy-internal`, smoke test + docs baseline, outstanding backup ADR.
