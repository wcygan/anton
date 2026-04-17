# Tailscale in Anton

**Policy source**: ADR 0012 (`context/adrs/0012-tailscale-for-internal-remote-workload-access.md`).

Tailscale has two roles in this cluster:

1. **Kubernetes API proxy** — how `kubectl`, `flux`, and `helm` reach the cluster off-LAN. Long-standing; see `anton-remote-access`.
2. **Internal remote workload access** — how an admin UI or dashboard is reached by an operator off-LAN, without publishing it to public DNS or the Cloudflare tunnel.

Upstream docs (WebFetch when in doubt — the annotation shape has evolved):

- Operator overview: https://tailscale.com/docs/features/kubernetes-operator
- Exposing a cluster workload to the tailnet: https://tailscale.com/docs/features/kubernetes-operator/how-to/cluster-ingress

## When to pick Tailscale over envoy-internal or envoy-external

Use the `expose-service` skill's gateway-choice matrix. Short version:

- **LAN only, no remote access needed** → `envoy-internal` (no Tailscale).
- **LAN + occasional remote operator access** → `envoy-internal` **plus** Tailscale annotation on the same Service. LAN clients get split-horizon DNS via `k8s-gateway`; remote clients get the tailnet hostname. Grafana is the canonical example of this pattern.
- **Remote operator access only, no LAN DNS needed** → Tailscale annotation on a ClusterIP Service. No HTTPRoute, no envoy.
- **Genuinely public (audience that cannot be required to join the tailnet)** → `envoy-external` + Cloudflare tunnel. Reserved for public-facing workloads only (echo smoke test, webhook receivers, demo pages).

Do **not** use `envoy-external` for admin UIs just to make them remotely reachable — that's what Tailscale is for now.

## Two recipes — pick by whether you want HTTPS in the browser

The Tailscale operator exposes workloads two different ways. They differ in whether TLS is terminated on the proxy and whether browsers trust the cert.

### Recipe A — Ingress (default for HTTP workloads)

Use this for any HTTP admin UI consumed in a browser (Grafana, Longhorn, etc.). The operator watches for `Ingress` resources with `ingressClassName: tailscale`, provisions a tailnet-joined proxy, and **terminates TLS on the proxy with a Let's Encrypt cert bound to the MagicDNS hostname**. Browsers trust the cert with no extra setup, and the URL is `https://<hostname>.<tailnet>.ts.net/`.

Standalone Ingress:

```yaml
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: observability
spec:
  ingressClassName: tailscale
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kube-prometheus-stack-grafana
                port: { number: 80 }
  tls:
    - hosts: [grafana]   # MagicDNS short name; no secretName — operator manages the cert
```

Most charts also expose ingress via `ingress.*` values — prefer the chart knob over a standalone file when the chart supports it. Canonical example: `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml` → `grafana.ingress` with `ingressClassName: tailscale` and `tls.hosts: [grafana]`.

### Recipe B — Service annotation (for non-HTTP or when you want raw TCP)

Use this when the workload is **not** HTTP, or when you specifically want a plain TCP pass-through to the backend's own TLS (e.g. a Kubernetes-API-style workload already serving its own cert). **No TLS is terminated on the proxy** — clients reach whatever the backend Service serves on its target port. For HTTP backends this means the URL is `http://...`; the WireGuard tunnel still encrypts it on the wire, but browsers will label it "Not secure."

```yaml
metadata:
  annotations:
    tailscale.com/expose: "true"       # required — opts the Service into exposure
    tailscale.com/hostname: foo        # MagicDNS short name; defaults to the Service name if unset
```

The operator provisions a tailnet-joined proxy (its own StatefulSet + Service) and reverse-proxies tailnet traffic straight to the annotated Service. No cert, no Let's Encrypt — the proxy is a TCP forwarder.

**Common mistake:** setting this annotation on an HTTP Service and expecting `https://<host>.ts.net/` to work in a browser. It will time out on :443. Use Recipe A for HTTPS.

## Hostname hygiene

**Do not commit the real tailnet name.** In docs and commit messages use the placeholder `<tailnet-name>.ts.net`. The MagicDNS hostname itself (`grafana`, `longhorn`, etc.) is fine — that's local-context-only and does not leak the tailnet.

## Verification

After Flux reconciles:

```sh
# Recipe A: operator creates a proxy StatefulSet + Service under namespace tailscale
kubectl get ingress -n <ns> <name>
kubectl get svc     -n tailscale -l tailscale.com/parent-resource-ns=<ns>

# Recipe B: same parent-resource label, targets the annotated Service
kubectl get svc -n <ns> <service> -o jsonpath='{.metadata.annotations}'
kubectl get svc -A -l tailscale.com/parent-resource=<service>

# MagicDNS record should resolve from any tailnet-joined device
tailscale status | rg <hostname>

# Hit it from the workstation (while on the tailnet)
curl -sS -o /dev/null -w '%{http_code}\n' https://<hostname>.<tailnet>.ts.net/   # Recipe A
curl -sS -o /dev/null -w '%{http_code}\n' http://<hostname>.<tailnet>.ts.net/    # Recipe B
```

Do **not** expect the hostname to resolve from outside the tailnet — that is the whole point. If a non-tailnet device must reach the workload, the answer is `envoy-external`, not a Tailscale exception.

## What's still out of scope

ADR 0012 covers the **Ingress** and **Service-annotation** recipes above. These Tailscale features remain un-adopted and would need their own decision:

- **Tailscale `serve` / `funnel`** for public exposure. Public path stays on Cloudflare tunnel.
- **Tailscale subnet routers** for pod/service CIDRs. Not set up — and not needed for the patterns above, because the per-workload proxy handles routing.
- **`loadBalancerClass: tailscale` on Services** (the LB-class variant of Recipe B). Functionally overlaps with the annotation path; annotations are the supported shape. Revisit only if a chart makes annotations harder than flipping Service type.

## Capacity and device hygiene

Each exposed Service consumes a tailnet device slot (free tier cap: 100). At current growth this is not a constraint, but audit the device list (`tailscale status`, Tailscale admin console) when adding many. Stale devices appear after operator-pod churn — the operator reuses auth keys but MagicDNS entries can linger; clean them up in the admin console when you see `-1`, `-2` suffixes in production hostnames.

## Related reading

- Policy ADR → `context/adrs/0012-tailscale-for-internal-remote-workload-access.md`
- Operational Tailscale (how `kubectl`/`talosctl` reach the cluster) → `anton-remote-access`
- Persistent Tailscale node names, why `TS_STATE_DIR=mem:` matters → ADR 0010
