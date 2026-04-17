# Tailscale in Anton

**Policy source**: ADR 0012 (`context/adrs/0012-tailscale-for-internal-remote-workload-access.md`), amended 2026-04-17.

Tailscale has two roles in this cluster:

1. **Kubernetes API proxy** — how `kubectl`, `flux`, and `helm` reach the cluster off-LAN. Long-standing; see `anton-remote-access`.
2. **Internal remote workload access** — how an admin UI or dashboard is reached by an operator off-LAN, without publishing it to public DNS or the Cloudflare tunnel.

Upstream docs (WebFetch when in doubt — shapes have evolved):

- Operator overview: https://tailscale.com/docs/features/kubernetes-operator
- Exposing a cluster workload to the tailnet: https://tailscale.com/docs/features/kubernetes-operator/how-to/cluster-ingress
- Ingress resource (HTTPS): https://tailscale.com/docs/features/kubernetes-operator/how-to/ingress

## When to pick Tailscale over envoy-internal or envoy-external

Use the `expose-service` skill's gateway-choice matrix. Short version:

- **LAN only, no remote access needed** → `envoy-internal` (no Tailscale).
- **LAN + off-LAN HTTP admin UI** → `envoy-internal` HTTPRoute **plus** a Tailscale `Ingress` on the same workload (Recipe A below). LAN clients get split-horizon DNS via `k8s-gateway`; remote clients get `<slug>.<tailnet>.ts.net` with a browser-trusted cert.
- **Off-LAN raw TCP or non-HTTP** → Service annotation (Recipe B). No TLS is terminated on the proxy; clients reach whatever the backend serves on its port.
- **Genuinely public (audience that cannot be required to join the tailnet)** → `envoy-external` + Cloudflare tunnel. Reserved for public-facing workloads only (echo smoke test, webhook receivers, demo pages).

Do **not** use `envoy-external` for admin UIs just to make them remotely reachable — that's what Tailscale is for.

## Recipe A — Ingress (HTTP admin UIs, browser-trusted HTTPS)

This is the supported path for any HTTP workload consumed in a browser. The operator provisions a Let's Encrypt cert via MagicDNS and terminates TLS on the proxy, so `https://<slug>.<tailnet>.ts.net` is trusted natively.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <app>
  namespace: <ns>
spec:
  ingressClassName: tailscale
  tls:
    - hosts:
        - <slug>          # MagicDNS short name — do NOT include the tailnet suffix
  defaultBackend:
    service:
      name: <service>
      port:
        number: <port>
```

Most charts also expose ingress via `ingress.*` values — prefer the chart knob over a standalone file when the chart supports it. Example values for `kube-prometheus-stack`:

```yaml
grafana:
  ingress:
    enabled: true
    ingressClassName: tailscale
    hosts: [grafana]
    tls:
      - hosts: [grafana]
```

> ⚠️ **Throughput caveat (ADR 0012 amendment 2026-04-17).** The operator defaults Ingress-resource proxies to **userspace netstack** (`TS_USERSPACE=true`), which caps per-proxy throughput near 100 Kbps; upstream bug [tailscale/tailscale#16198](https://github.com/tailscale/tailscale/issues/16198) also hits kernel-mode proxies on v1.84+ via oversized TCP segments past the 1280 MTU. Effect: SPA loads over the tailnet are slow (Grafana measured ~12 KB/s from a macOS peer); small API calls and text payloads feel fine. A `ProxyClass` for kernel-mode + privileged TUN is the prerequisite for the known workaround (`ethtool -k tailscale0 tso off gso off` inside the proxy) but does not itself fix throughput (ProxyClass has no sidecar or postStart hook, and `ethtool` is not in the Alpine proxy image). Until upstream fix (milestone 1.98.x) lands: prefer `envoy-internal` on LAN; use Tailscale Ingress for off-LAN admin access and accept the slowness. Do not copy a ProxyClass blindly onto other workloads — it only helps if a compatible `ethtool` workaround exists.

## Recipe B — Service annotation (raw TCP, non-HTTP workloads)

Use this when the workload is **not** HTTP, or when you specifically want a plain TCP pass-through to the backend's own TLS (e.g. a Kubernetes-API-style workload already serving its own cert). **No TLS is terminated on the proxy** — clients reach whatever the backend Service serves on its target port. For HTTP backends this means the URL is `http://...`; the WireGuard tunnel still encrypts it on the wire, but browsers will label it "Not secure."

```yaml
metadata:
  annotations:
    tailscale.com/expose: "true"           # required — opts the Service into exposure
    tailscale.com/hostname: <slug>         # optional — MagicDNS short name; defaults to the Service name if unset
```

The operator watches for these, provisions a tailnet-joined proxy (its own StatefulSet + Service), and forwards tailnet TCP traffic to the annotated Service. MagicDNS publishes `<slug>.<tailnet>.ts.net` on the tailnet.

Most charts expose Service annotations under `service.annotations` or `<subchart>.service.annotations`. Chart lacks the knob → fall back to a Kustomize `patches:` entry in the app's `kustomization.yaml` with a `kind: Service` target.

## Hostname hygiene

**Do not commit the real tailnet name.** In docs and commit messages use the placeholder `<tailnet-name>.ts.net`. The MagicDNS short name itself (`grafana`, `longhorn`, etc.) is fine to commit.

## Verification

After Flux reconciles:

```sh
# Ingress-based (Recipe A): operator creates a proxy Service and a tls Secret
kubectl get ingress -n <ns> <app>
kubectl get svc,statefulset -n tailscale -l tailscale.com/parent-resource=<app>

# Annotation-based (Recipe B): operator creates a proxy StatefulSet in the tailscale namespace
kubectl get svc -n <ns> <service> -o jsonpath='{.metadata.annotations}'
kubectl get statefulset -n tailscale -l tailscale.com/parent-resource=<service>

# MagicDNS record should resolve from any tailnet-joined device
tailscale status | rg <slug>

# hit it from the workstation (while on the tailnet)
curl -sS -o /dev/null -w '%{http_code}\n' https://<slug>.<tailnet>.ts.net/
```

Do **not** expect the hostname to resolve from outside the tailnet — that is the whole point. If a non-tailnet device must reach the workload, the answer is `envoy-external`, not a Tailscale exception.

## Operational guardrails

- **No bundling.** Tailscale-exposure changes ship on their own PR, never mixed with Cilium / gateway / CNI changes. A five-commit revert on 2026-04-16 was caused by bundling an Ingress switch with a subnet-router + DSR→SNAT LB-mode change. Enforced by ADR 0012 Consequences.
- **Tailscale subnet routers are forbidden** by ADR 0012 Alternatives — they leak the LAN, fight `TS_STATE_DIR=mem:` (ADR 0010), and were the first contributing cause of the revert storm. Any future need must go through a new ADR.

## What's still out of scope

Settled by ADR 0012 only for **Ingress-class and Service-annotation exposure**. These remain un-adopted and would need their own decision:

- **Tailscale `serve` / `funnel`** for public exposure. Public path stays on Cloudflare tunnel.
- **Tailscale subnet routers** for pod/service CIDRs or the home LAN (see guardrails above).
- **ProxyGroup / shared proxy pool** (operator 1.88+). Validate against `TS_STATE_DIR=mem:` (ADR 0010) before any adoption — current ephemeral-identity constraint may conflict.

## Capacity and device hygiene

Each exposed resource (Ingress or annotated Service) consumes a tailnet device slot (free tier cap: 100). At current growth this is not a constraint, but audit the device list (`tailscale status`, Tailscale admin console) when adding many. Stale devices appear after operator-pod churn — the operator reuses auth keys but MagicDNS entries can linger; clean them up in the admin console when you see `-1`, `-2` suffixes in production hostnames.

## Related reading

- Policy ADR → `context/adrs/0012-tailscale-for-internal-remote-workload-access.md`
- Operational Tailscale (how `kubectl`/`talosctl` reach the cluster) → `anton-remote-access`
- Persistent Tailscale node names, why `TS_STATE_DIR=mem:` matters → ADR 0010
