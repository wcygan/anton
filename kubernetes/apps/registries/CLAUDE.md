# kubernetes/apps/registries/

Harbor OCI registry (ADR 0015 / plan 0006), backed by SeaweedFS S3 object storage (ADR 0019 / plan 0005). Namespace `registries` — name deliberately plural so future registries (Helm chart repo, artifact repo) can live alongside Harbor without namespace sprawl.

## Contents

- `harbor/` — the Harbor HelmRelease itself (chart `goharbor/harbor` 1.18.x via `HelmRepository` — no upstream OCI chart last checked). HelmRelease-only app; the Postgres/Dragonfly/Secret/ingress resources live in the sibling `harbor-config/` because they need to reconcile against CRDs in the `databases` namespace operators.
- `harbor-config/` — `Cluster` CR `harbor-postgres` (3 replicas on Longhorn), `Dragonfly` CR `harbor-redis` (3 replicas, no auth), two `ExternalSecret`s (admin password + S3 creds), and the Tailscale `Ingress` for `registry.<tailnet>.ts.net`.

Dependency chain: `databases/cloudnative-pg` + `databases/dragonfly-operator` → `registries/harbor-config` (`dependsOn` both, `wait: true`) → `registries/harbor` (`dependsOn` harbor-config). **Direction matters**: `harbor` depends on `harbor-config`, not the reverse — Harbor's chart needs the CNPG `Cluster`, Dragonfly CR, and the two Secrets to exist before it can install.

## Load-bearing decisions

- **LB IP `192.168.1.106`.** Plan 0006 originally called for `.105` but plan 0007 (talos-log-sink) claimed it first. `.106` is the stable pin; `externalURL: http://192.168.1.106` matches. Pool definition in `kubernetes/apps/kube-system/cilium/app/networks.yaml`.
- **`http://` externalURL.** Docker's WWW-Authenticate token realm uses the `externalURL` literally. Historically HTTPS here breaks auth redirects for containerd-on-Talos pulls (pre-reset incident). The Tailscale ingress at `registry.<tailnet-name>.ts.net` is the HTTPS path for browsers and remote push; internal workloads use the LB IP.
- **S3 backend, not PVC.** `persistence.imageChartStorage.type: s3`, endpoint `http://seaweedfs-s3.storage.svc.cluster.local:8333`, bucket `harbor`. **`disableredirect: true` is required** — SeaweedFS does not support the pre-signed-URL redirects that MinIO does, so the registry proxies blob downloads itself. If this flag comes off, large-image pulls will 500 intermittently.
- **`jobservice.replicas: 1`** (not 2). ADR 0015 Consequences — without a replicated RWX filesystem, the jobservice log PVC can't be shared across replicas. Longhorn RWO + single replica. Scaling beyond 1 requires an RWX plan.
- **Trivy disabled.** `trivy.enabled: false` per ADR 0015. Re-enabling requires deciding where vuln DB + scan reports live.
- **`library` project is anonymous-pull.** Set post-install via `PUT /api/v2.0/projects/1 {metadata.public: true}` — not configurable via chart values. For private projects, create a robot account scoped to that project and distribute its token via an ExternalSecret of kind `kubernetes.io/dockerconfigjson`. **Don't** commit per-namespace `docker-registry` Secrets to Git.

## Credentials

| Secret | Kind | Source | Used by |
|---|---|---|---|
| `harbor-admin-secret` | Opaque (1 key) | ESO → 1Password `harbor-admin/admin-password` | Harbor chart via `existingSecretAdminPassword` / key `HARBOR_ADMIN_PASSWORD` |
| `harbor-s3-creds` | Opaque (2 keys) | ESO → 1Password `seaweedfs-harbor/{admin-access-key,admin-secret-key}` | Harbor registry via `persistence.imageChartStorage.s3.existingSecret` / keys `REGISTRY_STORAGE_S3_{ACCESSKEY,SECRETKEY}` |
| `harbor-postgres-app` | Opaque | CNPG-generated (key `password`) | Harbor chart via `database.external.existingSecret` |

## The admin-password bootstrap pitfall

**Harbor reads `existingSecretAdminPassword` exactly once — at first Helm install — and persists the password to its Postgres DB. Later Secret updates are NOT re-read.** Consequence: if the 1Password item `harbor-admin` doesn't exist when the HelmRelease first reconciles, ESO produces an empty Secret and Harbor bootstraps with an empty admin password.

Symptoms: `admin:<your password>` returns `401` on the API, `admin:` (empty) returns `200`. 

Recovery (doesn't require a re-install):

```sh
ADMIN_PASS=$(kubectl -n registries get secret harbor-admin-secret \
  -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d)
kubectl -n registries exec deploy/harbor-core -- curl -s \
  -u "admin:" -H "Content-Type: application/json" \
  -X PUT 'http://127.0.0.1:8080/api/v2.0/users/1/password' \
  -d "{\"old_password\":\"\",\"new_password\":\"$ADMIN_PASS\"}"
unset ADMIN_PASS
```

**Clean-install rule:** create the 1Password item **before** the HelmRelease first reconciles.

## Node-level wiring

- **`talos/patches/global/machine-registries.yaml`** tells containerd to treat `192.168.1.106` as HTTP. Without it, in-cluster pulls fail with TLS errors. Apply via `task talos:apply-node IP=<node>` (non-destructive, no reboot).
- **`kubernetes/apps/kube-system/spegel/app/helmrelease.yaml`** has `http://192.168.1.106` in `mirroredRegistries` and `prependExisting: true`. Preserves the Talos-managed hosts.toml entry and adds Spegel's P2P layer on top. **Don't** reapply the `287a6fa5` strip commit — it removes both of these.

## Usage

To verify Harbor is healthy end-to-end:

```sh
# API health
kubectl -n registries exec deploy/harbor-core -- \
  curl -s http://127.0.0.1:8080/api/v2.0/health | jq '.status'

# Anonymous pull
kubectl run pull-test --image=192.168.1.106/library/busybox:smoke \
  --restart=Never --rm -i --command -- true
```

Longer-form docs: `docs/docs/notes/harbor-registry.md` (architecture + troubleshooting) and `docs/docs/notes/harbor-developer-guide.md` (push/pull recipes).
