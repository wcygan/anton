# kubernetes/apps/network/

Two responsibilities live here. **Ingress** — `envoy-external` (public, via Cloudflare tunnel) and `envoy-internal` (LAN, via split-horizon DNS) front every HTTPRoute in the cluster; apps don't configure networking directly, they declare HTTPRoutes pointed at one of those gateways. **Storage fabric** — Multus + Whereabouts + a per-node VXLAN overlay DaemonSet provide the secondary network Longhorn replicates over (see ADRs 0009 / 0017 / 0018, plan 0004).

## Contents

### Ingress

- `envoy-gateway/` — Envoy Gateway controller plus `Gateway` definitions and the shared wildcard `Certificate` (from cert-manager); see `envoy-gateway/app/envoy.yaml` for the two Gateway specs and listener configuration
- `cloudflare-tunnel/` — `cloudflared` release bound to the `envoy-external` gateway; tunnel token is ESO-managed, HTTP/2 egress (UDP/7844 is blocked on this network)
- `cloudflare-dns/` — `external-dns` controller watching HTTPRoutes and writing CNAMEs to Cloudflare; filtered by `${cloudflare_domain}`
- `k8s-gateway/` — in-cluster DNS server at `${cluster_dns_gateway_addr}` that serves `*.${SECRET_DOMAIN}` as an A record to `${cluster_gateway_addr}` for LAN clients

### Storage fabric (ADR 0017 / plan 0004)

- `multus/` — Multus thick-plugin chained behind Cilium, installed via `GitRepository` + Flux `Kustomization` `spec.patches` (no usable Helm chart for thick mode). Includes the `install-cni` init container per ADR 0018 that drops `macvlan` + reference plugins into `/opt/cni/bin` on every node
- `whereabouts/` — IPAM for the secondary network; same `GitRepository` + `spec.patches` pattern as Multus
- `storage-vxlan/` — DaemonSet that builds the `vxlan-storage` overlay (VNI 100, MTU 8950) on top of the SFP+ /31 mesh and **adds the `lhnet1-host` macvlan-bridge child** that the host's iSCSI initiator uses to reach co-located Longhorn IM pods. The host-shim is load-bearing — without it, bare macvlan or ipvlan NADs on a vxlan parent break Longhorn v1 iSCSI. Storage namespace's `longhorn-storage` NAD lives at `kubernetes/apps/storage/longhorn-config/`

## Usage

Use the `expose-service` skill to add an HTTPRoute — it chooses the correct gateway (`envoy-internal` vs `envoy-external`), wires `parentRefs`/`sectionName: https`, and handles the postBuild substitution. The `add-flux-app` skill calls it automatically when scaffolding an app that needs exposure.

**Gateway choice:** `envoy-internal` for anything that should not be on the public internet (admin UIs, dashboards, dev); `envoy-external` only when Cloudflare-fronted access is genuinely required. Changing gateway ≠ changing hostname — split-horizon DNS makes the same hostname resolve differently per client.

**Secondary domains require an explicit `DNSEndpoint` resource** — HTTPRoute annotations alone will not cause `external-dns` to create records for a non-primary domain. Full walk-through: `docs/docs/notes/adding-a-2nd-domain.md`. Before editing anything in `envoy-gateway/app/envoy.yaml` itself, confirm the change is universal across both gateways; per-app routing belongs in the app's own HTTPRoute.
