# kubernetes/apps/network/

Goal: Maintain Anton's ingress layer and storage networking fabric without changing per-app routing semantics accidentally.

Success means:
- HTTPRoutes point at `envoy-internal` for private/LAN paths or `envoy-external` for Cloudflare-fronted public paths.
- Gateway-wide changes land only when they apply to every app behind that gateway.
- Multus, Whereabouts, and `storage-vxlan` preserve the Longhorn storage-network path described by ADRs 0017 and 0018.

Stop when: the changed network resource matches the intended scope and read-only status checks confirm the relevant controllers or resources.

## Contents

- `envoy-gateway/`: Envoy Gateway controller, two shared Gateways, wildcard Certificate.
- `cloudflare-tunnel/`: cloudflared tunnel to `envoy-external`; token comes from ESO.
- `cloudflare-dns/`: external-dns controller for Cloudflare records.
- `k8s-gateway/`: split-horizon DNS for LAN clients.
- `multus/`: thick-plugin Multus installed through GitRepository plus patches.
- `whereabouts/`: IPAM for secondary networks.
- `storage-vxlan/`: per-node VXLAN overlay plus `lhnet1-host` host shim for Longhorn iSCSI.

## Load-Bearing Rules

Preserve the `storage-vxlan` host shim unless a new diagnosis proves Longhorn iSCSI still works without it. The host iSCSI initiator reaches same-node instance-manager pods through `lhnet1-host`; bare macvlan/ipvlan attempts on the VXLAN parent failed this gate.

Use `docs/docs/notes/adding-a-2nd-domain.md` before adding secondary-domain routes. Add an explicit `DNSEndpoint` for those domains.

## Validation

```sh
flux get ks -n network
flux get hr -n network
kubectl -n network get httproute,gateway,dnsendpoint
```
