---
name: Tailscale Ingress shape — no FQDN substitution needed
description: tls.hosts[0] is a short slug; the operator builds the FQDN itself
type: reference
---

For a Recipe-A Tailscale `Ingress` (browser-trusted HTTPS off-LAN), the manifest contains only the **short slug**, not the FQDN:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <app>
spec:
  ingressClassName: tailscale
  defaultBackend:
    service: { name: <svc>, port: { number: 80 } }
  tls:
    - hosts: [<slug>]   # short slug only — no dots, no tailnet name
```

The Tailscale operator concatenates `<slug>` with the cluster's tailnet suffix to produce `<slug>.<tailnet>.ts.net` and provisions Let's Encrypt for it. **Do not** put `${TAILNET_SUFFIX}` into the `tls.hosts` field — it is unnecessary (and leaks the substitution into a place the operator does not parse).

You only need `${TAILNET_SUFFIX}` substitution when the FQDN has to appear inside the workload itself — e.g., ntfy's `server.yml` `base-url: https://ntfy.${TAILNET_SUFFIX}`, where ntfy needs to know its own external URL to render correct links in notifications.

Existing exemplars:
- `kubernetes/apps/kube-system/hubble-tailscale-ingress/app/ingress.yaml` — `tls.hosts: [hubble]`
- `kubernetes/apps/registries/harbor-config/app/ingress-tailscale.yaml` — `tls.hosts: [registry]`

No HTTPRoute, no DNSEndpoint, no gateway — Tailscale path is independent of the envoy gateways. Same-PR mixing of Tailscale changes with Cilium / gateway / CNI changes is forbidden by ADR 0012.
