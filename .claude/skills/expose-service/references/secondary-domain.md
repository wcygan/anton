# Secondary domain: DNSEndpoint + per-domain certificates

For an app whose hostname lives on `${SECRET_DOMAIN_TWO}` (or any non-primary domain), an HTTPRoute alone is **not** enough. Two things must be wired up: DNS and TLS.

## The DNSEndpoint trap (required)

`external-dns` in this cluster is started with `--gateway-name=envoy-external` and a `domainFilters` list scoped to a single primary domain. Hostnames on any other domain are silently ignored — the HTTPRoute is accepted, but no DNS record is ever created, so the host never resolves externally.

**Fix:** add an explicit `DNSEndpoint` resource alongside the HTTPRoute. `external-dns` reads `DNSEndpoint` CRs directly and bypasses the gateway-name filter.

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

Add `- ./dnsendpoint.yaml` to the app's `kustomization.yaml`. Background walk-through: `docs/docs/notes/adding-a-2nd-domain.md`.

## Per-domain certificates

Each domain needs its own wildcard certificate via cert-manager. The gateway attaches certs by listing them under `listeners[].tls.certificateRefs`. Secret naming convention: `${SECRET_DOMAIN/./-}-production-tls` (e.g. `example-com-production-tls`).

### If the cert for the second domain already exists

Check `kubernetes/apps/network/envoy-gateway/app/envoy.yaml` → the `envoy-external` Gateway's `listeners[name=https].tls.certificateRefs` should already list both domains. If yes, no cert work is needed — just the HTTPRoute + DNSEndpoint.

### If you are adding a brand-new second domain

1. Add a second `Certificate` resource for `${SECRET_DOMAIN_TWO}` next to the primary one in `kubernetes/apps/network/envoy-gateway/app/certificate.yaml`.
2. Add a second `tls.certificateRefs` entry to the gateway's HTTPS listener (`envoy-external`, and `envoy-internal` if the second domain should resolve on LAN too) pointing at `${SECRET_DOMAIN_TWO/./-}-production-tls`.
3. Verify: `kubectl get certificate -n network` — both should report `Ready=True`.

Missing this step means the gateway terminates TLS with the primary domain's cert and the browser shows a `SSL_ERROR_BAD_CERT_DOMAIN` / name-mismatch warning for the secondary host.

## Quick diagnosis

| Symptom | Likely cause |
| --- | --- |
| `NXDOMAIN` for the secondary host on public DNS | Missing `DNSEndpoint` (external-dns ignored the HTTPRoute) |
| Resolves, but browser warns about cert | Gateway listener missing the second `certificateRefs` entry |
| `Certificate` is `Ready=False` | cert-manager issue — check the `ClusterIssuer` and Cloudflare API token |
