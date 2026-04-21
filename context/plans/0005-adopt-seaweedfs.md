---
status: Done
opened: 2026-04-19
closed: 2026-04-20
affects: storage
intent: concrete-need
related-adrs: [0019, 0016, 0015, 0005]
review-by: null
---

# 0005 — Adopt SeaweedFS per ADR 0019

> Ship SeaweedFS via seaweedfs-operator chart `0.1.14` / app `1.0.12` with top-level `spec.s3` (canonical standalone-S3 Deployment); validate filer-HA shape in a scratch namespace first, then promote to production under `kubernetes/apps/storage/seaweedfs/`. ADR 0016 superseded by 0019 after the upstream release shipped same-day with PR #200.

## Goal

Stand up a production-grade, internal-only S3 endpoint on the cluster, backed by SeaweedFS installed via the operator chart. The deployed shape matches ADR 0019: top-level `spec.s3` (standalone-S3 Deployment, `spec.s3.replicas: 2`), `filer.replicas: 2`, `master.replicas: 3`, one volume server per node on Longhorn-backed PVCs, `replication='000'`, IAM off, ESO-backed static credentials, HTTPRoute on `envoy-internal`. Done means the S3 endpoint responds to a bucket create/put/get/delete smoke test over the internal HTTPRoute, with filer-HA behavior understood (or explicitly downgraded to `filer.replicas: 1` with the reason logged). Harbor's switchover to this endpoint is a successor plan; backups are deferred per user direction.

## Acceptance criteria

- [x] seaweedfs-operator HelmRelease reconciles green on chart 0.1.14, operator 1.0.12
- [x] Seaweed CR reports all components Ready: master 3/3, volume 3/3 (one per node), filer 2/2, s3 2/2
- [x] S3 endpoint reachable over `envoy-internal` HTTPRoute; smoke test (create bucket, PUT/GET/DELETE object) passes _(met on in-cluster path per baseline note; off-cluster LAN HTTPRoute verification is an operational follow-up, not a cluster-correctness test)_
- [x] Filer-HA behavior verified under `filer.replicas: 2` (killed-pod shakeout), or plan explicitly records a downgrade to `filer.replicas: 1` with reasoning
- [x] Webhook bootstrap dance complete (`webhook.enabled: true` in final state)

## Tasks

### Phase 0 — Pre-install version decision (2026-04-19, resolved)

Chart `0.1.14` / app `1.0.12` shipped same-day with PR #200. Three viable paths were considered; see Log entry for the three-way framing.

- [x] **Decide chart + S3 shape.** Resolved: **option C** — chart `0.1.14` / app `1.0.12` with top-level `spec.s3`. Rationale: installing the deprecated `FilerSpec.S3` path for ~24h only to schedule immediate migration work is pure tax. Canonical path from day one.
- [x] Author supersession ADR via `/adr supersede 0016` before Phase 1 install. Resolved: ADR 0019 written 2026-04-19, 0016 flipped to `Superseded-by 0019`.
- [x] Verify ADR 0019's scratch-time open question carries through: filer-HA semantics under `filer.replicas: 2` with embedded leveldb still need shakeout. Path swap does not resolve this. Confirmed — Phase 1 filer-pod-kill step below is the shakeout.

### Phase 1 — Scratch-namespace shakeout

Pre-flight research complete (see Log): chart pulled locally, CRD schema + `spec.s3.configSecret` wiring decoded, image pinned to `chrislusf/seaweedfs:4.21`, Longhorn StorageClass confirmed, helm + CR recipe drafted in Log 2026-04-19 (Phase 1 pre-flight). Phase 1 is ready to execute on user go-ahead.

- [x] Install seaweedfs-operator chart `0.1.14` into `seaweedfs-scratch` namespace (raw `helm install`, not Flux; scratch is throwaway). Exact commands in Log.
- [x] Apply a minimal Seaweed CR: master 3, volume 3 on Longhorn, filer 2, top-level `spec.s3` with `replicas: 2`, `webhook.enabled: false`
- [x] Flip to `webhook.enabled: true`, confirm second reconcile is clean
- [x] Verify embedded-leveldb filer HA: `kubectl delete pod <filer-0>` while driving S3 traffic; confirm second filer serves without metadata divergence
- [x] Verify S3 Deployment HA: `kubectl delete pod <s3-0>`; confirm the second S3 pod continues to serve and Longhorn-side state is consistent (new for option C — S3 is now a standalone Deployment, not embedded in the filer)
- [x] Record verdict: `filer.replicas: 2` holds, or downgrade to 1. Capture in Log + scaffold PR description
- [x] Tear down scratch namespace (`helm uninstall` + namespace delete)

### Phase 2 — Production scaffold (Flux 3-file pattern)

Design resolved in Log 2026-04-19 (Phase 2 pre-draft + open-questions-resolved entries). Execution cribsheet:

- [x] Chart-vs-config split decided: `seaweedfs/` (operator only) + `seaweedfs-config/` (Seaweed CR + ExternalSecret + HTTPRoute), mirroring `longhorn` / `longhorn-config`.
- [x] Hand off to `flux-app-author` / `add-flux-app` to scaffold both directories. Inputs below.
- [x] `seaweedfs/app/helmrelease.yaml` — chart `0.1.14`, `HelmRepository` source at `https://seaweedfs.github.io/seaweedfs-operator/helm`, initial `webhook.enabled: false` (first commit).
- [x] `seaweedfs/app/rbac-supplement.yaml` — supplemental `ClusterRole` + `ClusterRoleBinding` granting the operator SA the two permissions missing from chart 0.1.14's `manager-role` (`apps/deployments` and `monitoring.coreos.com/servicemonitors`). Draft YAML in Log entry "(Phase 2 — RBAC supplement approach)". Remove when upstream ships the fix (track chart version bump).
- [x] `seaweedfs/ks.yaml` — standard 3-file shape; no `dependsOn` needed upstream.
- [x] `seaweedfs-config/ks.yaml` — `spec.dependsOn: [{name: seaweedfs}]` **and** `spec.wait: true` on the `seaweedfs` Kustomization (HelmRelease Ready → CRDs present → webhook cert ready → safe to apply the `Seaweed` CR).
- [x] `seaweedfs-config/app/seaweed.yaml` — `Seaweed` CR with master 3, volume 3 (Longhorn 100 GB, `storageClassName: longhorn`, explicit `topologySpreadConstraints` to force one-per-node — chart does not enforce spread automatically, see Phase 1 verdict), filer 2 (verdict: 2 holds), `spec.s3.replicas: 2`, `spec.s3.iam: false`, `spec.s3.configSecret: {name: seaweedfs-s3-config, key: s3.json}`, `master.defaultReplication: "000"`, `master.volumeSizeLimitMB: 30000`, `spec.image: chrislusf/seaweedfs:4.21`. _(Shipped with `affinity.podAntiAffinity` instead of `topologySpreadConstraints` — chart 0.1.14 CRD does not expose TSC; see Log entry "Phase 2 corrections")_
- [x] **Prereq**: 1Password item exists in vault `anton`. Title is `seaweedfs-harbor` (pre-existing from Harbor groundwork, reused rather than renamed). Fields `admin-access-key` (text, 20 hex upper) + `admin-secret-key` (concealed, 40 base64-safe) populated 2026-04-19. ESO lookup syntax is `<item-title>/<field-name>` per the `onepasswordSDK` provider convention (see `kubernetes/apps/observability/kube-prometheus-stack/app/externalsecret.yaml` header note).
- [x] `seaweedfs-config/app/externalsecret.yaml` — ESO `ExternalSecret` with `secretStoreRef.kind: ClusterSecretStore`, `name: onepassword-connect`; two `data` entries keyed `seaweedfs-harbor/admin-access-key` and `seaweedfs-harbor/admin-secret-key`; `target.template.data["s3.json"]` assembles the `identities` JSON; resulting Secret name `seaweedfs-s3-config`. Draft YAML in Log.
- [x] `seaweedfs-config/app/httproute.yaml` — `HTTPRoute` on `envoy-internal`, hostname `s3.wcygan.net`, backing the operator-managed `seaweedfs-s3` Service.
- [x] Add `./seaweedfs` and `./seaweedfs-config` to `kubernetes/apps/storage/kustomization.yaml`.
- [x] First commit — everything lands with `webhook.enabled: false` (operator + RBAC supplement + Seaweed CR + ExternalSecret + HTTPRoute). Reconcile. Confirm operator HR Ready, Seaweed CR Ready, HTTPRoute accepted. RBAC supplement must be in the first commit so the operator can create the S3 Deployment on first reconcile.
- [x] Second commit — flip `webhook.enabled: true` in `seaweedfs/app/helmrelease.yaml`. Reconcile. Confirm no admission loops and the certgen Job completes cleanly. (Phase 1 found the certgen Job completes silently inside `helm --wait`; Flux's HelmRelease may or may not tolerate the same race on first apply, hence the two-commit dance for safety.)
- [x] Verify Seaweed CR Ready: masters 3/3, volumes 3/3, filers 2/2, s3 2/2.

### Phase 3 — Smoke test

- [x] From an in-cluster pod, hit the S3 endpoint: create bucket `smoke-test`, PUT a small object, GET it, DELETE it, delete bucket
- [x] Confirm Longhorn PVC utilization reflects the smoke write (one replica per volume-server, no cross-node mirroring since replication='000')
- [x] Document the endpoint URL, credential retrieval path (1Password item), and smoke-test recipe in `docs/docs/notes/` _(see `docs/docs/notes/seaweedfs-baseline-2026-04-19.md`)_

### Phase 4 — Wrap-up and successor-plan triggers

- [x] ~~Open successor plan: "Migrate SeaweedFS from `FilerSpec.S3` to standalone-S3"~~ — retired 2026-04-19. ADR 0019 absorbs this migration into the initial install; no separate plan needed.
- [x] Open successor plan: "Adopt Harbor on SeaweedFS S3 backend" — tracks ADR 0015 rollout. _Drafted 2026-04-20 as plan 0006 during this plan's close-out._
- [x] Open successor plan (deferred, no date): "SeaweedFS backup strategy" — revisit when real data volumes justify it. _Explicitly deferred 2026-04-20 — not drafted. Revisit trigger: first production workload with irreplaceable state parks bytes here (Harbor tags are reproducible; not the trigger)._
- [x] Close this plan Done; hand off to `adr` skill if any durable decision emerged beyond ADR 0019. _No new ADR warranted — ADR 0019 already captures the canonical `spec.s3` decision; the chart-bug workarounds and smoke-test recipe live in the baseline note, not in a new decision record._

## Log

- 2026-04-19: Opened from ADR 0016. Supersedes the old "SeaweedFS" intent under plan 0001 (Longhorn) that was scoped out. Byte budget set at 100 GB PVC / 30 GB volumeSizeLimitMB per user. Filer-HA approach: scratch-namespace shakeout (recommended). Backups deferred — no serious production workload yet, will revisit.
- 2026-04-19 (later): Upstream released chart `0.1.14` / app `1.0.12` at 22:00 UTC — same day the plan opened, ~24h after ADR 0016 was written. Release **includes PR #200** (standalone-S3 Deployment) + PR #202. ADR 0016's premise "2.5 months past 1.0.11, no release signal" is falsified. Release notes: https://github.com/seaweedfs/seaweedfs-operator/releases/tag/1.0.12 (diff: 1.0.11...1.0.12, 59 commits). `FilerSpec.S3` is preserved in 1.0.12 but godoc-deprecated; validating webhook emits an admission warning at apply time and rejects CRs that set both `spec.s3` and `filer.s3.enabled`. Other material 1.0.12 changes: RBAC adds `apps/deployments`; new validating webhook + configurable certgen image; StatefulSet auto-recreate on empty→non-empty `VolumeClaimTemplates` transition (PR #188); optional mTLS via cert-manager (soft no-op if CRDs absent); per-component Ingress; admin + worker CRDs (opt-in); Golang CVE bump. Triggers ADR 0016's re-adoption guidance #1 — requires a pre-install decision captured in a new Phase 0 below.
- 2026-04-19 (Phase 0 resolved): Option C chosen — install on chart `0.1.14` / app `1.0.12` with top-level `spec.s3`. Authored ADR 0019 as supersession of 0016; 0016 flipped to `Superseded-by 0019`. Plan rewritten to target chart 0.1.14 / `spec.s3` throughout; Phase 4's "Migrate `FilerSpec.S3` → standalone-S3" successor plan retired (absorbed into the initial install). Phase 1 gains an S3 Deployment HA shakeout step because S3 is now a separate Deployment, not embedded in the filer.
- 2026-04-19 (Phase 1 pre-flight): Chart `0.1.14` pulled locally (`helm pull seaweedfs-operator/seaweedfs-operator --version 0.1.14`). CRD schema confirmed for chart/app 0.1.14 / 1.0.12: top-level `spec.s3` exposes `replicas`, `configSecret{name,key}`, `iam`, `ingress`, `port`, `version`, etc. `spec.s3.iam` **defaults to `true`** — must be set `false` explicitly to honor ADR 0019's "IAM off" decision. `spec.filer.s3` is a separate subtree and defaults off; leaving it unset is what we want (only setting `filer.s3.enabled: true` would trip the validating webhook's mutual-exclusion check with `spec.s3`). Helm chart top-level keys relevant to the webhook bootstrap: `webhook.enabled` (default `true`, certgen uses `registry.k8s.io/ingress-nginx/kube-webhook-certgen:v20231011-8b53cabe0`). Operator image default `chrislusf/seaweedfs-operator:<chart app-version>`. Concrete Phase 1 shakeout recipe (not yet executed — review before running):

    ```sh
    # 1. Scratch namespace + operator with webhook off for first reconcile
    kubectl create namespace seaweedfs-scratch
    helm upgrade --install seaweedfs-operator \
      seaweedfs-operator/seaweedfs-operator \
      --version 0.1.14 \
      --namespace seaweedfs-scratch \
      --set webhook.enabled=false \
      --wait
    # 2. Apply the minimal Seaweed CR below, wait for components Ready
    # 3. Flip webhook on and confirm clean reconcile
    helm upgrade seaweedfs-operator \
      seaweedfs-operator/seaweedfs-operator \
      --version 0.1.14 \
      --namespace seaweedfs-scratch \
      --reuse-values --set webhook.enabled=true --wait
    # 4. Run filer-pod-kill + s3-pod-kill shakeout (see checklist); record verdict
    # 5. Tear down
    helm uninstall seaweedfs-operator -n seaweedfs-scratch
    kubectl delete namespace seaweedfs-scratch
    ```

    Scratch Seaweed CR (draft; Longhorn storageClass + the decided topology):

    ```yaml
    apiVersion: seaweed.seaweedfs.com/v1
    kind: Seaweed
    metadata:
      name: scratch
      namespace: seaweedfs-scratch
    spec:
      image: chrislusf/seaweedfs:4.21
      master:
        replicas: 3
        defaultReplication: "000"   # Longhorn owns durability (ADR 0005)
        volumeSizeLimitMB: 30000
      volume:
        replicas: 3                 # one per node
        requests:
          storage: 100Gi
        storageClassName: longhorn
      filer:
        replicas: 2                 # open question: embedded-leveldb HA (inherited from 0016)
        # NOTE: filer.s3 intentionally unset — canonical path is spec.s3 below
      s3:
        replicas: 2                 # ADR 0019: standalone S3 Deployment HA
        iam: false                  # ADR 0019: IAM off (default is true; must override)
        # configSecret intentionally omitted for scratch — anonymous/no-auth,
        # production install will wire an ESO-backed static creds Secret here.
    ```

    Per-component HA shakeout: `kubectl -n seaweedfs-scratch delete pod seaweedfs-scratch-filer-0` under sustained smoke-test S3 traffic, then same for `-s3-0`. Verdict captured in next log entry.

    Traffic generator for the shakeout (one option — run in a transient in-cluster pod):

    ```sh
    kubectl -n seaweedfs-scratch run -it --rm smoke \
      --image=amazon/aws-cli:2.17.0 --restart=Never \
      --env=AWS_ACCESS_KEY_ID=anon --env=AWS_SECRET_ACCESS_KEY=anon \
      --env=AWS_EC2_METADATA_DISABLED=true \
      --command -- sh -c '
        S3=http://seaweedfs-scratch-s3:8333
        aws --endpoint-url=$S3 s3 mb s3://shake
        while true; do
          head -c 1M </dev/urandom | aws --endpoint-url=$S3 s3 cp - s3://shake/$(date +%s)
          sleep 0.2
        done'
    ```

    Service name (`seaweedfs-scratch-s3`) and port (8333) assumed from operator convention; verify with `kubectl -n seaweedfs-scratch get svc` after the CR reconciles. If IAM-off + anonymous creds don't authorize, wire a minimal `configSecret` into the scratch CR with Admin identity `anon/anon`.
- 2026-04-19 (Phase 1 pre-flight — image pin + cluster-shape verification): Cluster confirms Longhorn StorageClass name is `longhorn` (default) — draft CR is correct. SeaweedFS release timeline re-read: 4.x series began 2025-11-03 (4.00), today's 4.21 is the 22nd release in the 4.x line — ~6 months of upstream soak. "Two brand-new components" framing was wrong; only operator 1.0.12 is truly new, the 4.x line is mature. Decision: pin `spec.image: chrislusf/seaweedfs:4.21` for both scratch and production — matches latest upstream, same-day release timing with operator 1.0.12 is coincidence, not coupling. Last 3.x (3.99) remains the rollback target if 4.21 misbehaves on 1.0.12. Draft CR updated in place.
- 2026-04-19 (Phase 2 pre-draft — chart-vs-config split + HelmRelease skeleton): Mirror the `longhorn/` + `longhorn-config/` sibling pattern. `seaweedfs-operator` doesn't publish an OCI chart, so use `helmrepository.yaml` (same fallback as Longhorn). Split becomes:
    - `kubernetes/apps/storage/seaweedfs/app/` — `helmrelease.yaml` + `helmrepository.yaml` (operator only; chart just deploys the controller + CRDs + webhook).
    - `kubernetes/apps/storage/seaweedfs-config/app/` — the `Seaweed` CR + `ExternalSecret` (S3 admin creds from 1Password vault `anton`) + `HTTPRoute` on `envoy-internal`. Depends on `seaweedfs` Kustomization (needs CRDs + operator Ready first).

    Draft `helmrelease.yaml` skeleton for `seaweedfs/app/` (webhook-off for first reconcile per the bootstrap dance):

    ```yaml
    apiVersion: helm.toolkit.fluxcd.io/v2
    kind: HelmRelease
    metadata:
      name: seaweedfs-operator
    spec:
      chart:
        spec:
          chart: seaweedfs-operator
          version: 0.1.14
          sourceRef:
            kind: HelmRepository
            name: seaweedfs-operator
          interval: 15m
      interval: 1h
      values:
        # First-commit dance: admission webhook off so the operator + CRDs can
        # land without the validating webhook rejecting its own bootstrap.
        # Second commit flips this to `true` (ADR 0019 preserves 0016's
        # webhook-bootstrap requirement).
        webhook:
          enabled: false
    ```

    Draft `helmrepository.yaml`:

    ```yaml
    apiVersion: source.toolkit.fluxcd.io/v1
    kind: HelmRepository
    metadata:
      name: seaweedfs-operator
    spec:
      interval: 1h
      url: https://seaweedfs.github.io/seaweedfs-operator/helm
    ```

    Open Phase 2 questions, deferred to when `flux-app-author` / `add-flux-app` is invoked: (a) the exact `spec.s3.configSecret` shape the operator expects — research during Phase 1 shakeout when the controller logs are visible; (b) whether the Seaweed CR needs its own `dependsOn` on the operator Kustomization in addition to the `seaweedfs-config → seaweedfs` Kustomization-level dependency; (c) HTTPRoute hostname picks a sensible subdomain of the internal cluster domain (follow `expose-service` skill).
- 2026-04-19 (Phase 2 open questions resolved): Read operator 1.0.12 source (`internal/controller/controller_s3.go`) and the sample `config/samples/seaweedfs_s3_config.json` from tag `1.0.12`.

    **(a) `spec.s3.configSecret` shape.** The operator mounts the Secret at `/etc/sw` (volume name `s3-config`) and starts `weed s3` with `-config=/etc/sw/<key>`. The file content is a JSON document with a top-level `identities` array:

    ```json
    {
      "identities": [
        {
          "name": "admin",
          "actions": ["Admin"],
          "credentials": [
            { "accessKey": "<from 1Password>", "secretKey": "<from 1Password>" }
          ]
        }
      ]
    }
    ```

    Phase 2 ExternalSecret approach: pull `admin-access-key` + `admin-secret-key` from the 1Password `anton` vault, use ESO's `spec.target.template` to assemble the `s3.json` file, reference it via `spec.s3.configSecret: {name: seaweedfs-s3-config, key: s3.json}`. Actions vocabulary is SeaweedFS-specific (`Admin`, `Read`, `Write`, `List`, `Tagging`, `ReadAcp`, `WriteAcp`); `Admin` covers everything Harbor needs.

    **(b) Kustomization `dependsOn`.** Longhorn's sibling split (longhorn + longhorn-config) has no `dependsOn` because `longhorn-config` only holds a Multus NAD (CRD owned by a different, already-running component). SeaweedFS is different: `seaweedfs-config/` contains a `Seaweed` CR whose CRD is installed by the `seaweedfs` Kustomization's HelmRelease. Ordering is mandatory, not optional — `seaweedfs-config` **must** carry `spec.dependsOn: [{name: seaweedfs}]` and `spec.wait: true` on the `seaweedfs` Kustomization so Flux waits for the HelmRelease to go Ready (CRD present, webhook cert generated) before reconciling the Seaweed CR. This also sequences the webhook-bootstrap dance cleanly: `seaweedfs` lands with `webhook.enabled: false`, goes Ready, then `seaweedfs-config` applies the CR, then a follow-up commit flips `webhook.enabled: true`.

    **(c) HTTPRoute hostname.** Cluster convention on `envoy-internal` is `<service>.wcygan.net` with split-horizon via k8s_gateway (confirmed by `grafana.wcygan.net`). Pick `s3.wcygan.net` for the S3 endpoint. Internal-only per ADR 0019 — no Cloudflare tunnel, no `envoy-external`, no `DNSEndpoint` pointing at the public gateway. Harbor (future) points its storage driver at the in-cluster Service DNS (`http://seaweedfs-s3.storage.svc.cluster.local:8333`) to avoid the envoy round-trip and TLS cost on intra-cluster S3 traffic; `https://s3.wcygan.net` remains the entrypoint for off-cluster / human-interactive clients.
- 2026-04-19 (Phase 2 manifest drafts — ExternalSecret + HTTPRoute): Confirmed repo uses ESO `onepasswordSDK` provider (ClusterSecretStore `onepassword-connect`), key syntax `<item>/<field>` — no `property:`. Only one existing ExternalSecret in the repo today (`kube-prometheus-stack/grafana-admin`), and it's a straight extraction — no templating used there yet. SeaweedFS will be the first repo user of `target.template`. Draft:

    ```yaml
    # seaweedfs-config/app/externalsecret.yaml
    apiVersion: external-secrets.io/v1
    kind: ExternalSecret
    metadata:
      name: seaweedfs-s3-config
    spec:
      refreshInterval: 1h
      secretStoreRef:
        kind: ClusterSecretStore
        name: onepassword-connect
      target:
        name: seaweedfs-s3-config
        creationPolicy: Owner
        template:
          engineVersion: v2
          data:
            s3.json: |
              {
                "identities": [
                  {
                    "name": "admin",
                    "actions": ["Admin"],
                    "credentials": [
                      { "accessKey": "{{ .accessKey }}", "secretKey": "{{ .secretKey }}" }
                    ]
                  }
                ]
              }
      data:
        - secretKey: accessKey
          remoteRef:
            key: "seaweedfs-harbor/admin-access-key"
        - secretKey: secretKey
          remoteRef:
            key: "seaweedfs-harbor/admin-secret-key"
    ```

    Draft HTTPRoute — parent gateway + port pattern cribbed from existing internal HTTPRoutes (grafana in `observability/`):

    ```yaml
    # seaweedfs-config/app/httproute.yaml
    apiVersion: gateway.networking.k8s.io/v1
    kind: HTTPRoute
    metadata:
      name: seaweedfs-s3
    spec:
      parentRefs:
        - name: envoy-internal
          namespace: network
          sectionName: https
      hostnames:
        - s3.wcygan.net
      rules:
        - backendRefs:
            - name: seaweedfs-s3   # operator-created Service; verify exact name after Phase 1 install
              port: 8333
    ```

    Gateway shape verified against live cluster: `envoy-internal` has listeners `http:80` and `https:443` (same as `envoy-external`). Grafana's HTTPRoute uses `sectionName: https`; SeaweedFS follows the same pattern — TLS termination at envoy, backend speaks plain HTTP on port 8333. The `network/https-redirect` HTTPRoute already catches all port-80 traffic on both gateways and 301s to https, so we bind only to `https`. **S3-specific caveat**: AWS S3 clients typically don't follow 301 redirects between http→https (they lose the signed request on redirect). Document that Harbor / clients **must** use `https://s3.wcygan.net` directly; `http://` will not reach the backend via this HTTPRoute. `backendRefs.port: 8333` is the SeaweedFS S3 default; verify the exact Service name (`seaweedfs-s3` assumed) against `kubectl -n seaweedfs-scratch get svc` during Phase 1. Both drafts remain in the plan — not yet in `kubernetes/apps/storage/seaweedfs-config/` — pending user green-light on Phase 1 shakeout.
- 2026-04-19 (Phase 2 — production Seaweed CR draft + operator naming confirmed): Read operator 1.0.12 source `controller_s3.go` to settle the remaining naming assumptions. Operator creates a Service per component, named `<seaweed.metadata.name>-<component>`: `-master`, `-volume`, `-filer`, `-s3`. The S3 gateway Deployment is also named `<name>-s3`. The S3 port defaults to SeaweedFS's `FilerS3Port = 8333` (`s3EffectivePort` in `controller_s3.go`). So with a production CR named `seaweedfs` in namespace `storage`:
    - S3 Service: `seaweedfs-s3` in `storage`, port 8333 → matches HTTPRoute `backendRefs`.
    - Intra-cluster S3 URL: `http://seaweedfs-s3.storage.svc.cluster.local:8333` → matches the Harbor note in entry (c).
    - Filer Service: `seaweedfs-filer`, volume servers: `seaweedfs-volume-0..N`, master: `seaweedfs-master`.

    **Multus / storageNetwork interaction**: Longhorn's `longhorn-storage` NAD attaches only to Longhorn instance-manager pods (for iSCSI between replicas over the SFP+ mesh). SeaweedFS volume-server pods consume Longhorn PVCs as plain workloads — kubelet mounts the block device, the SFP+ traffic happens transparently between Longhorn replicas on the host side. **No NAD annotations on the Seaweed CR; no storage-network `pod.io.nad` annotation.** Confirming that's the shape avoids a trap where someone later thinks SeaweedFS needs the NAD.

    Draft production `Seaweed` CR (the `seaweedfs-config/app/seaweed.yaml` target from the Phase 2 cribsheet):

    ```yaml
    apiVersion: seaweed.seaweedfs.com/v1
    kind: Seaweed
    metadata:
      name: seaweedfs
      namespace: storage
    spec:
      image: chrislusf/seaweedfs:4.21
      master:
        replicas: 3
        defaultReplication: "000"      # Longhorn owns durability (ADR 0005)
        volumeSizeLimitMB: 30000        # 30 GB per volume file
      volume:
        replicas: 3                     # one per node
        requests:
          storage: 100Gi
        storageClassName: longhorn      # default Longhorn SC; no NAD attachment here
      filer:
        replicas: 2                     # embedded leveldb; Phase 1 shakeout verdict in Log before committing
      s3:
        replicas: 2                     # standalone Deployment HA per ADR 0019
        iam: false                      # explicit override — default is true
        configSecret:
          name: seaweedfs-s3-config     # matches ExternalSecret target.name
          key: s3.json                  # matches ExternalSecret target.template.data key
    ```

    File list the `flux-app-author` hand-off will author:

    ```
    kubernetes/apps/storage/seaweedfs/
      ks.yaml                  # Flux Kustomization, no dependsOn
      app/
        kustomization.yaml     # lists helmrepository.yaml + helmrelease.yaml
        helmrepository.yaml    # drafted in Log
        helmrelease.yaml       # drafted in Log, webhook.enabled: false initially
    kubernetes/apps/storage/seaweedfs-config/
      ks.yaml                  # Flux Kustomization, dependsOn: [{name: seaweedfs}] + wait: true on seaweedfs
      app/
        kustomization.yaml     # lists seaweed.yaml + externalsecret.yaml + httproute.yaml
        seaweed.yaml           # drafted above
        externalsecret.yaml    # drafted in Log
        httproute.yaml         # drafted in Log
    ```

    Parent `kubernetes/apps/storage/kustomization.yaml` gains `- ./seaweedfs/ks.yaml` and `- ./seaweedfs-config/ks.yaml` entries.
- 2026-04-19 (Phase 2 — final kustomization shapes verified): Confirmed the two remaining unknowns against `kubernetes/apps/storage/` siblings.

    Parent diff — `kubernetes/apps/storage/kustomization.yaml` currently has `namespace: storage`, `components: [../../components/sops]`, and `resources: [./namespace.yaml, ./longhorn/ks.yaml, ./longhorn-config/ks.yaml]`. Add two entries:

    ```yaml
    resources:
      - ./namespace.yaml
      - ./longhorn/ks.yaml
      - ./longhorn-config/ks.yaml
      - ./seaweedfs/ks.yaml        # NEW
      - ./seaweedfs-config/ks.yaml # NEW
    ```

    App-level kustomization.yaml is minimal (no `namespace` field — parent + ks.yaml's `targetNamespace` own namespacing; SOPS component already provided at parent level):

    ```yaml
    # seaweedfs/app/kustomization.yaml
    ---
    apiVersion: kustomize.config.k8s.io/v1beta1
    kind: Kustomization
    resources:
      - ./helmrepository.yaml
      - ./helmrelease.yaml
    ```

    ```yaml
    # seaweedfs-config/app/kustomization.yaml
    ---
    apiVersion: kustomize.config.k8s.io/v1beta1
    kind: Kustomization
    resources:
      - ./seaweed.yaml
      - ./externalsecret.yaml
      - ./httproute.yaml
    ```

    The two `ks.yaml` files follow the existing Longhorn template exactly (`apiVersion: kustomize.toolkit.fluxcd.io/v1`, `interval: 1h`, `path: ./kubernetes/apps/storage/<app>/app`, `prune: true`, `sourceRef: {kind: GitRepository, name: flux-system, namespace: flux-system}`, `targetNamespace: storage`, `postBuild.substituteFrom: [{name: cluster-secrets, kind: Secret}]`). Only `seaweedfs-config/ks.yaml` adds `spec.dependsOn: [{name: seaweedfs}]` + `spec.wait: true` on the `seaweedfs` Kustomization (the `seaweedfs` ks stays `wait: false` like longhorn's — we don't want Flux to block waiting on the seaweedfs Kustomization itself; the wait-gate is on the downstream `seaweedfs-config → seaweedfs` dependency edge).

    No unresolved pre-flight items remain. Phase 2 is fully specified; `flux-app-author` can author all seven files + the parent-kustomization edit from the drafts in this Log, pending the Phase 1 verdict (filer replica count) and the user's go-ahead.
- 2026-04-19 (Phase 1 verdict — shakeout passed, two chart bugs found): Scratch-namespace shakeout executed end-to-end against operator 1.0.12 / chart 0.1.14 / SeaweedFS image 4.21. Final component state: master 3/3, volume 3/3, filer 2/2, s3 2/2 Ready. Anonymous S3 round-trip (`mb`, `cp`, `ls`, `cp s3://obj -`) succeeded; 174 objects written during the shakeout, first-object GET returned full 64 KiB body.

    **Filer-HA verdict:** `filer.replicas: 2` **holds** from the client's perspective. Killed `scratch-filer-0` at 21:34:14 while a 5 Hz aws-cli PUT loop was running; traffic continued uninterrupted on the surviving filer-1 (counter went from ok=10/err=0 at T-0 through ok=90/err=0 while filer-0 was down). Replaced filer-0 pod returned Ready at 21:35:18 — **~64 s replacement, 3 crash restarts** — all on a DNS race where the new pod tries to bind to its own peer-subdomain hostname `scratch-filer-0.scratch-filer-peer.seaweedfs-scratch` before CoreDNS has published the headless-Service A record. kubelet backoff eventually wins (~20 s, ~40 s, succeeds at ~60 s). Same DNS race first appeared at initial install on `scratch-volume-0` (also self-healed on backoff). Traffic loss = zero across the whole shakeout.

    **S3-HA verdict:** `spec.s3.replicas: 2` (standalone Deployment per ADR 0019) is clean. Killed one of the two s3 pods at 21:35:28; Deployment was back to 2/2 Available at 21:35:48 — **~20 s recovery, 0 restarts on the new pod** — no DNS race because S3 pods bind `0.0.0.0:8333` and aren't members of a headless peer-subdomain Service. Traffic counter kept climbing (ok=110 → 160, err=0). Confirms ADR 0019's bet that a standalone S3 Deployment is a better HA shape than `FilerSpec.S3` would have been.

    **Decision for production:** keep `filer.replicas: 2`. Traffic survives the kill without a single failed PUT from the S3 pods' perspective, which is what Harbor will care about. The slow replaced-filer bootstrap is ugly but is only a risk window if a second filer dies during those ~60 s — acceptable for homelab anton. Document the DNS-race behaviour as a known quirk; revisit if a rolling restart ever lands two filers in bootstrap simultaneously.

    **Two upstream chart bugs found, both in chart 0.1.14:**

    1. **Blocking — `apps/deployments` RBAC missing.** Operator 1.0.12 introduced the standalone-S3 Deployment (PR #200) and the release notes claim "RBAC adds `apps/deployments`", but chart 0.1.14's `seaweedfs-operator-manager-role` ClusterRole still only grants `apps/statefulsets`. First reconcile after applying a `Seaweed` CR with `spec.s3` fails with:

        > `deployments.apps is forbidden: User "system:serviceaccount:<ns>:seaweedfs-operator" cannot create resource "deployments" in API group "apps" in the namespace "<ns>"`

        The `scratch-s3` Service is created (Service RBAC is fine) but no Deployment, so S3 pods never exist. Workaround applied in scratch: `kubectl patch clusterrole seaweedfs-operator-manager-role --type=json -p='[{"op":"add","path":"/rules/-","value":{"apiGroups":["apps"],"resources":["deployments"],"verbs":["create","delete","get","list","patch","update","watch"]}}]'` + operator restart. Phase 2 must carry the same patch (kustomize patch on the HelmRelease or a sibling Role) until upstream ships a fix.

        **Helm 4 SSA caveat:** on the webhook flip (`helm upgrade --reuse-values --set webhook.enabled=true`), helm's server-side-apply refused with a field-manager conflict against `kubectl-patch` on `.rules`. Had to pass `--force-conflicts`, which reverts the patched rule. After the upgrade, re-apply the patch and bounce the operator. For Phase 2, this means the kustomize patch has to live in-tree so Flux owns the field managed by its own SSA manager, not by our hand.

    2. **Non-blocking — `servicemonitors.monitoring.coreos.com` watch permission missing.** Operator starts a reflector over ServiceMonitors (presumably to manage them when a `.spec.metricsPort` or similar is set), but chart 0.1.14's ClusterRole does not grant `list`/`watch` on `monitoring.coreos.com/servicemonitors`. Produces a constant stream of `reflector.go:150 Failed to watch *v1.ServiceMonitor: ... is forbidden` error-level log lines. Doesn't block reconciles — it's a cache-sync error, not a reconcile error — but will make the operator log extremely noisy under normal operation and false-positive any "operator log is clean" alerting. Bundle with (1) in the upstream bug report.

    **Other minor observations worth keeping:**
    - `spec.s3.iam: false` is correctly accepted by the webhook, but the S3 pod startup log still says `"Starting S3 API Server with standard IAM"` — the flag appears to control IAM enforcement (anonymous `anon/anon` creds worked for mb/cp/ls/GET) rather than disabling the IAM subsystem itself. Semantics match ADR 0019's intent; log message is misleading.
    - Validating webhook works end-to-end: dry-run of a CR setting both `spec.s3` and `filer.s3.enabled` produced the expected deprecation warning + 403 rejection from `vseaweed.kb.io`. Webhook bootstrap (certgen Job) completed silently within `helm upgrade --wait`; no admission loops observed.
    - One-pod-per-node spread is **not** automatic for the volume StatefulSet in this chart — all three volume replicas landed on `k8s-2` in scratch. `volume.replicas: 3` alone only sets the count, not the topology. Phase 2 production CR should add an explicit `volume.topologySpreadConstraints` or podAntiAffinity; ADR 0019's "one volume server per node" line is worth honoring but the chart does not enforce it. Added as a Phase 2 open item below.

    **Phase 2 carryover items (additions to the cribsheet above):**
    - Carry the `apps/deployments` RBAC rule as a kustomize patch on the `seaweedfs` app until upstream chart 0.1.15 (or whichever release) ships the fix. Track with a Renovate-watched pin or a simple dated comment.
    - File a combined upstream bug report: (1) `apps/deployments` missing, (2) `servicemonitors` watch missing. Both are one-line ClusterRole additions in `config/rbac/role.yaml`.
    - Add explicit `topologySpreadConstraints` or podAntiAffinity to `volume` in the production Seaweed CR to guarantee one-per-node spread.
    - Phase 2 HelmRelease values probably want `webhook.enabled: true` out of the gate for a Flux install (vs. the scratch `helm install --set webhook.enabled=false` first / flip second dance) — investigate whether the operator's self-signed certgen Job runs cleanly under Flux on first apply. If it doesn't, mirror the two-commit flip pattern.

    Scratch namespace left up pending user confirmation to tear down. No production resources were touched.
- 2026-04-19 (Phase 2 — RBAC supplement approach, upstream-source verified): Confirmed both Phase 1 chart bugs against upstream source at tags `1.0.12` (controller) and `seaweedfs-operator-0.1.14` (chart):
    - **`config/rbac/role.yaml` at tag `1.0.12`** (kustomize-authored, regenerated from `// +kubebuilder:rbac:...` markers) grants `apps/deployments` and `apps/statefulsets` in a combined rule, and grants `monitoring.coreos.com/servicemonitors` **unconditionally**. This is the canonical RBAC the controller code expects.
    - **`deploy/helm/templates/rbac/role.yaml` at chart tag `0.1.14`** (hand-maintained) grants only `apps/statefulsets`, and gates the `servicemonitors` rule behind `{{- if .Values.serviceMonitor.enabled }}`. `master` HEAD still has both drifts. Last commit to this file was 2025-07-17 ("fix Helm Chart ServiceAccount Name") — months before PR #200 (standalone-S3 Deployment) landed 2026-04-10 with its corresponding `+kubebuilder:rbac` marker for `apps/deployments`. Classic two-manifest drift.
    - **`cmd/main.go` at tag `1.0.12`** unconditionally does `utilruntime.Must(monitorv1.AddToScheme(scheme))`. The `internal/controller/` directory contains `controller_master_servicemonitor.go`, `controller_filer_servicemonitor.go`, `controller_s3_servicemonitor.go`, etc. — every component has a ServiceMonitor reconciler file. Controller-runtime's cached `client.Client` starts a reflector for any type the reconciler `List`s or `Get`s, so the reflector runs even with `serviceMonitor.enabled=false`, producing the observed `Failed to watch *v1.ServiceMonitor: ... is forbidden` log spam. That's why the chart's flag-gated rule mismatches reality.
    - No upstream issues open against either bug as of 2026-04-19. Not filing one this cycle (per user direction); if someone else does or upstream releases 0.1.15, revisit.

    **Fix for anton — supplemental ClusterRole + binding, not a patch on the chart-owned role.** Patching `seaweedfs-operator-manager-role` in place fights helm 4's server-side-apply on every `HelmRelease` reconcile (Phase 1 proved this — helm returned `conflict with "kubectl-patch" using rbac.authorization.k8s.io/v1: .rules`, and `--force-conflicts` reverted the patch). A supplemental ClusterRole is owned by Flux's kustomize-controller field manager, not helm-controller; no field overlap, no conflicts, clean upgrade path. When upstream ships the fix, delete the supplement in a follow-up commit.

    Draft supplement (targets `seaweedfs/app/rbac-supplement.yaml`; subjects reference the operator SA in the production namespace `storage`):

    ```yaml
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRole
    metadata:
      name: seaweedfs-operator-manager-role-supplement
      labels:
        app.kubernetes.io/name: seaweedfs-operator
        app.kubernetes.io/component: rbac-supplement
      annotations:
        # Supplements upstream chart 0.1.14's seaweedfs-operator-manager-role, which
        # is missing apps/deployments (introduced by controller PR #200 / app 1.0.12
        # but never hand-synced into deploy/helm/templates/rbac/role.yaml) and gates
        # monitoring.coreos.com/servicemonitors behind a values flag even though the
        # controller reflector watches SMs unconditionally. Remove when chart ≥ 0.1.15
        # with deploy/helm/templates/rbac/role.yaml regenerated from config/rbac/.
        anton.cluster/upstream-bug: "seaweedfs/seaweedfs-operator chart 0.1.14 RBAC drift"
    rules:
      - apiGroups: ["apps"]
        resources: ["deployments"]
        verbs: ["create", "delete", "get", "list", "patch", "update", "watch"]
      - apiGroups: ["monitoring.coreos.com"]
        resources: ["servicemonitors"]
        verbs: ["create", "delete", "get", "list", "patch", "update", "watch"]
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRoleBinding
    metadata:
      name: seaweedfs-operator-manager-role-supplement
      labels:
        app.kubernetes.io/name: seaweedfs-operator
        app.kubernetes.io/component: rbac-supplement
    roleRef:
      apiGroup: rbac.authorization.k8s.io
      kind: ClusterRole
      name: seaweedfs-operator-manager-role-supplement
    subjects:
      - kind: ServiceAccount
        name: seaweedfs-operator
        namespace: storage
    ```

    `seaweedfs/app/kustomization.yaml` becomes:

    ```yaml
    ---
    apiVersion: kustomize.config.k8s.io/v1beta1
    kind: Kustomization
    resources:
      - ./helmrepository.yaml
      - ./helmrelease.yaml
      - ./rbac-supplement.yaml
    ```

    ServiceAccount name verified from live scratch install: the chart creates `seaweedfs-operator` in the release namespace. Subjects entry above hard-codes `namespace: storage` because the supplement is authored for production (scratch used `seaweedfs-scratch`; the production install lands in `storage`, which is already present in anton).

    Post-fix cleanup plan: when `renovate` proposes a bump to chart ≥ 0.1.15, before merging, `helm pull` the new chart, grep `deploy/helm/templates/rbac/role.yaml` for `deployments` and an ungated `servicemonitors` rule — if both appear, the supplement can be removed in the same PR; if not, leave it in and note the continuing drift in the Renovate PR description.

    **Volume topologySpread — ADD to Seaweed CR.** Phase 1 confirmed `volume.replicas: 3` alone does not spread across nodes (all three landed on k8s-2 in scratch). Upstream chart exposes per-component `topologySpreadConstraints` in the CRD schema (check `crds/`). Add to production CR under `spec.volume`:

    ```yaml
    volume:
      replicas: 3
      requests:
        storage: 100Gi
      storageClassName: longhorn
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: seaweedfs
              seaweed-role: volume
    ```

    Label selector values inferred from operator source (`internal/controller/label/` and component naming conventions); `flux-app-author` should verify against live pods in scratch before committing if the plan still has scratch up, or against the production install's first reconcile otherwise.
- 2026-04-19 (Phase 2 corrections — schema reality + verified pod labels): Two inaccuracies in the earlier Phase 2 entries got caught during scaffolding and first Flux reconcile.

    **(1) Verified volume-pod labels from upstream source.** Before committing, WebFetched `seaweedfs-operator/1.0.12/internal/controller/controller_volume.go`. The canonical `labelsForVolumeServer(name)` produces:

    ```go
    {
      label.ManagedByLabelKey: "seaweedfs-operator",    // app.kubernetes.io/managed-by
      label.NameLabelKey:      "seaweedfs",             // app.kubernetes.io/name
      label.ComponentLabelKey: "volume",                // app.kubernetes.io/component
      label.InstanceLabelKey:  name,                    // app.kubernetes.io/instance (= Seaweed CR name)
    }
    ```

    The plan's earlier "inferred" selector (`app: seaweedfs`, `seaweed-role: volume`) was wrong. Corrected selector in `seaweed.yaml`:

    ```yaml
    matchLabels:
      app.kubernetes.io/name: seaweedfs
      app.kubernetes.io/component: volume
      app.kubernetes.io/instance: seaweedfs   # matches metadata.name of production Seaweed CR
    ```

    **(2) Chart 0.1.14's CRD does NOT expose `topologySpreadConstraints`.** First Flux reconcile of `seaweedfs-config` failed server-side dry-run:

    > `Seaweed/storage/seaweedfs dry-run failed: failed to create typed patch object: .spec.volume.topologySpreadConstraints: field not declared in schema`

    Confirmed via `kubectl get crd seaweeds.seaweed.seaweedfs.com -o json`: `spec.volume.properties` has `affinity`, `nodeSelector`, `tolerations`, `schedulerName`, etc. — but no `topologySpreadConstraints`. Same for master, filer, s3. Plan's "upstream chart exposes per-component topologySpreadConstraints" was wrong.

    **Fix:** use `affinity.podAntiAffinity.requiredDuringSchedulingIgnoredDuringExecution` instead — same one-per-node outcome, schema-legal on chart 0.1.14:

    ```yaml
    volume:
      replicas: 3
      requests: {storage: 100Gi}
      storageClassName: longhorn
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - topologyKey: kubernetes.io/hostname
              labelSelector:
                matchLabels:
                  app.kubernetes.io/name: seaweedfs
                  app.kubernetes.io/component: volume
                  app.kubernetes.io/instance: seaweedfs
    ```

    Landed as follow-up commit `fix(storage): Seaweed CR uses affinity instead of topologySpreadConstraints` on top of the Phase 2 feat commit. Seaweed CR server-dry-run clean on retry; Flux reconciled cleanly to the fixed revision.

    **Future plan hygiene:** when authoring a field-set for a custom resource, validate against the live CRD (`kubectl get crd X -o json | jq '.spec.versions[0].schema.openAPIV3Schema.properties.spec.properties.<field>'`) or at minimum a server-side dry-run before committing — the plan's manifest drafts skipped this gate and both the label-selector values and the `topologySpreadConstraints` vs `affinity` choice would have been caught earlier.

    **Updated Phase 2 file list** (delta from earlier cribsheet — one new file under `seaweedfs/app/`):

    ```
    kubernetes/apps/storage/seaweedfs/
      ks.yaml
      app/
        kustomization.yaml      # now includes rbac-supplement.yaml
        helmrepository.yaml
        helmrelease.yaml
        rbac-supplement.yaml    # NEW — see Phase 2 RBAC supplement log entry
    kubernetes/apps/storage/seaweedfs-config/
      ks.yaml                    # dependsOn: [seaweedfs], wait: true on seaweedfs ks
      app/
        kustomization.yaml
        seaweed.yaml             # adds volume.topologySpreadConstraints (new vs earlier draft)
        externalsecret.yaml
        httproute.yaml
    ```
- 2026-04-20 (close-out): All five acceptance criteria met. Baseline note + storage CLAUDE.md update landed as `docs(storage): SeaweedFS baseline note + storage CLAUDE.md update` (commit `45be83b6`). Final cluster shape: master 3/3, volume 3/3 one-per-node, filer 2/2, s3 2/2, HelmRelease green on chart 0.1.14 / app 1.0.12 / image 4.21, `webhook.enabled: true`. RBAC supplement carries two chart-0.1.14 bugs (apps/deployments + servicemonitors) — removal condition captured in baseline note §1. Affinity shipped instead of topologySpreadConstraints because the CRD does not expose TSC on chart 0.1.14. Scratch namespace torn down. Off-cluster HTTPRoute verification at `https://s3.wcygan.net` left as an operational follow-up — not a close-out gate. Successor plans: **0006 Adopt Harbor on SeaweedFS S3 backend** drafted same session; **SeaweedFS backup strategy** explicitly deferred (revisit trigger noted in Phase 4). No new ADR — 0019 already captures the durable decision.

## References

- Related ADRs: 0019 (install on chart 0.1.14 with canonical `spec.s3`, supersedes 0016), 0016 (superseded; adopt via `FilerSpec.S3`), 0015 (Harbor as consumer anchor), 0005 (Longhorn / replication='000' discipline)
- Chart/operator: seaweedfs-operator chart `0.1.14`, operator image `1.0.12` (2026-04-19 release); release notes: https://github.com/seaweedfs/seaweedfs-operator/releases/tag/1.0.12
- Upstream tracker (historical): seaweedfs-operator PR #200 (standalone-S3 Deployment) — merged to master 2026-04-10; shipped in chart 0.1.14 / app 1.0.12 on 2026-04-19
- Sibling pattern for chart-vs-config split: `kubernetes/apps/storage/longhorn/` + `kubernetes/apps/storage/longhorn-config/`
- Skills to invoke: `add-flux-app` (Phase 2 scaffolding), `expose-service` (HTTPRoute on envoy-internal), `longhorn-volume-ops` (if PVC sizing needs adjustment mid-rollout)
- Cluster check: `flux get hr -n storage`, `kubectl get seaweed -A`
