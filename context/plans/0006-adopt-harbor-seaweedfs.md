---
status: In-progress
opened: 2026-04-20
closed: null
affects: registries
intent: concrete-need
related-adrs: [0015, 0019, 0005]
review-by: null
---

# 0006 — Adopt Harbor on SeaweedFS S3 backend

> Execute ADR 0015 — restore Harbor as anton's in-cluster OCI registry, backed by the freshly-installed SeaweedFS S3 endpoint (ADR 0019 / plan 0005), with CNPG Postgres + DragonflyDB cache operators reinstated, re-exposed on the reused `192.168.1.105` LAN LB and `registry.<tailnet-name>.ts.net` Tailscale ingress, Spegel mirror config patched back in, and the Talos insecure-registry kubelet config verified.

## Goal

Stand up Harbor as a production workload on the restructured cluster, preserving the pre-reset shape (2-replica core/portal/jobservice¹/registry + CNPG-3-rep Postgres + Dragonfly-3-rep cache) but routing image blobs to `http://seaweedfs-s3.storage.svc.cluster.local:8333` instead of the removed Ceph filesystem. Done means: a laptop `docker push` via `registry.<tailnet-name>.ts.net` succeeds, an in-cluster pod pulls from `192.168.1.105` without an `imagePullSecret`, Spegel mirrors the pull across nodes, and Harbor survives a controlled reboot of its hosting node without dropping the registry service. Trivy stays off (per ADR 0015). Backup strategy for Harbor's Postgres is flagged but deferred to a future ADR — not in scope here.

¹ jobservice: start at `replicas: 1` per ADR 0015 Consequences (RWX gap), not 2. Scale up only if load warrants it.

## Acceptance criteria

- [ ] Harbor `HelmRelease` reports Ready with S3 storage driver resolving `http://seaweedfs-s3.storage.svc.cluster.local:8333` bucket `harbor`; no 500s in `core` or `registry` logs on steady state
- [ ] CNPG Postgres `Cluster harbor-postgres` 3/3 healthy; DragonflyDB `Dragonfly harbor-redis` 3/3 healthy; both CRD operators reconciled green
- [ ] End-to-end round-trip passes: laptop `docker login registry.<tailnet-name>.ts.net` + `docker push` succeeds; a test Pod pulls the same image via `192.168.1.105/library/<image>` without an `imagePullSecret`
- [ ] Spegel mirror reactivated — containerd on each node accepts `192.168.1.105` as an insecure mirror; a second-node pull of the pushed image is served peer-to-peer (verified via spegel metrics or containerd logs)
- [ ] Docs refreshed: `docs/docs/notes/harbor-registry.md` + `harbor-developer-guide.md` updated for anonymous-pull + SeaweedFS S3 backend (drop the legacy cluster-wide ImagePullSecret section)

## Tasks

### Phase 1 — SeaweedFS bucket + credential wiring for Harbor

Current state: SeaweedFS has one admin identity (`admin`, all Actions) at Secret `storage/seaweedfs-s3-config` key `s3.json`, backed by 1Password item `seaweedfs-harbor` in vault `anton`. Harbor can reuse these admin creds for v1. Least-privilege (a dedicated `harbor` identity scoped to bucket `harbor`) is a hardening pass the plan can take on after first-green, not a v1 gate.

- [ ] **Decide credential scope for v1.** Default: reuse existing admin identity from `storage/seaweedfs-s3-config`. Revisit under "Hardening follow-ups" if/when a second SeaweedFS consumer arrives (the first multi-tenant trigger forces us to add per-consumer identities anyway).
- [ ] **Pre-create the `harbor` bucket.** Harbor's registry driver can auto-create a bucket on first use, but creating it ahead of time lets us verify the admin creds work and the bucket policy is empty before Harbor mounts it. Run from an in-cluster aws-cli pod (same recipe as the plan 0005 baseline-note smoke test, just `s3 mb s3://harbor` instead of `smoke-test`). Record success in Log.
- [ ] **Mirror-project the credential into the `registries` namespace.** Options: (a) a second `ExternalSecret` in `kubernetes/apps/registries/harbor/app/` pulling the same 1Password fields into a Harbor-shaped Secret (access-key + secret-key as plain keys, not the `identities[]` JSON that SeaweedFS's own S3 config expects), or (b) ESO's `PushSecret` / a `Secret` reshape in the Harbor namespace. Decision: **(a)** — two `ExternalSecret`s, one per consumer, is the cleanest ESO idiom and avoids a cross-namespace Secret read. Harbor's HelmRelease references the Harbor-namespace Secret via `registry.credentials.existingSecret` or equivalent (verify exact values-key against chart).

### Phase 2 — CloudNative-PG operator reinstate

Operator was removed on 2026-04-10 alongside Harbor. CRDs and the operator Deployment all need to come back before Harbor's Postgres `Cluster` CR can land.

- [ ] Scaffold `kubernetes/apps/databases/cloudnative-pg/` (or `kubernetes/apps/database/cnpg-operator/` — verify the pre-reset path against `git log --diff-filter=D` + `docs/`). 3-file Flux pattern: operator HelmRelease only (no CNPG `Cluster` CR here — that lives next to Harbor in Phase 4).
- [ ] Pin chart to the current stable at scaffold time; cross-check against CNPG's `Deprecated` matrix on the release page before merging.
- [ ] First reconcile: operator Deployment Ready, `clusters.postgresql.cnpg.io` + `poolers.postgresql.cnpg.io` + other CRDs Established.
- [ ] Smoke test (optional but recommended): one-off scratch `Cluster` CR in a throwaway namespace, 1-replica, confirms the operator actually provisions Postgres on Longhorn. Tear down.

### Phase 3 — DragonflyDB operator reinstate

Same shape as Phase 2. DragonflyDB operator was removed on 2026-04-10 by commit `f2e73cf7`; reinstate under `kubernetes/apps/databases/` or similar.

- [ ] Scaffold the DragonflyDB operator HelmRelease; pin chart version.
- [ ] First reconcile: operator Deployment Ready, `dragonflies.dragonflydb.io` CRD Established.
- [ ] Smoke test (optional): scratch `Dragonfly` CR in a throwaway namespace.

### Phase 4 — Harbor scaffold + install

This is the biggest phase. ADR 0015's Decision section is the authoritative field-set; this phase translates it into Flux manifests.

- [ ] Scaffold `kubernetes/apps/registries/harbor/` (3-file Flux pattern + sibling `harbor-config/` if cluster-level resources — Postgres CR, Dragonfly CR, ExternalSecrets — want their own Kustomization). Mirror the chart-vs-config split we used for SeaweedFS: `harbor/` (HelmRelease + HelmRepository), `harbor-config/` (Postgres CR, Dragonfly CR, ExternalSecrets, LoadBalancer Service, Tailscale ingress Annotations or CR, Spegel mirror config patch).
- [ ] **Prereq — 1Password inventory.** Items needed in vault `anton`: (a) `harbor-admin` (admin password) — new, needs creation; (b) SeaweedFS creds already exist as `seaweedfs-harbor`. Log any other credentials that surface during scaffolding (Postgres app-user password is auto-generated by CNPG; Dragonfly has no auth by default — confirm).
- [ ] **HelmRelease values shape (ADR 0015 → manifest mapping):**
  - `expose.type: loadBalancer`, LB annotations for Cilium IPAM / `192.168.1.105` reuse
  - `externalURL: https://registry.<tailnet-name>.ts.net` (verify Harbor's behaviour when LB URL differs from externalURL; previous install tolerated this)
  - `persistence.imageChartStorage.type: s3` with `s3.region`, `s3.regionendpoint: http://seaweedfs-s3.storage.svc.cluster.local:8333`, `s3.bucket: harbor`, `s3.secure: false`, `s3.skipverify: true` (SeaweedFS speaks HTTP cluster-internally)
  - `database.type: external`, `database.external.host: harbor-postgres-rw`, Postgres creds from ExternalSecret
  - `redis.type: external`, `redis.external.host: harbor-redis`, no auth
  - `jobservice.replicas: 1` (RWX gap — see ADR 0015 Consequences), `core.replicas: 2`, `portal.replicas: 2`, `registry.replicas: 2`
  - `trivy.enabled: false`
  - Project-wide anonymous pull: configured post-install via admin API call against `library` project, not via chart values
- [ ] **Postgres `Cluster` CR** under `harbor-config/`: 3 replicas, Longhorn block storage, instance resources sized to match previous install (check `docs/docs/notes/harbor-registry.md` for the prior sizing).
- [ ] **Dragonfly `Dragonfly` CR** under `harbor-config/`: 3 replicas, Longhorn block storage.
- [ ] **ExternalSecrets**: `harbor-admin` (admin password), `harbor-s3-creds` (SeaweedFS admin AK/SK reshaped from `seaweedfs-harbor`). Pattern from `kubernetes/apps/storage/seaweedfs-config/app/externalsecret.yaml`.
- [ ] **Dependency ordering** in `ks.yaml`: `harbor-config` depends on `harbor` (CRDs); both depend on `cnpg-operator` and `dragonflydb-operator` having reconciled (use `spec.dependsOn` pointing at the operator Kustomizations with `wait: true`).
- [ ] **Tailscale ingress** for `registry.<tailnet-name>.ts.net`. Cluster uses the Tailscale operator per ADR 0012; express this as an `Ingress` annotation or the Tailscale-operator `Connector`/`Service` flavor the cluster already uses elsewhere. Verify the pattern against existing internal Tailscale ingresses in the repo.
- [ ] **First reconcile**: confirm Harbor `HelmRelease` Ready, Postgres `Cluster` 3/3, Dragonfly 3/3, core/portal/registry Ready, jobservice 1/1. Watch `core` logs for S3-backend connection errors on the first push.

### Phase 5 — Node-level integration (Talos + Spegel)

- [ ] **Talos `insecure-registry` patch**. Check current state: was `192.168.1.105` left in `talos/talconfig.yaml` after the cluster reset? If yes, likely still there. If no, re-apply via machine-config patch. Pattern documented in `docs/docs/notes/harbor-registry.md` previous-install section. **Destructive step warning**: this is a Talos machine-config change and goes through `talos-operator` for rolling apply.
- [ ] **Spegel mirror re-enable**. Re-apply the values-diff from commit `4a7cb9ed` (2026-02-11) and the surrounding guardrail commits `12f48802` ("preserve Talos-managed containerd registry mirrors") + `bb2345cc` ("explicitly list registries to prevent Harbor interception"). Do **not** re-apply the strip commit `287a6fa5`. Verify Spegel's current `kubernetes/apps/kube-system/spegel/` values against the reverted commits before committing.
- [ ] Post-patch smoke: `kubectl describe pod <any>` should show the image pulled via the Spegel mirror on a follower node after a leader node first populates it. Spegel exposes metrics for this; alternatively, the peer-pull shows in containerd logs.

### Phase 6 — Smoke test + docs update

- [ ] **Laptop push test**: `docker login registry.<tailnet-name>.ts.net` with the admin robot account; `docker tag busybox registry.<tailnet-name>.ts.net/library/busybox-smoke:v1`; `docker push`. Verify object lands in the SeaweedFS `harbor` bucket: aws-cli pod, `aws --endpoint-url=http://seaweedfs-s3.storage.svc.cluster.local:8333 s3 ls s3://harbor/docker/registry/v2/...` shows the blob.
- [ ] **In-cluster pull test**: create a throwaway namespace + Pod that pulls `192.168.1.105/library/busybox-smoke:v1` without any `imagePullSecret` (anonymous-pull acceptance). Confirm the Pod reaches Running.
- [ ] **Mirror-pull test**: schedule the Pod to a node that was not the first to pull the image; observe Spegel metrics / containerd logs showing peer-pull traffic.
- [ ] **Controlled-reboot test**: drain and reboot the node hosting one of the 2-replica Harbor components; verify registry stays serving (the surviving replica handles traffic). Same drill for a CNPG replica.
- [ ] **Docs update**: rewrite `docs/docs/notes/harbor-registry.md` — drop the "Cluster-Wide Image Pull Configuration" section, add a paragraph on anonymous-pull + the SeaweedFS S3 backend, refresh the endpoint table. Mirror to `harbor-developer-guide.md` (skim for references to Ceph / ImagePullSecret and rewrite).

### Phase 7 — Wrap-up + successor-plan triggers

- [ ] Close this plan Done.
- [ ] **Successor plan (deferred)**: "Harbor Postgres backup strategy." ADR 0015 Consequences flags Harbor's DB as irreplaceable state that becomes more pressing once Harbor lands. Deferred until a backup ADR opens more broadly (the long-outstanding anton backup ADR has been flagged in plan 0001, 0002, 0005 — plan 0006's close is another signal to prioritize it).
- [ ] **Hardening follow-up (optional)**: add a dedicated `harbor` identity in SeaweedFS with bucket-scoped Actions (not Admin) and rotate Harbor's S3 creds to it. Do this when a second SeaweedFS consumer arrives (forces multi-identity anyway) or if an auditor's "Admin for Harbor" finding becomes uncomfortable — whichever first.

## Log

- 2026-04-20: Plan opened as the `Phase 4 — Open successor plan` handoff from plan 0005 (SeaweedFS adoption). SeaweedFS is green on chart 0.1.14 / app 1.0.12; in-cluster S3 target `http://seaweedfs-s3.storage.svc.cluster.local:8333` is the Harbor anchor per ADR 0015 (originally referenced as ADR 0006 before the supersession chain). Admin S3 creds live at Secret `storage/seaweedfs-s3-config` key `s3.json` from 1Password item `seaweedfs-harbor` in vault `anton`. V1 credential scope: reuse admin, defer per-consumer identity to hardening follow-up. Backup strategy explicitly out of scope (separate, long-outstanding ADR).
- 2026-04-21: **Phase 1 task 2 (pre-create `harbor` bucket) — done.** Ran an in-cluster `amazon/aws-cli:2.17.0` pod in namespace `storage` with admin AK/SK sourced from the live `seaweedfs-s3-config` Secret; executed `aws --endpoint-url=http://seaweedfs-s3.storage.svc.cluster.local:8333 s3 mb s3://harbor`. Bucket created, empty contents, `HARBOR_BUCKET_READY` marker fired. Pod auto-deleted.
- 2026-04-21: **Phase 1 task 3 scope shift.** The per-namespace credential mirror that task 3 calls for is now implemented inside the Phase 4 scaffold as `externalsecret-s3.yaml` under `harbor-config/` rather than a separate Phase 1 step. Net effect: task 3 is satisfied by the Phase 4 commit; Phase 1 closed.
- 2026-04-21: **Phase 2 + Phase 3 operator scaffolding — done and deployed.** Created `kubernetes/apps/databases/` namespace with `cloudnative-pg` (chart 0.28.0 via HelmRepository) and `dragonfly-operator` (v1.5.0 via GitRepository). Both Flux Kustomizations Ready within ~25s; both pods Running on k8s-3 (since k8s-2 is still cordoned from plan 0007). CRDs verified Established: `clusters.postgresql.cnpg.io` + siblings, `dragonflies.dragonflydb.io`. Both Kustomizations set `wait: true` so downstream apps can `dependsOn` them. Hook bug fixed in the same commit: `.claude/hooks/check_3_file_pattern.py` now accepts `app/gitrepository.yaml` as a valid chart source alongside OCI and HelmRepository (Flux's HelmRelease has always supported GitRepository sources; the hook simply didn't know). Framing note: both operators are **platform infrastructure** intended for multiple cluster-wide consumers, not Harbor-scoped — Harbor is the first consumer, not the only one.
- 2026-04-21: **Phase 4 scaffolding — done, file-side.** 13 files under `kubernetes/apps/registries/`: namespace + kustomization.yaml, `harbor/` (HelmRelease on chart 1.18.3 bumped from pre-reset 1.16.2 + HelmRepository) and `harbor-config/` (CNPG `Cluster` harbor-postgres 3-rep on Longhorn, DragonflyDB `Dragonfly` harbor-redis 3-rep on Longhorn, two ExternalSecrets, Tailscale Ingress). Key decisions baked in: Harbor chart `trivy.enabled: false` and `jobservice.replicas: 1` (ADR 0015 Consequences, RWX gap); S3 storage driver points at `http://seaweedfs-s3.storage.svc.cluster.local:8333` bucket `harbor` with `disableredirect: true` (SeaweedFS doesn't support pre-signed-URL redirects); `existingSecret` wiring for both admin password (`harbor-admin-secret`, key `HARBOR_ADMIN_PASSWORD`) and S3 creds (`harbor-s3-creds`, keys `REGISTRY_STORAGE_S3_ACCESSKEY` / `REGISTRY_STORAGE_S3_SECRETKEY`); Postgres uses CNPG-generated `harbor-postgres-app` Secret directly; Dragonfly no-auth so only `addr` supplied. Dependency chain: operators → `harbor-config` (`dependsOn` cnpg + dragonfly-operator, `wait: true`) → `harbor` (`dependsOn` harbor-config).
- 2026-04-21: **LB IP conflict discovered and worked around.** Plan 0006 originally called for `192.168.1.105` as the next-free LAN LB IP for Harbor (after `.104` envoy-external). Between plan open and Phase 4 scaffold, plan 0007 Phase 3 (talos-log-sink) claimed `.105` for the Vector aggregator. Harbor moved to `192.168.1.106`; `externalURL` updated to match. Note: if plan 0007 tears down the log-sink in its own Phase 5 (as designed), `.105` will free up but Harbor's pin does not need to migrate back — `.106` is stable.
- 2026-04-21: **Operator action needed before Harbor reconciles Ready.** `externalsecret-admin.yaml` references 1Password vault `anton` item `harbor-admin` field `admin-password`, which does not exist yet. Until created, the `harbor-admin-secret` ExternalSecret stays NotReady → `harbor-config` Kustomization stays NotReady → `harbor` Kustomization waits on its `dependsOn`. The Postgres Cluster + Dragonfly CR + S3 ExternalSecret (reusing `seaweedfs-harbor`) all resolve independently and should come up green once `harbor-config` starts reconciling.

## References

- Anchor decision: [ADR 0015 — Adopt Harbor as the in-cluster image registry](../adrs/0015-adopt-harbor-for-image-registry.md)
- Storage backend: [ADR 0019 — Install SeaweedFS on chart 0.1.14 with canonical `spec.s3`](../adrs/0019-install-seaweedfs-on-chart-0-1-14-canonical-spec-s3.md) + [plan 0005 close-out](./0005-adopt-seaweedfs.md) + [baseline note](../../docs/docs/notes/seaweedfs-baseline-2026-04-19.md)
- Block storage for DB/cache PVCs: [ADR 0005 — Adopt Longhorn as replicated block storage CSI](../adrs/0005-adopt-longhorn-as-block-storage-csi.md)
- Previous install documentation: `docs/docs/notes/harbor-registry.md`, `docs/docs/notes/harbor-developer-guide.md` (both need updating in Phase 6)
- Spegel mirror diff: `jj log` at commits `4a7cb9ed` (mirror config), `12f48802` (preserve Talos registry mirrors), `bb2345cc` (guardrail), `287a6fa5` (the **strip** commit — do not reapply)
- Chart: `goharbor/harbor` (HelmRepository upstream; not published as OCI last time checked — verify at scaffold time)
- Operator charts: `cloudnative-pg/cloudnative-pg`, `dragonflydb/dragonfly-operator`
- Skills to invoke: `add-flux-app` (Phase 2/3/4 scaffolding), `talos-operator` (Phase 5 insecure-registry patch; high-stakes rolling apply), `conventions-linter` (pre-commit on each phase)
- Cluster checks: `flux get hr -A`, `kubectl -n registries get pods`, `kubectl -n storage get seaweed`, `kubectl -n kube-system logs -l app.kubernetes.io/name=spegel`
