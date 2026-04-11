---
name: S3 intake shortlist (April 2026)
description: Verified candidate status for k8s-native S3 on anton as of 2026-04-11; blog post by feld.me triggered the comparison
type: project
---

**Fact**: On 2026-04-11 the user asked for a k8s-native S3 comparison triggered by https://blog.feld.me/posts/2026/04/i-just-want-simple-s3/ . Intent was not declared; I produced conditional verdicts under both concrete-need and learning rubrics.

**Verified upstream status (2026-04-11)**:
- `minio/minio`: archived 2026-02-13
- `minio/operator`: archived 2026-03-20, last release v7.1.1 (2025-04)
- `rook/rook`: CNCF Graduated, v1.19.3 (2026-03-24), very active
- `seaweedfs/seaweedfs`: 31.5k stars, active; `seaweedfs-operator` v0.1.13 (2026-02-03), pre-1.0, README "Maintenance and Uninstallation: TBD"
- `deuxfleurs-org/garage`: main-v2 last commit 2024-12-17 (~16mo stale as of today), 88 tags, AGPL-3, in-repo helm chart at `script/helm`

**Anton cluster state (verified 2026-04-11)**: `kubernetes/apps/` contains only cert-manager, external-secrets, network, flux-system, kube-system, default, playground. **Zero persistent storage backend.** Picking S3 is implicitly picking a storage layer too.

**Graveyard relevance**: Rook-Ceph removed at `889a9662` is a direct hit on the "distributed/HA storage" category in references/anton-history.md. Blocks concrete-need Rook without a new delta; does not block learning-intent Rook *if* the stated goal is specifically understanding why it didn't fit last time.

**Why**: S3 on k8s is a recurring question for homelab operators and this candidate set is likely to come up again. Upstream status dates decay fast — MinIO archival timing especially.

**How to apply**: If S3 comes up again in the next 90 days, reuse this evidence rather than re-fetching. Re-verify upstream dates after 2026-07 since MinIO-operator archival and Garage cadence could change (fork activity, community rescue).
