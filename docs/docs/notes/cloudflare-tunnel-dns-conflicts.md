# Cloudflare Tunnel DNS Conflicts

Triage and recovery for the failure mode where a hostname looks correctly deployed in Kubernetes but returns Cloudflare error 1033 / HTTP 530 to the public. Caused by a stale or foreign DNS record at Cloudflare that `external-dns` refuses to overwrite.

## Symptom

You just applied an `HTTPRoute` and `DNSEndpoint` for `myapp.example.com`, the cluster reports everything healthy (`HTTPRoute Accepted=True`, app pods Ready, app's own `/api/health` returns 200 in-cluster), but a public request fails:

```sh
$ curl -I https://myapp.example.com/
HTTP/2 530
```

The response body contains `error code: 1033`. Cloudflare's edge is reporting "Argo Tunnel error — the tunnel that this hostname routes to isn't connected (or there's no route for this hostname)."

The cluster-side `cloudflare-tunnel` pod is running fine; `kubectl logs` on it shows no recent errors. **The request never reaches it.**

## Root cause

`external-dns` in this cluster runs with `txtPrefix: k8s.` and `txtOwnerId: default`. It claims ownership of a DNS record by writing a sibling `TXT` record at `k8s.cname-<hostname>` containing `external-dns/owner=default`. Under `policy: sync`, it will only modify or delete records it owns — foreign records (no marker) are silently left alone.

The mode of failure:

1. Some prior infrastructure created a CNAME at `myapp.example.com` pointing to a different tunnel UUID — typically because the app was previously deployed with its own per-app `cloudflared` sidecar, and adding a "Public Hostname" entry to that tunnel in Cloudflare's Zero Trust dashboard auto-creates a CNAME bound to that tunnel's `cfargotunnel.com` endpoint.
2. The previous deploy was decommissioned. The app is gone, but **the tunnel registration, the Public Hostname mapping, and the auto-created CNAME all remain** unless explicitly cleaned up.
3. A new deploy lands today. The new `DNSEndpoint` (which would publish `myapp.example.com` → `external.example.com` → live shared tunnel) is processed, but `external-dns` sees the foreign CNAME and refuses to overwrite it.
4. Public requests follow the foreign CNAME to a tunnel that has 0 active connections. Cloudflare's edge can't establish a path → 1033.

The decision to skip foreign records is logged at debug level only, so at default INFO log level the failure is **silent** — nothing in the cluster reports a problem.

## Diagnostic recipe

### Step 1: confirm the request isn't reaching cloudflared

```sh
# How many log lines has the in-cluster cloudflared written recently?
POD=$(kubectl -n network get pods -l app.kubernetes.io/name=cloudflare-tunnel \
  --field-selector=status.phase=Running -o name | head -1)
kubectl -n network logs $POD --since=5m | wc -l
```

If the count is suspiciously low (say `< 5` after you've sent a handful of failing requests), the request isn't even reaching cloudflared — strong signal that DNS routes elsewhere.

### Step 2: query Cloudflare DNS records directly

`dig` is misleading for orange-cloud-proxied records — Cloudflare returns its own anycast IPs regardless of the underlying record type. Query the Cloudflare API directly:

```sh
TOKEN=$(kubectl -n network get secret cloudflare-dns-secret -o jsonpath='{.data.api-token}' | base64 -d)
ZONE_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=example.com" \
  | jq -r '.result[0].id')

curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?name=myapp.example.com" \
  | jq -r '.result[] | "\(.type)\t\(.name)\t→ \(.content)\tproxied=\(.proxied)"'
```

You're looking for one of three outcomes:

| Result | What it means |
|---|---|
| Record exists, `content` ends in `external.<your-domain>` (or its tunnel-target `cfargotunnel.com`) | Healthy. Look elsewhere for the failure (HTTPRoute, certs, app). |
| Record exists, `content` is a different `<uuid>.cfargotunnel.com` | **Conflict.** The hostname is bound to a foreign tunnel. This is the case this note is about. |
| No record returned | `external-dns` hasn't published yet. Check its logs: `kubectl -n network logs deploy/cloudflare-dns --tail=100`. |

### Step 3: identify the orphan tunnel

If you found a foreign `cfargotunnel.com` target:

```sh
cloudflared tunnel list | grep <uuid-prefix-from-the-CNAME>
```

The `CONNECTIONS` column tells you whether anything is currently serving that tunnel. An empty connections list means the tunnel is registered but offline — no app is on the other side.

### Step 4: cross-check that `external-dns` is not silently skipping

```sh
kubectl -n network get dnsendpoint -A | grep myapp
kubectl -n network logs deploy/cloudflare-dns --since=10m | grep -i myapp
```

`external-dns` logs at INFO level only show records it actively created or deleted. If the DNSEndpoint exists in the cluster but no log line references it, that's the smoking gun for "skipped because foreign owner."

## Recovery

Once you've confirmed the foreign CNAME is the cause:

```sh
# 1. Delete the stale record via the Cloudflare API
TOKEN=$(kubectl -n network get secret cloudflare-dns-secret -o jsonpath='{.data.api-token}' | base64 -d)
ZONE_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=example.com" | jq -r '.result[0].id')
RECORD_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?type=CNAME&name=myapp.example.com" \
  | jq -r '.result[0].id')

curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/$RECORD_ID" | jq '.success'

# 2. Wait for external-dns to publish its own (≤ 60 s — its sync loop is 1 min)
until curl -s -H "Authorization: Bearer $TOKEN" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?type=CNAME&name=myapp.example.com" \
    | jq -e '.result[0].content == "external.example.com"' >/dev/null; do
  echo "$(date +%H:%M:%S) waiting..."; sleep 15
done

# 3. Test
curl -sI https://myapp.example.com/
```

`external-dns` will publish the correct CNAME within one sync loop (≤ 60 s). The next request lands on the live shared tunnel.

If you also want to remove the orphan tunnel itself:

```sh
cloudflared tunnel delete <orphan-tunnel-name-or-uuid>
```

Cloudflare will refuse to delete a tunnel that still has `cfargotunnel.com` routes pointing to it via DNS — clean those up first.

## Prevention

### Pre-flight check before adding any new public hostname

Before you `kubectl apply` an `HTTPRoute` or `DNSEndpoint` for a brand-new hostname, run:

```sh
TOKEN=$(kubectl -n network get secret cloudflare-dns-secret -o jsonpath='{.data.api-token}' | base64 -d)
ZONE_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=example.com" | jq -r '.result[0].id')
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?name=myapp.example.com" \
  | jq '.result[] | {type, name, content, proxied}'
```

If the result is non-empty and the `content` is anything other than `external.<your-domain>`, you've found the conflict before it bites.

### Decommission checklist

When retiring an app that previously had its own DNS or its own tunnel, walk this list before declaring it gone:

```
[ ] kubectl delete the app's manifests
[ ] If the app had its own tunnel:
    cloudflared tunnel delete <name>
[ ] If the app had its own DNS records (created via Zero Trust dashboard or
    via a DNSEndpoint that external-dns no longer manages):
    delete them in Cloudflare dashboard or via the API
[ ] Revoke any 1Password tokens specific to the app's tunnel or registry
[ ] Verify no orphan: cloudflared tunnel list | grep <name>
[ ] Verify no orphan DNS: list zone records and check for foreign cfargotunnel.com targets
```

### Architectural choice: shared tunnel only

Anton's policy is one cloudflared tunnel for the entire cluster — see the relevant ADR. Per-app sidecar tunnels are forbidden because every one of them becomes a future orphan with a corresponding foreign CNAME. The shared tunnel + `HTTPRoute` + `DNSEndpoint` pattern in `hosting-apps-outside-flux.md` and `adding-a-2nd-domain.md` is the only supported public-ingress shape.

### Periodic Cloudflare zone audit (defense-in-depth)

A monthly scheduled agent that walks each Cloudflare zone, finds DNS records pointing to `*.cfargotunnel.com` whose tunnel UUID isn't in the current `cloudflared tunnel list` active set, and reports them. Catches drift you missed at decommission time. Not a substitute for the pre-flight check or the decommission checklist — those prevent the failure; this catches it after the fact.

## Related notes

- [Hosting apps outside Flux](./hosting-apps-outside-flux.md) — the imperative kubectl pattern that depends on the shared tunnel + wildcard cert.
- [Adding a 2nd domain](./adding-a-2nd-domain.md) — how the shared tunnel gets extended for a new top-level domain. Same `external-dns` ownership model applies.
