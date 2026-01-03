---
description: Guide developers through setting up Docker build/push/pull with Harbor registry
---

Help the developer set up their Docker image pipeline with the private Harbor registry.

## Context

This cluster uses a private Harbor registry. The key insight is:

- **Push**: Use `localhost:8080` via port-forward (fast, ~LAN speed)
- **Pull**: Pods reference `registry.<tailnet>.ts.net` (auto-redirected to internal ClusterIP)

Both hostnames access the same Harbor instance. The repository path (`library/myapp:v1`) is what identifies the image, not the hostname.

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

### Start Harbor Port-Forward

```bash
# Run in a separate terminal (or background with &)
kubectl port-forward svc/harbor -n harbor 8080:80
```

This creates a fast local tunnel to Harbor, bypassing slow Tailscale DERP relay.

### Login to Harbor

```bash
# Login once (credentials are cached)
docker login localhost:8080
# Username: admin (or your username)
# Password: (get from cluster admin or Harbor UI)
```

## Step 3: Build and Push Workflow

Based on their machine type, provide the appropriate workflow.

### For ARM Mac users (M1/M2/M3/M4):

```bash
# Build for cluster architecture (REQUIRED - cluster runs amd64)
docker build --platform linux/amd64 -t <app-name>:<tag> .

# Push via port-forward (fast)
docker tag <app-name>:<tag> localhost:8080/library/<app-name>:<tag>
docker push localhost:8080/library/<app-name>:<tag>
```

### For Intel Mac / Linux x86_64:

```bash
# Build (no platform flag needed)
docker build -t <app-name>:<tag> .

# Push via port-forward (fast)
docker tag <app-name>:<tag> localhost:8080/library/<app-name>:<tag>
docker push localhost:8080/library/<app-name>:<tag>
```

## Step 4: Kubernetes Reference

Pods always reference the Tailscale hostname (cluster handles the fast internal routing):

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
          image: registry.<tailnet-suffix>/library/<app-name>:<tag>
```

**Why different hostnames?**
- Push uses `localhost:8080` for speed (port-forward to Harbor)
- Pull uses `registry.<tailnet>.ts.net` which containerd redirects to internal ClusterIP (~69 MB/s)
- Same image - Harbor stores by repository path, not hostname

## Step 5: Quick Reference Card

Provide this copy-pasteable summary:

```bash
# === One-time setup ===
kubectl port-forward svc/harbor -n harbor 8080:80 &
docker login localhost:8080

# === Build and push ===
docker build --platform linux/amd64 -t <app-name>:<tag> .
docker tag <app-name>:<tag> localhost:8080/library/<app-name>:<tag>
docker push localhost:8080/library/<app-name>:<tag>

# === In Kubernetes manifests ===
image: registry.<tailnet-suffix>/library/<app-name>:<tag>
```

## Fallback: Push via Tailscale

If port-forward isn't available, push directly via Tailscale (slower, ~200 KB/s):

```bash
docker login registry.<tailnet-suffix>
docker tag <app-name>:<tag> registry.<tailnet-suffix>/library/<app-name>:<tag>
docker push registry.<tailnet-suffix>/library/<app-name>:<tag>
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `unauthorized` on push | Run `docker login localhost:8080` (or the registry URL you're using) |
| `connection refused` on localhost:8080 | Start port-forward: `kubectl port-forward svc/harbor -n harbor 8080:80` |
| `exec format error` in cluster | Image built for wrong arch - rebuild with `--platform linux/amd64` |
| Push is slow | Use port-forward method instead of Tailscale |
| Image not found in cluster | Verify repository path matches exactly (`library/<app-name>:<tag>`) |

## Output Style

Be conversational and guide them step-by-step. Replace all `<placeholders>` with their actual values. Confirm each step works before proceeding to the next.
