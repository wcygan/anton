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
endpoint. Use the Tailscale ingress for the web UI. Its authenticated OCI path
has the token-realm mismatch described below.

## Architecture

```
                 ┌──────────────────────────────┐
                 │ Tailscale Operator Ingress   │
                 │ registry.<tailnet-name>.ts.net │
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
only during first installation. It then stores the password in PostgreSQL.
Later Secret updates do not replace the stored password.

Treat password repair as credential rotation. Use the application-credential
branch in `rotate-credential`. Keep the value out of shell variables, command
arguments, output, and retained evidence.

For a clean installation, create the 1Password item before the first
HelmRelease reconciliation.

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
  Applied via `mise exec -- task talos:apply-node IP=<node>` (non-destructive, no reboot;
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
mise exec -- kubectl -n registries exec deploy/harbor-core -- \
  curl -s http://127.0.0.1:8080/api/v2.0/health | jq

# HelmRelease + CR status
mise exec -- flux -n registries get hr harbor
mise exec -- kubectl -n registries get cluster,dragonfly,helmrelease
mise exec -- kubectl -n registries get pods

# Registry logs show successful S3-backed blob work after one approved push.
mise exec -- kubectl -n registries logs deploy/harbor-registry \
  -c registry --tail=100 | rg 's3|blob|error'
```

Do not extract storage credentials for verification. Retain the pushed digest,
Harbor response, and bounded registry logs.

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

### `docker login registry.<tailnet-name>.ts.net` fails with "connection refused" on port 80

Known issue. Harbor's `externalURL` is `http://192.168.1.106`, so when Docker requests a
token it gets a `WWW-Authenticate` realm of `http://registry.<tailnet-name>.ts.net/service/token` —
note the `http://` scheme. The Tailscale operator Ingress only serves port 443 (even though
its `Ingress` object lists `80, 443`), so the realm URL isn't reachable and Docker's auth
flow stalls.

Use the host-native flow in
[the Harbor developer guide](./harbor-developer-guide.md). It validates the
client network namespace, challenge realm, archive, remote digest, and cleanup.

Docker Desktop can run its engine in a virtual machine. Its `localhost` might
not reach a Mac host port-forward.

Anonymous in-cluster pulls are unaffected — they don't hit the auth realm. The issue
surfaces only for authenticated flows (laptop push, private-project pulls).

### Pulls hang or fail TLS

Likely the Talos machine-registries patch isn't applied on the node. Check:

```sh
mise exec -- talosctl --endpoints <tailscale-ip> --nodes <tailscale-ip> \
  get machineconfig -o yaml | yq '.spec.machine.registries'
```

Should show `mirrors['192.168.1.106'].endpoints[0] = http://192.168.1.106`.

### Push or admin API returns 401

Your local admin password disagrees with Harbor's DB. See the
bootstrap-password pitfall above, or reset via the Harbor UI.

### Registry pod 5xx on push

Check SeaweedFS is reachable and the `harbor` bucket exists:

```sh
mise exec -- kubectl -n registries logs deploy/harbor-registry \
  -c registry --tail=30
```

Look for `s3aws` or `S3` errors referencing the SeaweedFS endpoint.
