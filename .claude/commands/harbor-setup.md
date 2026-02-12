---
description: Guide developers through setting up Docker build/push/pull with Harbor registry
---

Help the developer set up their Docker image pipeline with the private Harbor registry.

## Context

This cluster uses a private Harbor registry exposed at `192.168.1.105` via Cilium LoadBalancer (HTTP).

- **Push**: Use `192.168.1.105` directly from LAN (fast, no port-forward needed)
- **Pull**: Pods reference `192.168.1.105` (containerd mirrors to internal ClusterIP for ~100ms pulls)
- **Web UI**: `https://registry.<tailnet-name>.ts.net` via Tailscale (remote access only)

## Step 1: Gather Information

Use the AskUserQuestion tool to collect:

**Question 1 - Application name**: "What is your application name?"
- This determines the image name (e.g., `myapp` becomes `library/myapp`)

**Question 2 - Dockerfile location**: "Where is your Dockerfile?"
- Options: "Current directory", "Subdirectory (specify path)", "Need to create one"

**Question 3 - Development machine**: "What machine are you building on?"
- Options: "ARM Mac (M1/M2/M3/M4)", "Intel Mac", "Linux x86_64"
- ARM Macs MUST use `--platform linux/amd64`

## Step 2: One-Time Setup

### Configure Docker for HTTP Registry

Harbor is HTTP-only. Docker requires explicit opt-in:

**Docker Desktop**: Settings → Docker Engine → add to JSON config:

```json
{
  "insecure-registries": ["192.168.1.105"]
}
```

Restart Docker Desktop after saving.

### Login to Harbor

```bash
docker login 192.168.1.105
# Username: admin (or your username)
# Password: (get from cluster admin or Harbor UI)
```

## Step 3: Build and Push Workflow

### For ARM Mac users (M1/M2/M3/M4):

```bash
# Build for cluster architecture (REQUIRED - cluster runs amd64)
docker build --platform linux/amd64 -t <app-name>:<tag> .

# Tag and push directly to Harbor LAN IP
docker tag <app-name>:<tag> 192.168.1.105/library/<app-name>:<tag>
docker push 192.168.1.105/library/<app-name>:<tag>
```

### For Intel Mac / Linux x86_64:

```bash
# Build (no platform flag needed)
docker build -t <app-name>:<tag> .

# Tag and push
docker tag <app-name>:<tag> 192.168.1.105/library/<app-name>:<tag>
docker push 192.168.1.105/library/<app-name>:<tag>
```

## Step 4: Kubernetes Reference

Pods reference the LoadBalancer IP (cluster handles fast internal routing via ClusterIP mirror):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <app-name>
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <app-name>
  template:
    metadata:
      labels:
        app: <app-name>
    spec:
      containers:
        - name: <app-name>
          image: 192.168.1.105/library/<app-name>:<tag>
      imagePullSecrets:
        - name: harbor-pull
```

**imagePullSecret setup** (per namespace):

```bash
kubectl create secret docker-registry harbor-pull \
  --docker-server=192.168.1.105 \
  --docker-username='robot$cluster-pull' \
  --docker-password='<robot-token>' \
  -n <namespace>
```

## Step 5: Quick Reference Card

Provide this copy-pasteable summary:

```bash
# === One-time setup ===
# Add "192.168.1.105" to Docker insecure-registries, restart Docker
docker login 192.168.1.105

# === Build and push ===
docker build --platform linux/amd64 -t <app-name>:<tag> .
docker tag <app-name>:<tag> 192.168.1.105/library/<app-name>:<tag>
docker push 192.168.1.105/library/<app-name>:<tag>

# === In Kubernetes manifests ===
image: 192.168.1.105/library/<app-name>:<tag>
```

## Fallback: Off-LAN Push via Port-Forward

If not on the cluster LAN, push via kubectl port-forward:

```bash
# Terminal 1: Port-forward to Harbor
kubectl port-forward svc/harbor -n harbor 8080:80

# Terminal 2: Push via localhost
docker tag <app-name>:<tag> localhost:8080/library/<app-name>:<tag>
docker push localhost:8080/library/<app-name>:<tag>
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `unauthorized` on push | Run `docker login 192.168.1.105` |
| Connection refused | Verify you're on cluster LAN: `curl http://192.168.1.105/api/v2.0/health` |
| `exec format error` in cluster | Image built for wrong arch - rebuild with `--platform linux/amd64` |
| Image not found in cluster | Verify repository path matches exactly (`library/<app-name>:<tag>`) |
| Off-LAN and can't reach 192.168.1.105 | Use port-forward fallback above |

## Output Style

Be conversational and guide them step-by-step. Replace all `<placeholders>` with their actual values. Confirm each step works before proceeding to the next.
