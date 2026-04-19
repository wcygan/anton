---
status: Accepted
date: 2026-04-19
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: [0016]
superseded-by: null
retrospective: false
---

# 0019 — Install SeaweedFS on chart 0.1.14 with canonical `spec.s3`

> Supersedes 0016. Install SeaweedFS on seaweedfs-operator chart `0.1.14` / app `1.0.12` using the top-level `spec.s3` standalone-S3 path. Architecture is unchanged from 0016; only the CRD field moves. The same-day release of 1.0.12 falsifies 0016's "no release signal" premise and retires the need for a follow-on migration plan.

## Status

Accepted

## Context

This supersedes ADR 0016, written 2026-04-18. ADR 0016's decision to install on `FilerSpec.S3` was driven by one load-bearing premise: the seaweedfs-operator project had been quiet for 2.5 months post-`1.0.11` with no release signal, so the canonical `spec.s3` path (introduced by PR #200, merged to master 2026-04-10) was not available on any released chart.

That premise was falsified within 24 hours. On 2026-04-19 at 22:00 UTC — the same day plan 0005 was opened — upstream published chart `0.1.14` / operator `1.0.12`. The release includes PR #200 and its follow-up PR #202. Release notes: https://github.com/seaweedfs/seaweedfs-operator/releases/tag/1.0.12. Full diff: 59 commits between 1.0.11 and 1.0.12.

In 1.0.12 the CRD preserves `FilerSpec.S3` for backward-compat but the Go struct is godoc-deprecated, and the operator's validating webhook emits an admission warning on any CR that enables the embedded path. The webhook also rejects CRs that set both `spec.s3` and `filer.s3.enabled=true` — they're mutually exclusive. Other material 1.0.12 changes that affect a production install: RBAC expands to include `apps/deployments` (required for the new S3 gateway Deployment); new validating-webhook logic plus configurable certgen image parameters; StatefulSet auto-recreate on an empty→non-empty `VolumeClaimTemplates` transition (PR #188); optional mTLS between components via cert-manager (soft no-op if CRDs absent); per-component Ingress support; admin + worker CRDs added (opt-in); Golang CVE bump.

ADR 0016's "re-adoption guidance" clause #1 anticipated exactly this event — "chart release ships PR #200 → migrate `FilerSpec.S3` → `spec.s3` in a successor plan, not an ADR supersession." That clause assumed the install would already be live on `FilerSpec.S3`. Because the release arrived before any install happened, installing the deprecated path for ~24h and then immediately scheduling migration work is pure tax. The cleaner move is to supersede 0016 and install on the canonical path from day one. Architecture is unchanged — only the CRD field moves.

## Decision

Install SeaweedFS via seaweedfs-operator chart `0.1.14` / app `1.0.12` with:

- **S3 path**: top-level `spec.s3` (standalone-S3 Deployment in front of the filer). `FilerSpec.S3` is **not used**.
- **S3 Deployment**: `spec.s3.replicas: 2` for S3 endpoint HA. The S3 process runs in its own stateless Deployment; the filer is still deployed.
- **Filer**: `filer.replicas: 2` with default embedded leveldb metadata backing. Filer-HA semantics under this shape still require scratch-namespace shakeout (inherited open question from 0016); the open question is not resolved by the path swap.
- **SeaweedFS replication**: `000`. Longhorn owns durability (ADR 0005).
- **Master**: `replicas: 3`, one per node.
- **Volume servers**: one per node on Longhorn-backed PVCs. `volumeSizeLimitMB` 30000 (30 GB) and 100 GB PVC per volume-server per plan 0005's byte budget.
- **Webhook bootstrap**: initial `webhook.enabled: false`, follow-up commit to flip after first reconcile (unchanged from 0016).
- **IAM**: off. ESO pulls a static access-key / secret-key pair from 1Password vault `anton` (unchanged from 0016).
- **S3 endpoint**: `HTTPRoute` on `envoy-internal`. Internal-only (unchanged from 0016).
- **Consumer anchor**: Harbor per ADR 0015 (unchanged from 0016). LGTM follows in a successor plan.
- **Hand-off**: plan 0005 Phase 1 scratch shakeout continues on chart 0.1.14 / `spec.s3`. Phase 4's "migrate `FilerSpec.S3` → `spec.s3`" successor plan is retired — no migration needed.

## Alternatives considered

- **Continue per ADR 0016 verbatim (chart 0.1.11 + `FilerSpec.S3`)** — rejected. Installs a chart that shipped 2.5 months ago and skips the 1.0.12 Golang CVE bump, RBAC expansion, and validating-webhook hardening. Schedules an immediate migration to `spec.s3` against the same operator version we'd pick anyway for the migration. Pure cost, no benefit now that 0.1.14 exists.
- **Chart 0.1.14 + `FilerSpec.S3`** (newer chart, same CRD field as 0016) — rejected. Preserves 0016's decision body and gets the 1.0.12 fixes, but accepts the admission-webhook deprecation warning and keeps the Phase 4 migration plan alive. There is no cluster-side reason to install a deprecated field on day one — the deprecation cost is real (warning on every apply, scheduled migration work) while the benefit (decision-body fidelity to 0016) is purely historical and served better by this supersession.
- **Wait for chart 0.1.15** — rejected on the same grounds that already sank 0006's "wait" stance. Harbor is waiting. 0.1.14 is a tagged release with the canonical path; there is nothing to wait for.

## Consequences

### Accepted costs

- **Chart 0.1.14 is the first release with PR #200 code in production use by us.** No prior anton soak time on the standalone-S3 Deployment. Scratch-namespace shakeout (plan 0005 Phase 1) carries more weight — in particular, the S3 Deployment's crash/restart behavior and its interaction with the filer-HA path must both be verified before promotion to production.
- **Filer-HA open question carries forward unchanged.** Embedded leveldb filer-HA semantics under `filer.replicas: 2` still require verification. If leveldb-per-pod does not provide the expected metadata-sync behavior, fall back to `filer.replicas: 1` or add an external filer store. Path swap does not resolve this.
- **RBAC change**: operator ClusterRole includes `apps/deployments`. Chart handles this, but worth noting for any future custom RBAC audit.
- **StatefulSet auto-recreate on VolumeClaimTemplates transition** (PR #188). Not triggered by the initial install, but relevant to any future Seaweed CR edit that adds a VolumeClaimTemplate to a component whose template was previously empty.
- **Tier-0 dependency** once installed (unchanged from 0016). SeaweedFS down = every S3 consumer breaks.
- **Pre-1.0 operator CRD surface** (unchanged from 0016). CRD fields may shift in future minor releases.
- **Renovate-PR tax** — one more chart tracked; unchanged from 0016.

### What this preserves (from ADRs 0004, 0005, 0006, 0015, 0016)

- ADR 0004's best-of-breed split (Longhorn Block, SeaweedFS Object).
- ADR 0005's 1 Gbit discipline (`replication='000'`).
- Garage as first-class fallback if SeaweedFS regresses.
- `master.replicas: 3` HA and Longhorn-backed PVCs.
- No IAM, no external exposure, no speculative RWX.
- ADR 0015's Harbor-as-anchor framing.

### What this changes (from ADR 0016)

- **S3 CRD field**: top-level `spec.s3` instead of embedded `FilerSpec.S3`.
- **Chart / operator version**: 0.1.14 / 1.0.12 instead of 0.1.13 / 1.0.11.
- **Successor plan retired**: plan 0005 Phase 4's "Migrate SeaweedFS from `FilerSpec.S3` to standalone-S3" is no longer needed. Phase 4 will be edited accordingly.

## Re-adoption guidance

Supersession triggers specific to this ADR (in addition to 0006's and 0016's, which carry forward):

1. **`spec.s3` standalone-S3 proves unstable at small scale** — successor ADR falls back to `FilerSpec.S3` (still supported in 1.0.12) or pivots to Garage per ADR 0006's Garage-fallback framing.
2. **Filer HA under `filer.replicas: 2` proves unstable** — same as 0016: fall back to `filer.replicas: 1` or add an external filer store via successor plan. Not an ADR supersession.
3. **Upstream drops `FilerSpec.S3` entirely without a migration story** — no action required; we are already on `spec.s3`. This is the whole point of the supersession.

## Follow-ups

- [ ] Flip ADR 0016 `status:` line to `Superseded-by 0019` (skill handles this).
- [ ] Update plan 0005: Phase 0 outcome is option C; Phase 1 targets chart 0.1.14 / `spec.s3`; Phase 4's `FilerSpec.S3` → `spec.s3` successor plan is retired.
- [ ] Carry forward 0016's scratch-time verification of `filer.replicas: 2` HA semantics. Capture verdict in the scaffold PR description.
- [ ] No separate "chart release ships PR #200" successor plan needed — this ADR is that migration, absorbed into the initial install.
