# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the network stack in this cluster.

## Project Overview

The network namespace contains 4 components that work together to route traffic to services. Understanding the 2 traffic paths (external and internal) is key to working with this stack.

**Simple mental model**:
- External traffic → Cloudflare Tunnel → envoy-external gateway → service
- Internal traffic → k8s-gateway DNS → envoy-internal gateway → service

## The 4 Components (One-Sentence Each)

### 1. envoy-gateway
**What it does**: Routes HTTP/HTTPS traffic to backend services via two separate gateways

**Key files**:
- `envoy-gateway/app/envoy.yaml` - Gateway definitions + policies
- `envoy-gateway/app/certificate.yaml` - TLS wildcard certificate

**Two gateways**:
- `envoy-external` (192.168.1.104) - Public internet traffic via Cloudflare
- `envoy-internal` (192.168.1.103) - Cluster-internal traffic

### 2. cloudflare-tunnel
**What it does**: Creates secure outbound tunnel from cluster to Cloudflare edge

**Key files**:
- `cloudflare-tunnel/app/helmrelease.yaml` - Tunnel agent configuration
- `cloudflare-tunnel/app/secret.sops.yaml` - TUNNEL_TOKEN (encrypted)
- `cloudflare-tunnel/app/dnsendpoint.yaml` - DNS CNAME record

**How it works**: Proxies all `*.${SECRET_DOMAIN}` requests back to envoy-external gateway

### 3. cloudflare-dns
**What it does**: Syncs HTTPRoute hostnames to Cloudflare DNS automatically

**Key files**:
- `cloudflare-dns/app/helmrelease.yaml` - external-dns controller
- `cloudflare-dns/app/secret.sops.yaml` - CF_API_TOKEN (encrypted)

**How it works**: Watches HTTPRoute resources, creates DNS records in Cloudflare

### 4. k8s-gateway
**What it does**: Provides DNS resolution for internal clients querying cluster services

**Key files**:
- `k8s-gateway/app/helmrelease.yaml` - DNS server configuration

**How it works**: LoadBalancer service on 192.168.1.102:53 that resolves `*.${SECRET_DOMAIN}` to gateway IPs

## Traffic Flow (2 Paths Only)

### Path 1: External Traffic (Internet → Cluster)

```
Internet Client
    ↓
Cloudflare DNS resolver
    ↓
CNAME: external.example.com → xyz.cfargotunnel.com
    ↓
Cloudflare Edge
    ↓
Cloudflare Tunnel (secure QUIC connection)
    ↓
cloudflare-tunnel pod in cluster
    ↓
envoy-external Gateway (192.168.1.104:443)
    ↓
HTTPRoute matches hostname + path
    ↓
Backend Service
```

**Key insight**: Traffic enters via tunnel, NOT direct to cluster. Cloudflare terminates public TLS, tunnel uses separate TLS to cluster.

### Path 2: Internal Traffic (Home Network → Cluster)

```
Internal Client (home network device)
    ↓
Home DNS server (forwards *.example.com queries)
    ↓
k8s-gateway (192.168.1.102:53)
    ↓
Returns: A record → 192.168.1.103 (envoy-internal)
    ↓
Client connects to 192.168.1.103:443
    ↓
envoy-internal Gateway
    ↓
HTTPRoute matches hostname + path
    ↓
Backend Service
```

**Key insight**: DNS resolves to internal gateway IP. Traffic stays within local network, never touches Cloudflare.

## How to Expose a New Service (3 Steps)

### Step 1: Create HTTPRoute

Create `app/httproute.yaml` in your application directory:

```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
spec:
  hostnames: ["my-app.${SECRET_DOMAIN}"]
  parentRefs:
    - name: envoy-external          # or envoy-internal for internal-only
      namespace: network
      sectionName: https
  rules:
    - backendRefs:
        - name: my-app-service       # Your service name
          port: 80                   # Your service port
```

**Gateway choice**:
- `envoy-external` - Accessible via internet (through Cloudflare tunnel)
- `envoy-internal` - Accessible only from home network (split-horizon DNS)

### Step 2: Add to kustomization

Edit `app/kustomization.yaml`:
```yaml
resources:
  - ./helmrelease.yaml
  - ./ocirepository.yaml
  - ./httproute.yaml  # Add this line
```

### Step 3: Apply and verify

```bash
# Render and validate
task configure

# Commit and push
git add -A && git commit -m "feat: expose my-app via HTTPRoute"
git push

# Verify HTTPRoute created
kubectl get httproute -n {namespace}

# Verify DNS record (if external)
dig my-app.example.com

# Test access
curl https://my-app.example.com
```

## Gateway Configuration Deep Dive

### envoy-external (Public Internet)

**IP Address**: 192.168.1.104 (from `${cloudflare_gateway_addr}`)

**DNS**: `external.${SECRET_DOMAIN}` → used as tunnel target

**Listeners**:
- HTTP:80 - Redirects to HTTPS (301)
- HTTPS:443 - Routes to services

**TLS**: Wildcard certificate `*.${SECRET_DOMAIN}` from cert-manager

**Configuration** (kubernetes/apps/network/envoy-gateway/app/envoy.yaml:1):
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: envoy-external
  annotations:
    lbipam.cilium.io/ips: "192.168.1.104"  # Fixed IP assignment
    external-dns.alpha.kubernetes.io/hostname: external.${SECRET_DOMAIN}
spec:
  gatewayClassName: envoy
  listeners:
    - name: http
      port: 80
      protocol: HTTP
    - name: https
      port: 443
      protocol: HTTPS
      tls:
        certificateRefs:
          - name: ${SECRET_DOMAIN/./-}-production-tls
```

### envoy-internal (Home Network)

**IP Address**: 192.168.1.103 (from `${cluster_gateway_addr}`)

**DNS**: `internal.${SECRET_DOMAIN}` → resolved by k8s-gateway

**Listeners**: Same as envoy-external (HTTP:80, HTTPS:443)

**TLS**: Same wildcard certificate

**Use case**: Services that should NOT be exposed to internet (admin panels, internal dashboards, development services)

## DNS Resolution Strategy (Split-Horizon)

**Problem**: Same hostname (`app.example.com`) needs to resolve differently based on client location:
- External clients → Cloudflare IP (via tunnel)
- Internal clients → Internal gateway IP (direct)

**Solution**: Split-horizon DNS via k8s-gateway

### External Resolution (via Cloudflare)
```bash
$ dig app.example.com @1.1.1.1
;; ANSWER SECTION:
app.example.com.  300  IN  CNAME  external.example.com.
external.example.com.  300  IN  CNAME  xyz.cfargotunnel.com.
xyz.cfargotunnel.com.  300  IN  A  104.16.x.x  # Cloudflare edge IP
```

### Internal Resolution (via k8s-gateway)
```bash
$ dig app.example.com @192.168.1.102
;; ANSWER SECTION:
app.example.com.  1  IN  A  192.168.1.103  # envoy-internal gateway
```

**How to configure your home DNS**:
1. Forward `*.${SECRET_DOMAIN}` queries to 192.168.1.102 (k8s-gateway)
2. All other queries to upstream DNS (e.g., 1.1.1.1)
3. Internal clients get internal IPs, external clients get Cloudflare

## Variable Flow from cluster.yaml

Network components use 4 IP addresses from `cluster.yaml`:

**In cluster.yaml**:
```yaml
cluster_api_addr: "192.168.1.101"              # Kubernetes API
cluster_dns_gateway_addr: "192.168.1.102"      # k8s-gateway DNS
cluster_gateway_addr: "192.168.1.103"          # envoy-internal
cloudflare_gateway_addr: "192.168.1.104"       # envoy-external
cloudflare_domain: "example.com"               # Primary domain
```

**Usage by component**:

| Component | Uses | For |
|-----------|------|-----|
| k8s-gateway | `cluster_dns_gateway_addr` | LoadBalancer IP (DNS server) |
| envoy-gateway | `cluster_gateway_addr` | envoy-internal gateway IP |
| envoy-gateway | `cloudflare_gateway_addr` | envoy-external gateway IP |
| cloudflare-tunnel | `cloudflare_domain` | Domain to proxy (ingress rules) |
| cloudflare-dns | `cloudflare_domain` | Domain filter (only manage these domains) |

**Flow**:
```
cluster.yaml
    ↓
task configure (Jinja2 → Flux variables)
    ↓
${SECRET_DOMAIN}, ${KUBERNETES_API_ADDR}, etc.
    ↓
Flux postBuild substitution
    ↓
Actual values in manifests
```

## TLS Certificate Management

**Single wildcard certificate** shared by both gateways:
- Common Name: `${SECRET_DOMAIN}`
- SANs: `*.${SECRET_DOMAIN}`, `${SECRET_DOMAIN}`

**Managed by** cert-manager with Let's Encrypt:
- Issuer: `letsencrypt-production`
- Challenge: HTTP-01 or DNS-01 (depends on ClusterIssuer config)
- Auto-renewal: 60 days before expiry

**Certificate resource** (kubernetes/apps/network/envoy-gateway/app/certificate.yaml:1):
```yaml
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: ${SECRET_DOMAIN/./-}-production
spec:
  secretName: ${SECRET_DOMAIN/./-}-production-tls
  issuerRef:
    name: letsencrypt-production
    kind: ClusterIssuer
  commonName: "${SECRET_DOMAIN}"
  dnsNames:
    - "${SECRET_DOMAIN}"
    - "*.${SECRET_DOMAIN}"
```

**Secret name**: Dots replaced with dashes (e.g., `example-com-production-tls`)

## Common Network Tasks

### Task 1: Add external domain to Cloudflare DNS

**When**: You want external-dns to manage additional domains

**Steps**:
```bash
# 1. Edit cloudflare-dns HelmRelease
# Add domain to domainFilters array
# File: kubernetes/apps/network/cloudflare-dns/app/helmrelease.yaml

# 2. Render and apply
task configure
git add -A && git commit -m "feat: add domain to cloudflare-dns"
git push
```

### Task 2: Change gateway IP addresses

**When**: IP conflicts or network restructuring

**Steps**:
```bash
# 1. Edit cluster.yaml
# Change cluster_gateway_addr or cloudflare_gateway_addr

# 2. Re-render manifests
task configure

# 3. Commit and push
git add -A && git commit -m "chore: update gateway IPs"
git push

# 4. Flux reconciles automatically (or force)
task reconcile
```

### Task 3: Block external access to a service

**When**: Service should be internal-only

**Options**:

**Option A**: Change HTTPRoute to use envoy-internal
```yaml
parentRefs:
  - name: envoy-internal  # Changed from envoy-external
```

**Option B**: Delete HTTPRoute entirely
```bash
rm kubernetes/apps/{namespace}/{app}/app/httproute.yaml
# Remove from app/kustomization.yaml resources
```

### Task 4: Add service to both internal and external

**When**: Service accessible from both internet and home network

**Steps**: Create 2 HTTPRoutes with different parent gateways:

```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-external
spec:
  hostnames: ["my-app.${SECRET_DOMAIN}"]
  parentRefs:
    - name: envoy-external
      namespace: network
      sectionName: https
  rules:
    - backendRefs:
        - name: my-app
          port: 80
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-internal
spec:
  hostnames: ["my-app.internal.${SECRET_DOMAIN}"]  # Different subdomain
  parentRefs:
    - name: envoy-internal
      namespace: network
      sectionName: https
  rules:
    - backendRefs:
        - name: my-app
          port: 80
```

### Task 5: Debug DNS resolution

**Check external DNS**:
```bash
# Query Cloudflare DNS
dig app.example.com @1.1.1.1

# Check external-dns logs
kubectl logs -n network -l app.kubernetes.io/name=cloudflare-dns

# Verify DNS records in Cloudflare API
# (Check cloudflare-dns created them)
```

**Check internal DNS**:
```bash
# Query k8s-gateway
dig app.example.com @192.168.1.102

# Check k8s-gateway logs
kubectl logs -n network -l app.kubernetes.io/name=k8s-gateway

# Verify HTTPRoute exists
kubectl get httproute -A
```

## Debugging Network Stack

### Check Gateway status
```bash
# Gateway resources
kubectl get gateway -n network

# Envoy proxy pods
kubectl get pods -n network -l gateway.envoy.io/owning-gateway-name=envoy-external

# Gateway details
kubectl describe gateway -n network envoy-external
```

### Check HTTPRoute status
```bash
# All HTTPRoutes
kubectl get httproute -A

# Specific HTTPRoute
kubectl describe httproute -n {namespace} {name}

# Check if route is accepted by gateway
kubectl get httproute -n {namespace} {name} -o jsonpath='{.status.parents[*].conditions[?(@.type=="Accepted")].status}'
```

### Check Cloudflare Tunnel
```bash
# Tunnel pod logs
kubectl logs -n network -l app.kubernetes.io/name=cloudflare-tunnel

# Verify tunnel config
kubectl get secret -n network cloudflare-tunnel-secret -o jsonpath='{.data.TUNNEL_TOKEN}' | base64 -d

# Check tunnel connectivity
kubectl exec -n network deploy/cloudflare-tunnel -- curl -I https://envoy-external.network.svc.cluster.local
```

### Check TLS certificates
```bash
# Certificate status
kubectl get certificate -n network

# Certificate details
kubectl describe certificate -n network ${SECRET_DOMAIN/./-}-production

# Check secret exists
kubectl get secret -n network ${SECRET_DOMAIN/./-}-production-tls

# View certificate
kubectl get secret -n network ${SECRET_DOMAIN/./-}-production-tls -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout
```

### Common issues and fixes

| Issue | Symptom | Fix |
|-------|---------|-----|
| **503 Service Unavailable** | HTTPRoute exists but returns 503 | Check backend service exists and has endpoints |
| **DNS not resolving** | `dig` returns NXDOMAIN | Verify HTTPRoute created, check k8s-gateway/cloudflare-dns logs |
| **TLS certificate error** | Browser shows certificate warning | Check certificate status, verify cert-manager issued cert |
| **Tunnel disconnected** | External access broken | Check cloudflare-tunnel pod logs, verify TUNNEL_TOKEN |
| **Gateway not ready** | HTTPRoute shows "Gateway not found" | Check Envoy pods running, verify Gateway resource exists |

## Component Dependencies

```
cert-manager ClusterIssuer
    ↓
Certificate resource
    ↓
Secret: *-production-tls
    ↓
Gateway resources (envoy-external, envoy-internal)
    ↓
HTTPRoute resources (reference Gateways)
    ↓
cloudflare-dns watches HTTPRoutes
    ↓
Creates DNS records in Cloudflare
    ↓
cloudflare-tunnel proxies to envoy-external
```

**Startup order**:
1. cert-manager issues certificate → Secret created
2. envoy-gateway deploys → Gateways created with TLS
3. k8s-gateway deploys → DNS server ready
4. cloudflare-dns deploys → Watches HTTPRoutes
5. cloudflare-tunnel deploys → Connects to Cloudflare edge
6. Apps create HTTPRoutes → DNS records auto-created

## Key Insights

1. **Two gateways, two traffic paths** - External via tunnel, internal via DNS
2. **Single certificate** - Both gateways use same wildcard cert
3. **Split-horizon DNS** - Same hostname resolves differently based on client
4. **HTTPRoute is the interface** - Apps don't configure networking directly
5. **Cloudflare tunnel is outbound** - Cluster initiates connection to CF, not inbound
6. **DNS is automatic** - cloudflare-dns syncs HTTPRoutes to Cloudflare API
7. **IPs are fixed** - Gateways use Cilium LBIPAM for consistent addresses

## Quick Reference

| Command | Purpose |
|---------|---------|
| `kubectl get gateway -n network` | Check gateway status |
| `kubectl get httproute -A` | List all exposed services |
| `dig @192.168.1.102 app.example.com` | Test internal DNS |
| `dig @1.1.1.1 app.example.com` | Test external DNS |
| `kubectl logs -n network -l app.kubernetes.io/name=cloudflare-tunnel` | Tunnel logs |
| `kubectl get certificate -n network` | Check TLS certificates |
