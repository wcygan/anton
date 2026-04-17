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

## How the operator exposes a Service

Annotate the Service the chart already produces. Two annotations, both optional but the second is strongly recommended:

```yaml
metadata:
  annotations:
    tailscale.com/expose: "true"           # required — opts the Service into exposure
    tailscale.com/hostname: grafana        # optional — MagicDNS short name; defaults to the Service name if unset
```

The operator watches for these, provisions a tailnet-joined proxy (its own StatefulSet + Service), and reverse-proxies tailnet traffic to the annotated Service. TLS is Tailscale-issued on the proxy — cert-manager is not involved. MagicDNS publishes `<hostname>.<tailnet>.ts.net` on the tailnet.

**Do not commit the real tailnet name.** In docs and commit messages use the placeholder `<tailnet-name>.ts.net`. The MagicDNS hostname itself (`grafana`, `longhorn`, etc.) is fine.

## Wiring this through a Helm chart

Most charts expose Service annotations under `service.annotations` or `<subchart>.service.annotations`. Prefer that over a Kustomize patch — it keeps the annotation in the HelmRelease where chart values live.

- `kube-prometheus-stack` → `grafana.service.annotations` (canonical example; see `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`).
- bjw-s `app-template` → `service.<name>.annotations`.
- Chart lacks a Service-annotation knob → fall back to a Kustomize `patches:` entry in the app's `kustomization.yaml` with a `kind: Service` target.

## Verification

After Flux reconciles:

```sh
# operator observes the annotated Service and creates a Tailscale proxy Service
kubectl get svc -n <ns> <service> -o jsonpath='{.metadata.annotations}'
kubectl get svc -A -l tailscale.com/parent-resource=<service>

# MagicDNS record should resolve from any tailnet-joined device
tailscale status | rg <hostname>

# hit it from the workstation (while on the tailnet)
curl -sS -o /dev/null -w '%{http_code}\n' https://<hostname>.<tailnet>.ts.net/
```

Do **not** expect the hostname to resolve from outside the tailnet — that is the whole point. If a non-tailnet device must reach the workload, the answer is `envoy-external`, not a Tailscale exception.

## What's still out of scope

Settled by ADR 0012 only for **Service-level expose**. These remain un-adopted and would need their own decision:

- **Tailscale `serve` / `funnel`** for public exposure. Public path stays on Cloudflare tunnel.
- **Tailscale subnet routers** for pod/service CIDRs. Not set up — and not needed for the patterns above, because the per-Service proxy handles routing.
- **Tailscale ingress class** (the `LoadBalancer` + `loadBalancerClass: tailscale` mode). Functionally equivalent to the annotation path; annotations are the supported shape in this repo. If a chart ever makes annotations harder than flipping Service type, that's a separate decision.

## Capacity and device hygiene

Each exposed Service consumes a tailnet device slot (free tier cap: 100). At current growth this is not a constraint, but audit the device list (`tailscale status`, Tailscale admin console) when adding many. Stale devices appear after operator-pod churn — the operator reuses auth keys but MagicDNS entries can linger; clean them up in the admin console when you see `-1`, `-2` suffixes in production hostnames.

## Related reading

- Policy ADR → `context/adrs/0012-tailscale-for-internal-remote-workload-access.md`
- Operational Tailscale (how `kubectl`/`talosctl` reach the cluster) → `anton-remote-access`
- Persistent Tailscale node names, why `TS_STATE_DIR=mem:` matters → ADR 0010
