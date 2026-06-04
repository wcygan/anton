# Software inventory

High-level "what's running" map for anton. Exact versions live in the manifests and Renovate PRs; this file is for orientation. For the *why* behind each pick, follow the ADR links.

**Last verified:** 2026-04-19

## Node layer

| Component | Role |
|---|---|
| Talos Linux | Immutable, API-driven node OS. Machine configs rendered from `talos/talconfig.yaml` by talhelper. |
| Kubernetes (stock upstream) | Version pinned in `talenv.yaml`; rolling upgrades via `task talos:upgrade-k8s`. |

Control plane is three MS-01 nodes with a shared VIP (see `context/hardware.md`).

## Bootstrap layer (`bootstrap/helmfile.d/`)

Applied once by `task bootstrap:apps` to take the cluster from "nodes Ready" to "Flux in charge." Strict ordering:

| Component | Role |
|---|---|
| Cilium | CNI (built-in Talos CNI is disabled). |
| CoreDNS | In-cluster DNS. |
| Spegel | Stateless OCI registry mirror across node containerd stores. |
| cert-manager | X.509 issuance (cluster-internal CA + Cloudflare ACME). |
| flux-operator / flux-instance | Installs and manages Flux itself. |

Everything past this point is Flux-managed.

## GitOps + secrets

| Component | Role |
|---|---|
| Flux CD | Reconciles `kubernetes/` from this repo. |
| SOPS (age) | Bootstrap and infra secrets. Rules in `.sops.yaml`, files match `*.sops.*`. |
| External Secrets Operator | App secrets. |
| 1Password Connect (`onepassword-store`) | `ClusterSecretStore` backing ESO; vault `anton`. |

SOPS-vs-ESO decision: see `anton-repo-conventions` skill.

## Networking and ingress

| Component | Role |
|---|---|
| Envoy Gateway | Two Gateway API listeners: `envoy-internal` (LAN) and `envoy-external` (public, via Cloudflare). |
| k8s-gateway | Split-horizon DNS — resolves HTTPRoute hostnames to the right gateway on-LAN. |
| external-dns (`cloudflare-dns`) | Publishes public records to Cloudflare from HTTPRoutes and `DNSEndpoint` resources. |
| cloudflared (`cloudflare-tunnel`) | Zero-trust tunnel fronting `envoy-external`; public traffic never hits home WAN directly. |
| Tailscale operator | Remote kubectl/talosctl access over MagicDNS. Installed out-of-band (not Flux-managed); `tailnet-rbac` binds `wcygan@github` to `cluster-admin`. |
| Multus + Whereabouts | Secondary CNI for Longhorn replica + iSCSI traffic on the SFP+ mesh. See ADRs 0017 / 0018 and plan 0004. |
| `storage-vxlan` DaemonSet | Builds the `vxlan-storage` overlay (VNI 100, 10.100.1.0/24) on the SFP+ /31 mesh and adds the `lhnet1-host` macvlan host-shim that lets the host iSCSI initiator reach co-located IM pods. |

Secondary-domain HTTPRoutes require an explicit `DNSEndpoint` — see `kubernetes/apps/network/CLAUDE.md`.

## Platform utilities

| Component | Role |
|---|---|
| reloader | Rolls Deployments/StatefulSets when referenced ConfigMaps/Secrets change. |
| metrics-server | Kubelet metrics for `kubectl top` and HPA. |

## Storage

| Component | Role | Status |
|---|---|---|
| Longhorn | Replicated block storage CSI on the 1 TB WD_BLACK NVMes. | Deployed (chart 1.11.1, plans 0001 + 0004). Replica + iSCSI traffic rides the SFP+ mesh via the `storage/longhorn-storage` NAD on `vxlan-storage` plus the `lhnet1-host` macvlan shim — see plan 0004 Log 2026-04-19. ADR 0005. |
| SeaweedFS | S3-compatible object storage. | Accepted — see [ADR 0016](adrs/0016-adopt-seaweedfs-today-on-chart-1011-via-embedded-filerspec-s3.md) (supersedes ADR 0006). Deploy pending. |
| Rook-Ceph | — | Deferred indefinitely, [ADR 0002](adrs/0002-defer-rook-ceph-indefinitely.md). |

## Observability

| Component | Role | Status |
|---|---|---|
| kube-prometheus-stack | Metrics (Prometheus + Alertmanager + Grafana). | Deployed on Longhorn PVCs in the `observability` namespace; ADR 0007. |
| OpenTelemetry (logs + traces) | Logs and traces pipeline. | Deferred roadmap — see [ADR 0008](adrs/0008-opentelemetry-based-logs-and-traces-roadmap.md). |
| ClickStack (ClickHouse + OTel + HyperDX) | Logs/traces backend eval (bundled ClickHouse, Keeper, OTel collector, MongoDB, HyperDX UI). | **EXPERIMENT** — 60-day throwaway learning eval in the `clickstack` namespace; **review-by 2026-08-02**; [ADR 0028](adrs/0028-clickstack-learning-experiment.md). Metrics stay on Prometheus; logs/traces pillar only. See [note](../docs/docs/notes/clickstack-experiment.md). |

## Tooling (runs on the operator's machine, not the cluster)

| Tool | Role |
|---|---|
| Task (`Taskfile.yaml` + `.taskfiles/`) | Top-level automation entry point. |
| Makejinja | Renders `templates/` → `kubernetes/`, `talos/`, `bootstrap/`. |
| talhelper | Renders Talos machine configs from `talconfig.yaml`. |
| Helmfile | Drives the one-shot bootstrap layer. |
| Renovate | Opens PRs for chart, image, and Talos/Kubernetes version bumps. |
