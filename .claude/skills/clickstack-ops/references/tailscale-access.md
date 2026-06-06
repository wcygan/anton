# Tailscale access — how HyperDX is reachable off-LAN (and why login works)

How the HyperDX UI is exposed over the tailnet, the two-part fix that makes login work from off-box, and — load-bearing — how the tailnet name is kept out of git. Placeholders only here: write `<tailnet-name>.ts.net` or the `${TAILNET_SUFFIX}` variable, **never** the literal tailnet name in any committed file.

## The problem this solved

HyperDX needed to be reachable from off-LAN (over Tailscale), and two separate things were in the way:

1. **The `envoy-internal` HTTPRoute is LAN-only.** Its Gateway LoadBalancer sits on the home LAN subnet (`192.168.1.0/24`), so `hyperdx.${SECRET_DOMAIN}` resolves and serves on-LAN via `k8s_gateway` split-horizon DNS, but is **not** reachable across the tailnet.
2. **HyperDX's default `FRONTEND_URL` was `http://localhost:3000`.** HyperDX builds its login / redirect URLs from `FRONTEND_URL`, so any off-box user loaded the page (HTTP 200) but got bounced to `localhost:3000` the moment they hit `/login`.

Reachability and login are **two independent fixes** — you need both.

## The fix — two parts

### 1. A dedicated Tailscale Ingress (reachability)

A separate Flux app, `hyperdx-tailscale-ingress`, mirrors `kube-system/hubble-tailscale-ingress`: a plain `Ingress` with `ingressClassName: tailscale` whose backend is the HyperDX Service `clickstack-app:3000`. The Tailscale operator (already running, the same one backing `anton-remote-access`) sees the Ingress, provisions a proxy pod (`ts-hyperdx-*` in the `tailscale` namespace), and registers the app on MagicDNS as `hyperdx.<tailnet-name>.ts.net`.

```yaml
# kubernetes/apps/clickstack/hyperdx-tailscale-ingress/app/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hyperdx
  namespace: clickstack
spec:
  ingressClassName: tailscale
  tls:
    - hosts:
        - hyperdx          # Tailscale APPENDS the tailnet suffix → no name in git
  defaultBackend:
    service:
      name: clickstack-app # the chart's hyperdx fullname helper appends -app
      port:
        number: 3000
```

This is tailnet-internal per **ADR 0012** (Tailscale for internal remote workload access) — **not** a public exposure. No Cloudflare tunnel, no `envoy-external`.

### 2. `FRONTEND_URL` pointed at the tailnet origin (login)

Set in the main HelmRelease values so HyperDX builds redirects against the URL users actually hit:

```yaml
# kubernetes/apps/clickstack/clickstack-app/app/helmrelease.yaml  (spec.values)
hyperdx:
  config:
    FRONTEND_URL: "https://hyperdx.${TAILNET_SUFFIX}"
```

`hyperdx.config` deep-merges over the chart defaults, so this overrides only `FRONTEND_URL` and leaves the rest of the chart's config (`MONGO_URI`, `OPAMP_SERVER_URL`, ports, …) intact.

## Keeping the tailnet name out of git (the rule)

Never hardcode the tailnet name. Two mechanisms do this for you:

- **The Ingress** sets only `tls.hosts: [hyperdx]`. The Tailscale operator appends the tailnet suffix at runtime — the full hostname never appears in the manifest.
- **`FRONTEND_URL`** uses `${TAILNET_SUFFIX}`, a key in the SOPS-encrypted `cluster-secrets` Secret, substituted by Flux `postBuild.substituteFrom` at apply time. This is the same pattern `observability/ntfy` uses (`base-url: "https://ntfy.${TAILNET_SUFFIX}"`). The `clickstack-app` Kustomization already carries `postBuild.substituteFrom: cluster-secrets`, so the variable resolves with no extra wiring.

The literal hostname only ever exists in the **live cluster** (ConfigMap, pod env, Ingress status) — never in the repo.

## Find the live URL at runtime (don't hardcode it)

```sh
kubectl get ingress hyperdx -n clickstack            # ADDRESS column = hyperdx.<tailnet-name>.ts.net
kubectl get pods -n tailscale | grep ts-hyperdx       # the operator-provisioned proxy pod
tailscale status | grep -i hyperdx                     # the tailnet device + IP (run on a tailnet client)
```

## Verify access end-to-end

```sh
# 1. FRONTEND_URL resolved correctly in the live pod (expect the tailnet origin, NOT localhost)
kubectl exec -n clickstack deploy/clickstack-app -c app -- printenv FRONTEND_URL

# 2. UI + login serve over the tailnet with no localhost bounce (run from a tailnet client)
URL="https://$(kubectl get ingress hyperdx -n clickstack -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
curl -sS -o /dev/null -w "%{http_code} final=%{url_effective}\n" -L "$URL/login"   # expect 200, stays on the tailnet host
```

A correct result is HTTP 200 on `/login` whose final URL stays on `hyperdx.<tailnet-name>.ts.net` — no `localhost` in any `Location` header or in the served page.

## Gotchas

- **`FRONTEND_URL` changes need a pod restart.** It's an env var from the `clickstack-config` ConfigMap and is not hot-reloaded. After any change: `kubectl rollout restart deploy/clickstack-app -n clickstack`.
- **There is only one `FRONTEND_URL`.** We canonicalized on the tailnet origin because access is via Tailscale, so the on-LAN `envoy-internal` route (`hyperdx.${SECRET_DOMAIN}`) now redirects login to the tailnet origin. If you switch to primarily on-LAN use, set `FRONTEND_URL` to `https://hyperdx.${SECRET_DOMAIN}` instead — you can't have both.
- **Two exposure paths now exist** — the `envoy-internal` HTTPRoute (LAN) and this Tailscale Ingress (tailnet) — both internal, neither public. ADR 0028's body says "envoy-internal HTTPRoute only"; the Tailscale Ingress is a same-spirit internal addition (the operator wanted off-LAN access) and is flagged in the experiment doc note to record at the 2026-08-02 review.
- **Teardown:** removing `hyperdx-tailscale-ingress` deregisters the MagicDNS name and removes the `ts-hyperdx-*` proxy pod. It's part of the full exit runbook in [maintenance](maintenance.md#exit--teardown-runbook).

## Manifest pointers

- Tailscale Ingress: `kubernetes/apps/clickstack/hyperdx-tailscale-ingress/{ks.yaml, app/ingress.yaml}`
- `FRONTEND_URL`: `kubernetes/apps/clickstack/clickstack-app/app/helmrelease.yaml` (`spec.values.hyperdx.config`)
- The `${TAILNET_SUFFIX}` source: `kubernetes/components/sops/cluster-secrets.sops.yaml` (encrypted) — also used by `observability/ntfy`
