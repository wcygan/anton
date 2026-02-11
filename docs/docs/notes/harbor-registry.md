# Harbor Container Registry

Private container registry for the cluster, accessible on the LAN via Cilium LoadBalancer at `192.168.1.105`.

## Access

Harbor is exposed on the LAN at `http://192.168.1.105` (HTTP). The web UI is also available remotely via Tailscale at `https://registry.<tailnet-name>.ts.net`.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Cilium LoadBalancer                         │
│          192.168.1.105 (LAN-accessible, HTTP)               │
│         Docker push/pull + auth realm endpoint              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                  Tailscale Ingress                           │
│            (TLS termination, web UI only)                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Harbor Components                        │
│  ┌─────────┐  ┌──────┐  ┌────────────┐  ┌──────────────┐    │
│  │ Portal  │  │ Core │  │ JobService │  │   Registry   │    │
│  │ (2 rep) │  │(2rep)│  │  (2 rep)   │  │   (2 rep)    │    │
│  └─────────┘  └──────┘  └────────────┘  └──────────────┘    │
│                              │                              │
│                    ┌─────────┴─────────┐                    │
│                    ▼                   ▼                    │
│           ┌──────────────┐    ┌──────────────┐              │
│           │    Trivy     │    │   Storage    │              │
│           │  (scanning)  │    │ (Ceph 100Gi) │              │
│           └──────────────┘    └──────────────┘              │
└─────────────────────────────────────────────────────────────┘
                    │                   │
                    ▼                   ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│   PostgreSQL (CNPG)      │  │   DragonflyDB (Redis)    │
│   3 replicas, HA         │  │   3 replicas, HA         │
└──────────────────────────┘  └──────────────────────────┘
```

**Key design decisions:**

- **LoadBalancer exposure**: Cilium LB IPAM assigns 192.168.1.105, making Harbor's auth realm reachable from containerd on Talos nodes (host network)
- **External database**: CloudNative PG Operator provides HA PostgreSQL (3 replicas) instead of Harbor's internal database
- **External cache**: DragonflyDB Operator provides HA Redis-compatible cache (3 replicas) instead of Harbor's internal Redis
- **Ceph storage**: Registry images stored on `ceph-filesystem` (RWX) for multi-replica access
- **Tailscale Ingress preserved**: Web UI still accessible remotely via Tailscale for browsing and management

## Usage

### Docker Login

```bash
docker login 192.168.1.105
# Username: admin
# Password: (stored in SOPS secret)
```

**Note**: Requires Docker insecure registry config for HTTP. See [Harbor Developer Guide](./harbor-developer-guide.md).

### Push an Image

```bash
# Tag your image for the private registry
docker tag myapp:latest 192.168.1.105/library/myapp:latest

# Push to Harbor
docker push 192.168.1.105/library/myapp:latest
```

### Pull an Image

```bash
docker pull 192.168.1.105/library/myapp:latest
```

### Use in Kubernetes

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp
spec:
  containers:
    - name: myapp
      image: 192.168.1.105/library/myapp:latest
  imagePullSecrets:
    - name: harbor-pull
```

Create the pull secret:

```bash
kubectl create secret docker-registry harbor-pull-secret \
  --docker-server=192.168.1.105 \
  --docker-username=admin \
  --docker-password=<password> \
  -n <namespace>
```

## Vulnerability Scanning

Trivy is enabled for automatic vulnerability scanning. Images are scanned on push and results are visible in the Harbor UI.

## File Locations

| Component | Path |
|-----------|------|
| Harbor HelmRelease | `kubernetes/apps/harbor/harbor/app/helmrelease.yaml` |
| PostgreSQL Cluster | `kubernetes/apps/harbor/harbor-postgres/app/cluster.yaml` |
| DragonflyDB Cluster | `kubernetes/apps/harbor/harbor-redis/app/dragonfly.yaml` |
| Tailscale Ingress | `kubernetes/apps/harbor/harbor/app/ingress-tailscale.yaml` |
| Admin Secret (SOPS) | `kubernetes/apps/harbor/harbor/app/secret.sops.yaml` |

## Troubleshooting

### Check Harbor health

```bash
kubectl get pods -n harbor
kubectl get hr -n harbor
curl http://192.168.1.105/api/v2.0/health
```

### Check database connectivity

```bash
kubectl exec -n harbor deploy/harbor-core -- nc -zv harbor-postgres-rw.harbor.svc.cluster.local 5432
```

### Check Redis connectivity

```bash
kubectl exec -n harbor deploy/harbor-core -- nc -zv harbor-redis.harbor.svc.cluster.local 6379
```

### View Harbor logs

```bash
kubectl logs -n harbor -l app=harbor -c harbor-core --tail=100
```

## Cluster-Wide Image Pull Configuration

Harbor requires authentication for Docker pulls even from public projects. To simplify deployments, configure namespaces with a default imagePullSecret.

### Why This Is Needed

Harbor's "public" project setting only affects UI/API visibility, not the Docker Registry v2 API. All image pulls require authentication, regardless of project visibility.

### Setup with Robot Account

**Step 1**: Create a robot account in Harbor UI

1. Go to `https://registry.<tailnet-name>.ts.net` → Administration → Robot Accounts
2. Click "New Robot Account"
3. Name: `cluster-pull` (or similar)
4. Expiration: Never expire (or set appropriate duration)
5. Permissions: Select projects → Check "Pull Repository" only
6. Save and copy the generated token

**Step 2**: Create the secret in target namespaces

```bash
# Create secret (repeat for each namespace that needs Harbor access)
kubectl create secret docker-registry harbor-pull \
  --docker-server=192.168.1.105 \
  --docker-username='robot$cluster-pull' \
  --docker-password='<robot-token>' \
  -n <namespace>
```

**Step 3**: Attach to default ServiceAccount

```bash
# Patch default SA so all pods automatically get the secret
kubectl patch serviceaccount default -n <namespace> \
  -p '{"imagePullSecrets": [{"name": "harbor-pull"}]}'
```

### Verification

```bash
# Test without explicit imagePullSecrets in pod spec
kubectl run harbor-test \
  --image=192.168.1.105/library/myapp:latest \
  --restart=Never \
  -n <namespace> \
  --command -- sleep 30

# Check if pull succeeded
kubectl get pod harbor-test -n <namespace>
kubectl describe pod harbor-test -n <namespace> | grep -A5 Events
```

### Automating for New Namespaces

For GitOps-managed namespaces, add the secret and SA patch to the namespace's kustomization:

```yaml
# kubernetes/apps/<namespace>/harbor-pull/secret.sops.yaml
apiVersion: v1
kind: Secret
metadata:
  name: harbor-pull
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {"auths":{"192.168.1.105":{"username":"robot$cluster-pull","password":"<token>"}}}
```

Then patch the default ServiceAccount in a post-deploy hook or init container.
