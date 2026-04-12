---
name: S3 intake shortlist (April 2026)
description: Verified candidate status for k8s-native S3 on anton as of 2026-04-11; corrected 2026-04-11 after ADR 0006 interview surfaced stale Garage facts
type: project
---

**Fact**: On 2026-04-11 the user asked for a k8s-native S3 comparison triggered by https://blog.feld.me/posts/2026/04/i-just-want-simple-s3/ . Intent was not declared initially; I produced conditional verdicts. Later the same day, ADR 0006 ("Adopt SeaweedFS for object storage") recorded the concrete pick under the ADR 0004 framework — with the LGTM monitoring-stack successor to ADR 0003 as the concrete-need anchor.

**Upstream status re-verified 2026-04-11 via direct API queries** (not scraped from blog posts or prior memory):

- `minio/minio`: archived 2026-02-13.
- `minio/operator`: archived 2026-03-20, last release v7.1.1 (2025-04).
- `rook/rook`: CNCF Graduated, v1.19.3 (2026-03-24), very active. Still rejected for anton by ADR 0002's indefinite defer.
- `seaweedfs/seaweedfs` + `seaweedfs/seaweedfs-operator`:
  - Default branch `master`, last push **2026-04-10** (not stale).
  - **PR #200 "standalone S3 gateway" merged 2026-04-09** — the operator now natively supports S3-gateway-only deployment without the filer. This invalidates the earlier "skip the operator" recommendation.
  - **PR #202 "ingress for volume/filer/S3" merged 2026-04-10**.
  - Operator binary latest: `seaweedfs-operator-0.1.13` (2026-02-03) — still pre-1.0.
  - Helm chart latest: `1.0.11` (2026-02-03) — monthly cadence Jan/Feb 2026.
  - Published Helm repo: `https://seaweedfs.github.io/seaweedfs-operator/` with a worked FluxCD install example in the README.
  - **The "Maintenance and Uninstallation: TBD" warning cited in the earlier version of this memo no longer appears in the current README.** Earlier memo claim was stale.
  - Apache-2.0, 291 stars, 36 open issues, not archived.
- `deuxfleurs-org/garage` — **the earlier version of this memo was factually wrong on Garage**. Corrected facts:
  - `main-v2` HEAD SHA: **`9969c3e5999ce5f7077b36ffffc6b9d535fd83f6`** (CORS website-config fix #1392).
  - **Last commit on main-v2: 2026-03-22T17:09:16Z** (≈3 weeks before this memo, NOT 16 months stale).
  - Current v2 release: **v2.2.0** published **2026-01-24**.
  - Release cadence: v2.0.0 (2025-06-14) → v2.1.0 (2025-09-15) → v2.2.0 (2026-01-24), ~quarterly.
  - Parallel **v1.3.1** LTS shipped the same day (2026-01-24) — v1 branch still maintained for conservative users.
  - Source: `git ls-remote https://git.deuxfleurs.fr/Deuxfleurs/garage` + Deuxfleurs Gitea `/api/v1/repos/Deuxfleurs/garage/{branches/main-v2,releases}` endpoints on 2026-04-11.
  - License AGPLv3, in-repo Helm chart at `script/helm`.
  - **Correcting the earlier claim**: `"main-v2 last commit 2024-12-17 (~16mo stale)"` was wrong. Likely the earlier research queried a long-abandoned mirror or confused `main-v2` with a pre-v2 branch. ADR 0006's "Alternatives considered" section carries this retraction authoritatively; ADR 0004's shortlist row is immutable and remains wrong until/unless a successor ADR supersedes it.

**Anton cluster state (verified 2026-04-11)**: `kubernetes/apps/` contains only cert-manager, external-secrets, network, flux-system, kube-system, default, playground. **Zero persistent storage backend.** Picking S3 is implicitly picking a storage layer too. Since 2026-04-11 the ADR chain has been:
- ADR 0004 (framework) — best-of-breed, no Rook, no external S3.
- ADR 0005 (Block) — Longhorn, 2-replica default, install gated on the monitoring-stack successor to ADR 0003.
- ADR 0006 (Object) — **SeaweedFS via seaweedfs-operator, S3-gateway-only, `replication='000'`, master replicas=3, s3 replicas≥2, no filer**. Install gated behind Longhorn landing.

**Why SeaweedFS over Garage on 2026-04-11** (not upstream-health — Garage is legitimately active as corrected above): the user chose SeaweedFS for (1) the Kubeflow Pipelines 2.15 "default S3" blessing, (2) Apache-2.0 vs AGPLv3 (soft preference, not binding for homelab), (3) the just-merged PR #200 making operator-managed gateway-only viable, (4) explicit FluxCD install example in the operator README. The regret-shape question interviewed directly ranked "scale wall on single S3 pod" higher than "should've been Garage" — hence S3 replicas≥2 and master HA from day one.

**Graveyard relevance**: Rook-Ceph removed at `889a9662` is a direct hit on the "distributed/HA storage" category in references/anton-history.md. Blocks concrete-need Rook under ADR 0002's indefinite defer; does not block learning-intent Rook *if* the stated goal is specifically understanding why it didn't fit last time.

**Why**: S3 on k8s is a recurring question for homelab operators and this candidate set is likely to come up again. Upstream status dates decay fast — and this memo's previous version is a concrete example of how fast a "verified" claim can rot. Always re-verify with `git ls-remote` + direct API queries, never trust prior-memo claims past ~60 days.

**How to apply**:
- If S3 comes up again in the next 60 days, reuse this evidence.
- **Re-verify upstream dates before any subsequent S3 decision** — both for the pick and for any alternative. The previous version of this memo shipped a 16-month-stale claim that ADR 0004 immortalized; ADR 0006 had to retract it. Do not let that happen again.
- When writing or superseding ADR 0006, cite the Garage retraction from 0006's "Alternatives considered" section directly rather than re-researching from scratch.
- If a reader encounters ADR 0004's Object shortlist table, remind them that the Garage row is known-wrong and point to 0006's retraction.
