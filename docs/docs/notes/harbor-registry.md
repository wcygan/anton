# Harbor Container Registry

Private container registry for the cluster. In-cluster and on-LAN access at
`http://192.168.1.106`; remote web UI at `https://registry.<tailnet-name>.ts.net`
via the Tailscale operator. Installed per ADR 0015, backed by SeaweedFS S3
object storage (ADR 0019) for image blobs.

## Access surfaces

| Surface | Endpoint | Transport | Use |
|---|---|---|---|
| LAN / in-cluster | `192.168.1.106` | HTTP | `docker push`/`pull`, Kubernetes image refs |
| Remote web UI | `registry.<tailnet-name>.ts.net` | HTTPS (Tailscale-provisioned TLS) | Admin console, robot-account management |

The LoadBalancer VIP `192.168.1.106` is the Docker v2 API and auth-realm
endpoint. The Tailscale ingress is web-UI-only — pushing and pulling blobs
through it works but the Tailscale path isn't where nodes pull from.

## Architecture

```
                 ┌──────────────────────────────┐
                 │ Tailscale Operator Ingress   │
                 │ registry.<tailnet>.ts.net    │
                 │ (web UI, browser-trusted TLS)│
                 └──────────────┬───────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│            Cilium LoadBalancer VIP — 192.168.1.106 (HTTP)      │
│          Docker v2 API + auth realm for containerd pulls       │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│                      Harbor components                         │
│  ┌────────┐  ┌──────┐  ┌──────────────┐  ┌────────────────┐    │
│  │ Portal │  │ Core │  │  JobService  │  │    Registry    │    │
│  │ (2x)   │  │ (2x) │  │     (1x)     │  │     (2x)       │    │
│  └────────┘  └──────┘  └──────────────┘  └────────────────┘    │
│     (Trivy disabled per ADR 0015 — no vulnerability scanning)  │
└───────────┬───────────────────────┬───────────────────────┬────┘
            │                       │                       │
            ▼                       ▼                       ▼
  ┌──────────────────┐    ┌──────────────────┐   ┌─────────────────────┐
  │ CNPG PostgreSQL  │    │ DragonflyDB      │   │ SeaweedFS S3        │
  │ harbor-postgres  │    │ harbor-redis     │   │ seaweedfs-s3        │
  │ 3 replicas (HA)  │    │ 3 replicas (HA)  │   │ bucket: `harbor`    │
  │ Longhorn storage │    │ Longhorn storage │   │ plain HTTP cluster  │
  │                  │    │ (no auth)        │   │ internal @ :8333    │
  └──────────────────┘    └──────────────────┘   └─────────────────────┘
```

## Key design decisions

- **SeaweedFS S3 backend.** Registry blobs are written to
  `http://seaweedfs-s3.storage.svc.cluster.local:8333` bucket `harbor`
  (registered as `persistence.imageChartStorage.s3.*` in the HelmRelease
  values). `disableredirect: true` is set because SeaweedFS does not
  support pre-signed-URL redirects the way MinIO does. Credentials are
  the shared `seaweedfs-harbor` 1Password admin identity for v1, reshaped
  into Harbor-expected `REGISTRY_STORAGE_S3_ACCESSKEY` /
  `REGISTRY_STORAGE_S3_SECRETKEY` keys by an ExternalSecret.
- **`jobservice.replicas: 1`.** The pre-reset cluster used Ceph's RWX
  filesystem to let multiple jobservice replicas share a job-log PVC;
  without a replicated filesystem today, jobservice is pinned at 1 so
  its RWO Longhorn volume has a single writer (ADR 0015 Consequences).
- **Trivy disabled.** Vulnerability scanning is off per ADR 0015.
  Re-enabling requires a design decision about where scan databases
  and vulnerability reports live.
- **Anonymous pull on `library`.** Post-install API call sets project
  `library` to public; Pods pull from `192.168.1.106/library/...` with
  no `imagePullSecret`. Pushes still require admin auth.
- **LoadBalancer VIP over Tailscale for image I/O.** Containerd on the
  Talos nodes runs in the host netns and needs a stable LAN-reachable
  endpoint for the Docker auth realm. The Tailscale ingress remains the
  web UI path.

## Credentials

| Secret name | Kind | Purpose | Source |
|---|---|---|---|
| `registries/harbor-admin-secret` | Opaque | Admin login (`HARBOR_ADMIN_PASSWORD`) | ExternalSecret → 1Password `harbor-admin/admin-password` |
| `registries/harbor-s3-creds` | Opaque | Registry → SeaweedFS S3 | ExternalSecret → 1Password `seaweedfs-harbor/admin-{access,secret}-key` |
| `registries/harbor-postgres-app` | Opaque | Postgres app user | CNPG-generated |

All three live in the `registries` namespace. The admin password lands
in a Secret via ESO; never committed.

**Bootstrap-password pitfall.** Harbor reads `existingSecretAdminPassword`
only at first install and persists the password in its Postgres DB; later
Secret updates are *not* re-read. If the Secret is empty when Harbor first
installs (e.g. the 1Password item doesn't exist yet), you'll need a
one-time `PUT /api/v2.0/users/1/password` to sync the real password:

```sh
ADMIN_PASS=$(kubectl -n registries get secret harbor-admin-secret \
  -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d)
kubectl -n registries exec deploy/harbor-core -- curl -s \
  -u "admin:" -H "Content-Type: application/json" \
  -X PUT 'http://127.0.0.1:8080/api/v2.0/users/1/password' \
  -d "{\"old_password\":\"\",\"new_password\":\"$ADMIN_PASS\"}"
unset ADMIN_PASS
```

For a clean re-install, create the 1Password item *before* the HelmRelease
first reconciles.

## Node-level wiring (Talos + Spegel)

- **Talos machine-registries patch** (`talos/patches/global/machine-registries.yaml`)
  tells containerd to treat `192.168.1.106` as HTTP:
  ```yaml
  machine:
    registries:
      mirrors:
        "192.168.1.106":
          endpoints:
            - "http://192.168.1.106"
  ```
  Applied via `task talos:apply-node IP=<node>` (non-destructive, no reboot;
  containerd re-reads registry config on apply).
- **Spegel P2P mirror** (`kubernetes/apps/kube-system/spegel/app/helmrelease.yaml`)
  includes `http://192.168.1.106` in `mirroredRegistries` with
  `prependExisting: true`. After the first node pulls an image, peers can
  serve it peer-to-peer without re-fetching from Harbor. Observed second-node
  pull served in ~10-15% of the first-node pull time for a small image.

## Anonymous pull

Project `library` is public. In-cluster Pods pull without an
`imagePullSecret`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp
  namespace: default
spec:
  containers:
    - name: myapp
      image: 192.168.1.106/library/myapp:latest
```

No `docker login` is needed for pull; it is for push. See
[harbor-developer-guide.md](./harbor-developer-guide.md) for the push flow.

If you need a *private* project with auth-gated pulls, create a robot
account scoped to that project in the Harbor UI and distribute its
`Secret` via ExternalSecret pointing at a 1Password item — don't commit
per-namespace `docker-registry` Secrets.

## Verification

```sh
# Harbor health
kubectl -n registries exec deploy/harbor-core -- \
  curl -s http://127.0.0.1:8080/api/v2.0/health | jq

# HelmRelease + CR status
flux -n registries get hr harbor
kubectl -n registries get cluster,dragonfly,helmrelease
kubectl -n registries get pods

# S3 backend holds blobs after first push
AK=$(kubectl -n storage get secret seaweedfs-s3-config \
  -o jsonpath='{.data.s3\.json}' | base64 -d \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["identities"][0]["credentials"][0]["accessKey"])')
# (+ SK the same way)
kubectl -n storage run s3-ls --rm --restart=Never \
  --image=amazon/aws-cli:2.17.0 \
  --env=AWS_ACCESS_KEY_ID=$AK --env=AWS_SECRET_ACCESS_KEY=$SK \
  --env=AWS_EC2_METADATA_DISABLED=true \
  --command -- aws --endpoint-url=http://seaweedfs-s3.storage.svc.cluster.local:8333 \
    s3 ls s3://harbor/docker/registry/v2/repositories/ --recursive
```

## File locations

| Component | Path |
|---|---|
| Harbor HelmRelease | `kubernetes/apps/registries/harbor/app/helmrelease.yaml` |
| Postgres `Cluster` CR | `kubernetes/apps/registries/harbor-config/app/postgres-cluster.yaml` |
| Dragonfly CR | `kubernetes/apps/registries/harbor-config/app/dragonfly.yaml` |
| Admin-password ExternalSecret | `kubernetes/apps/registries/harbor-config/app/externalsecret-admin.yaml` |
| S3-creds ExternalSecret | `kubernetes/apps/registries/harbor-config/app/externalsecret-s3.yaml` |
| Tailscale Ingress | `kubernetes/apps/registries/harbor-config/app/ingress-tailscale.yaml` |
| CNPG operator | `kubernetes/apps/databases/cloudnative-pg/` |
| Dragonfly operator | `kubernetes/apps/databases/dragonfly-operator/` |
| Talos machine-registries patch | `talos/patches/global/machine-registries.yaml` |
| Spegel mirror config | `kubernetes/apps/kube-system/spegel/app/helmrelease.yaml` |

## Troubleshooting

### Pulls hang or fail TLS

Likely the Talos machine-registries patch isn't applied on the node. Check:

```sh
talosctl --endpoints <tailscale-ip> --nodes <tailscale-ip> \
  get machineconfig -o yaml | yq '.spec.machine.registries'
```

Should show `mirrors['192.168.1.106'].endpoints[0] = http://192.168.1.106`.

### Push or admin API returns 401

Your local admin password disagrees with Harbor's DB. See the
bootstrap-password pitfall above, or reset via the Harbor UI.

### Registry pod 5xx on push

Check SeaweedFS is reachable and the `harbor` bucket exists:

```sh
kubectl -n registries logs deploy/harbor-registry -c registry --tail=30
```

Look for `s3aws` or `S3` errors referencing the SeaweedFS endpoint.
