# Layer 5 — Platform components

This is the silent-killer layer. Flux will report everything as healthy while one of these silently breaks an entire class of apps. Always probe each explicitly — `flux get` will not tell you.

## cert-manager

```sh
kubectl -n cert-manager get pods
kubectl get clusterissuers
kubectl get issuers -A
```

**Healthy**: `cert-manager`, `cert-manager-webhook`, `cert-manager-cainjector` all Running; `ClusterIssuer` resources show `Ready=True`.

**Check for stuck Certificates**:

```sh
kubectl get certificate -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,AGE:.metadata.creationTimestamp'
```

Any `Ready=False` row is a stuck issuance. cert-manager will retry on its own; if a Certificate has been `False` for more than an hour, drill into its `CertificateRequest`/`Order`/`Challenge` chain.

## External Secrets + ClusterSecretStore

**The #1 silent killer in this cluster.** If the store is not Ready, every ExternalSecret is frozen and no new data flows from 1Password.

```sh
kubectl -n external-secrets get pods
kubectl get clustersecretstore onepassword-connect -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
```

If it is not `True`:

```sh
kubectl describe clustersecretstore onepassword-connect
```

Common causes:
- 1Password service-account token expired or rotated without updating the referenced Secret → hand off to `rotate-credential`
- Network reachability to 1Password API broken (check cloudflared / outbound DNS)
- `onepassword-connect` Secret referenced by the store is missing entirely

**Check frozen ExternalSecrets** (those whose store is broken):

```sh
kubectl get externalsecret -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status' | grep -v True
```

## Envoy Gateway — the `Programmed` condition

**Silent killer.** An envoy Gateway can be `Accepted=True` but `Programmed=False` — meaning the config was parsed but never actually configured on the data plane. HTTPRoutes attach to it, look healthy, and serve no traffic.

```sh
kubectl get gateway -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,ACCEPTED:.status.conditions[?(@.type=="Accepted")].status,PROGRAMMED:.status.conditions[?(@.type=="Programmed")].status'
```

Any `Programmed=False` row is a silent outage.

```sh
# Then inspect the full condition set
kubectl describe gateway -A | less
```

Common causes:
- Listener port conflict with another Gateway
- TLS Secret referenced by the listener is missing or expired
- envoy-gateway controller pod is crash-looping — check `kubectl -n envoy-gateway-system get pods`

## Cloudflare tunnel

**Silent killer.** The pod runs fine, the Deployment is Ready, but the tunnel never re-registered with Cloudflare. You just fixed a QUIC→HTTP/2 regression in commit `42822fc3` — this failure mode is fresh in memory.

```sh
# Pod health
kubectl -n network get deploy cloudflare-tunnel
kubectl -n network get pods -l app.kubernetes.io/name=cloudflare-tunnel

# Registration and transport signals in retained logs
kubectl -n network logs deploy/cloudflare-tunnel --tail=100 | \
  grep -Ei 'Registered tunnel connection|ERR|connection refused|QUIC|http2'

# Current error pulse
kubectl -n network logs deploy/cloudflare-tunnel --since=6h | \
  grep -Ei 'ERR|connection refused'
```

**Healthy**: Deployment Ready, retained logs show `Registered tunnel connection` after pod start or reconnect, and the current error pulse is empty.

**If only `ERR` lines**: Cloudflare token may be expired → `rotate-credential`. Or the tunnel transport is blocked — the current workaround is HTTP/2 (set in the Helm values after the QUIC block); verify that is still the case.

## k8s-gateway (split-horizon DNS)

Handles `*.{cloudflare_domain}` lookups from the home network. If it is down, home-network clients get no answer for internal hostnames.

```sh
kubectl -n network get pods -l app.kubernetes.io/name=k8s-gateway
```

Quick resolution test from inside the cluster (you need to know the Service IP — it is `cluster_dns_gateway_addr` from `cluster.yaml`):

```sh
kubectl run -n default dnscheck --rm -it --restart=Never \
  --image=busybox:1.36 -- nslookup grafana.${CLOUDFLARE_DOMAIN} $(kubectl -n network get svc k8s-gateway -o jsonpath='{.spec.clusterIP}')
```

## 1Password Connect (if deployed in-cluster)

The ESO ClusterSecretStore talks to it. If the Connect pods are unhealthy, the store goes NotReady (see ESO section above).

```sh
kubectl -n external-secrets get pods -l app.kubernetes.io/name=onepassword-connect
```

## One-shot platform pulse

Paste this to get every silent-killer signal in one go:

```sh
echo "=== cert-manager ===" && kubectl -n cert-manager get pods
echo "=== ESO store ===" && kubectl get clustersecretstore onepassword-connect -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
echo "=== gateways ===" && kubectl get gateway -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,PROGRAMMED:.status.conditions[?(@.type=="Programmed")].status'
echo "=== cloudflare-tunnel ===" && kubectl -n network get deploy cloudflare-tunnel && kubectl -n network logs deploy/cloudflare-tunnel --tail=20 | grep -Ei 'Registered|ERR|http2|QUIC' | tail -5
```
