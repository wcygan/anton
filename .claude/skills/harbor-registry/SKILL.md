---
name: harbor-registry
description: Push and pull container images with the private Harbor registry at 192.168.1.105. Covers Docker build/tag/push, Kubernetes imagePullSecrets, deployment specs, and troubleshooting image pull failures. Use when working with Harbor, pushing Docker images, pulling private images, setting up imagePullSecrets, or debugging ImagePullBackOff errors. Keywords: harbor, docker push, docker pull, registry, image, container, imagePullSecret, ImagePullBackOff, unauthorized
---

# Harbor Registry

Push, pull, and deploy container images using the private Harbor registry.

## Cluster Registry Details

- **Registry IP**: `192.168.1.105` (Cilium LoadBalancer, HTTP)
- **Protocol**: HTTP (requires Docker insecure registry config)
- **Default project**: `library` (public visibility, auth still required)
- **Web UI**: `https://registry.<tailnet-name>.ts.net` (via Tailscale, remote access)
- **In-cluster pull path**: containerd mirrors to ClusterIP (10.43.216.243) for ~100ms pulls

## Instructions

### 1. Gather Information

Use AskUserQuestion to collect:

**Question 1 - What do you need?**
- "Push an image" — walk through build/tag/push
- "Pull in Kubernetes" — set up imagePullSecrets and deployment
- "Full pipeline" — both push and Kubernetes deployment
- "Troubleshoot" — diagnose image pull failures

**Question 2 - Application name**: "What is your application/image name?"

**Question 3 - Build machine** (only if pushing):
- "ARM Mac (M1/M2/M3/M4)" — MUST use `--platform linux/amd64`
- "Intel Mac / Linux x86_64" — no platform flag needed

### 2. Docker Push Workflow

#### Prerequisites (one-time)

**Docker Desktop insecure registry config** — Harbor is HTTP, Docker requires opt-in:

```json
// Docker Desktop → Settings → Docker Engine → add:
{
  "insecure-registries": ["192.168.1.105"]
}
```

Then restart Docker Desktop.

**Login**:

```bash
docker login 192.168.1.105
# Username: admin (or your username)
# Password: (from cluster admin or Harbor UI)
```

#### Build and Push

**ARM Mac (M1/M2/M3/M4)** — cluster nodes are amd64:

```bash
docker build --platform linux/amd64 -t <app>:<tag> .
docker tag <app>:<tag> 192.168.1.105/library/<app>:<tag>
docker push 192.168.1.105/library/<app>:<tag>
```

**Intel Mac / Linux x86_64**:

```bash
docker build -t <app>:<tag> .
docker tag <app>:<tag> 192.168.1.105/library/<app>:<tag>
docker push 192.168.1.105/library/<app>:<tag>
```

#### Verify push succeeded

```bash
curl -s http://192.168.1.105/v2/library/<app>/tags/list | jq .
```

### 3. Kubernetes Deployment

#### Image reference in pod specs

```yaml
image: 192.168.1.105/library/<app>:<tag>
```

#### imagePullSecret setup

Harbor requires auth even for public projects. Create a pull secret per namespace:

```bash
kubectl create secret docker-registry harbor-pull \
  --docker-server=192.168.1.105 \
  --docker-username='robot$cluster-pull' \
  --docker-password='<robot-token>' \
  -n <namespace>
```

Get the robot token from the cluster admin or Harbor UI (Administration → Robot Accounts).

#### Attach to default ServiceAccount (auto-pull for all pods)

```bash
kubectl patch serviceaccount default -n <namespace> \
  -p '{"imagePullSecrets": [{"name": "harbor-pull"}]}'
```

#### Deployment example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <app>
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <app>
  template:
    metadata:
      labels:
        app: <app>
    spec:
      containers:
        - name: <app>
          image: 192.168.1.105/library/<app>:<tag>
      imagePullSecrets:
        - name: harbor-pull
```

#### GitOps imagePullSecret (for Flux-managed namespaces)

Use the `/create-secret` skill to create an ExternalSecret that pulls Harbor robot credentials from 1Password, or create a SOPS-encrypted secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: harbor-pull
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {"auths":{"192.168.1.105":{"username":"robot$cluster-pull","password":"<token>"}}}
```

### 4. Verify End-to-End

```bash
# Check image exists in Harbor
curl -s http://192.168.1.105/v2/library/<app>/tags/list | jq .

# Test in-cluster pull
kubectl run harbor-test \
  --image=192.168.1.105/library/<app>:<tag> \
  --restart=Never \
  -n <namespace> \
  --command -- sleep 30

# Verify pull succeeded (should show ~100ms for cached images)
kubectl describe pod harbor-test -n <namespace> | grep -A 5 Events

# Clean up
kubectl delete pod harbor-test -n <namespace>
```

### 5. Troubleshooting

Run these checks when image pulls fail:

#### ImagePullBackOff / ErrImagePull

```bash
# Get the exact error
kubectl describe pod <pod-name> -n <namespace> | grep -A 10 Events

# Check if image exists
curl -s http://192.168.1.105/v2/library/<app>/tags/list | jq .

# Check Harbor health
curl -s http://192.168.1.105/api/v2.0/health | jq .
```

| Error | Cause | Fix |
|-------|-------|-----|
| `unauthorized` | Missing or wrong credentials | Create/update imagePullSecret, verify robot account |
| `not found` | Wrong image name or tag | Check exact repo path and tag in Harbor UI |
| `exec format error` | Built for wrong architecture | Rebuild with `--platform linux/amd64` |
| `connection refused` | Harbor service down | `kubectl get pods -n harbor`, check HelmRelease |
| Pull hangs (>30s) | Mirror misconfigured | Check `talosctl -n <node-ip> read /etc/cri/conf.d/hosts/192.168.1.105/hosts.toml` |

#### Advanced diagnostics

```bash
# Check containerd mirror config on a node
talosctl -n 192.168.1.98 read /etc/cri/conf.d/hosts/192.168.1.105/hosts.toml

# Check auth realm is reachable
curl -sI http://192.168.1.105/v2/ | grep -i www-authenticate

# List all repos in Harbor
curl -s -u admin:<password> http://192.168.1.105/v2/_catalog | jq .

# Check Harbor service
kubectl get svc -n harbor harbor
```

### 6. Off-LAN Push (Fallback)

When not on the cluster LAN, use kubectl port-forward:

```bash
# Terminal 1
kubectl port-forward svc/harbor -n harbor 8080:80

# Terminal 2
docker tag <app>:<tag> localhost:8080/library/<app>:<tag>
docker push localhost:8080/library/<app>:<tag>
```

## Quick Reference Card

Always provide this at the end:

```bash
# === Prerequisites (one-time) ===
# Add "192.168.1.105" to Docker insecure-registries, restart Docker
docker login 192.168.1.105

# === Build and push ===
docker build --platform linux/amd64 -t <app>:<tag> .
docker tag <app>:<tag> 192.168.1.105/library/<app>:<tag>
docker push 192.168.1.105/library/<app>:<tag>

# === Kubernetes ===
# Image ref:  192.168.1.105/library/<app>:<tag>
# Pull secret: kubectl create secret docker-registry harbor-pull \
#   --docker-server=192.168.1.105 --docker-username='robot$cluster-pull' \
#   --docker-password='<token>' -n <namespace>
```

## Output Style

Replace all `<placeholders>` with the user's actual values. Be conversational and confirm each step works before proceeding. Run verification commands to validate.
