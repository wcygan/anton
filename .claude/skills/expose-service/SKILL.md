---
name: expose-service
description: Expose a service through Anton's envoy gateway. Use to expose service with an HTTPRoute, pick a public URL via cloudflare tunnel route or an internal hostname via k8s-gateway, and handle DNSEndpoint plus certificates for a second domain.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Expose a service

Task skill for routing traffic to a service via the envoy gateways. Architecture deep-dive (traffic flow, component dependencies, debug commands) lives in `kubernetes/apps/network/CLAUDE.md` — read that for the full picture; this skill is the authoring playbook.

## Gateway choice matrix

| Use case | Gateway | parentRef name | Hostname pattern | Reaches |
| --- | --- | --- | --- | --- |
| **Public URL** (anyone on internet) | `envoy-external` | `envoy-external` | `<app>.${SECRET_DOMAIN}` | Internet → Cloudflare tunnel → cluster |
| **Internal hostname** (home network only) | `envoy-internal` | `envoy-internal` | `<app>.${SECRET_DOMAIN}` (split-horizon) | LAN → k8s-gateway DNS → cluster |
| **Both public + internal** | both | two HTTPRoutes | different subdomains | one HTTPRoute per gateway |
| **App on second domain** (`${SECRET_DOMAIN_TWO}`) | `envoy-external` | `envoy-external` | `<app>.${SECRET_DOMAIN_TWO}` | **also requires explicit DNSEndpoint — see trap below** |

Both gateways live in namespace `network`. Cross-namespace ref is required: `parentRefs[].namespace: network`. Always set `sectionName: https` to attach to the TLS listener.

## Workflow A — standalone HTTPRoute file (always works)

Use this when the chart does not expose a `route:` schema (most charts), or when you want HTTPRoute decoupled from values.

1. Create `kubernetes/apps/<ns>/<app>/app/httproute.yaml`:
   ```yaml
   ---
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata:
     name: <app>
   spec:
     hostnames: ["<app>.${SECRET_DOMAIN}"]
     parentRefs:
       - name: envoy-external          # or envoy-internal
         namespace: network
         sectionName: https
     rules:
       - backendRefs:
           - name: <service-name>      # service in your app namespace
             port: 80
         matches:
           - path:
               type: PathPrefix
               value: /
   ```
2. Add to `app/kustomization.yaml`:
   ```yaml
   resources:
     - ./helmrelease.yaml
     - ./ocirepository.yaml
     - ./httproute.yaml
   ```
3. `task configure` to validate, then commit + push, then `task reconcile`.

## Workflow B — HTTPRoute inside HelmRelease values

Use only when the chart explicitly supports a `route:` schema (e.g. bjw-s `app-template`). Saves a file at the cost of coupling.

```yaml
spec:
  values:
    route:
      app:
        hostnames: ["{{ .Release.Name }}.${SECRET_DOMAIN}"]
        parentRefs:
          - name: envoy-external
            namespace: network
            sectionName: https
        rules:
          - backendRefs: [{identifier: app, port: 80}]
```

## The secondary-domain DNSEndpoint trap

For an app on `${SECRET_DOMAIN_TWO}` (or any non-primary domain), an HTTPRoute alone is **not enough**. external-dns is started with `--gateway-name=envoy-external` and a `domainFilters` list scoped to one domain at a time, so HTTPRoute hostnames on the secondary domain are silently ignored — DNS records never get created.

**Fix:** add an explicit `DNSEndpoint` resource alongside the HTTPRoute. external-dns reads `DNSEndpoint` CRs directly and bypasses the gateway-name filter.

```yaml
---
apiVersion: externaldns.k8s.io/v1alpha1
kind: DNSEndpoint
metadata:
  name: <app>
spec:
  endpoints:
    - dnsName: "<app>.${SECRET_DOMAIN_TWO}"
      recordType: CNAME
      targets: ["external.${SECRET_DOMAIN_TWO}"]
```

Add `- ./dnsendpoint.yaml` to `app/kustomization.yaml`. Background: `docs/docs/notes/adding-a-2nd-domain.md`.

## Certificates per domain

Each domain needs its own wildcard certificate sourced via cert-manager. The primary domain's cert is already wired up by `kubernetes/apps/network/envoy-gateway/app/certificate.yaml` and consumed by both gateways via the listener `tls.certificateRefs` block. Secret naming convention: `${SECRET_DOMAIN/./-}-production-tls`.

**For a second domain:**
1. Add a second `Certificate` resource for `${SECRET_DOMAIN_TWO}` next to the primary one (or in a sibling app dir).
2. Add a second `tls.certificateRefs` entry to the gateway's HTTPS listener pointing at `${SECRET_DOMAIN_TWO/./-}-production-tls`. Without this, the gateway terminates the connection with the primary cert and the browser shows a name-mismatch warning.
3. Verify: `kubectl get certificate -n network` → both should be `Ready=True`.

## Pre-commit checklist

- [ ] HTTPRoute `parentRefs[0].name` is `envoy-external` or `envoy-internal` (not a service name)
- [ ] HTTPRoute `parentRefs[0].namespace: network` is set (cross-namespace)
- [ ] HTTPRoute `parentRefs[0].sectionName: https` is set (attaches to TLS listener)
- [ ] `backendRefs[].name` matches an actual `Service` in the app's namespace
- [ ] If app is on `${SECRET_DOMAIN_TWO}` → `DNSEndpoint` resource present
- [ ] If new second-domain cert → gateway listener updated with the new `certificateRefs`
- [ ] HTTPRoute (and DNSEndpoint, if any) listed in `app/kustomization.yaml`
- [ ] `task configure` passes

## Verify after deploy

```sh
kubectl get httproute -A | rg <app>
kubectl get httproute -n <ns> <app> -o jsonpath='{.status.parents[*].conditions[?(@.type=="Accepted")].status}'
# expect: True

# DNS — primary domain via Cloudflare:
dig <app>.${SECRET_DOMAIN}

# DNS — internal split-horizon via k8s-gateway:
dig <app>.${SECRET_DOMAIN} @${cluster_dns_gateway_addr}

# End-to-end:
curl -I https://<app>.${SECRET_DOMAIN}
```

If DNS does not resolve for a public URL, check `kubectl logs -n network -l app.kubernetes.io/name=cloudflare-dns`. If the secondary domain returns the wrong cert, the gateway listener is missing the second `certificateRefs` entry.

## Related skills

- Architecture / traffic flow / debug commands → `kubernetes/apps/network/CLAUDE.md`
- Pattern reference for HelmRelease / ks.yaml → `anton-repo-conventions`
- Triaging an HTTPRoute that exists but the app is unreachable → `debug-flux-reconciliation`
