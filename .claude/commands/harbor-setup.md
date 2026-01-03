---
description: Guide developers through setting up Docker build/push/pull with Harbor registry
---

Help the developer set up their Docker image pipeline with the private Harbor registry.

## Context

This cluster uses a private Harbor registry exposed via Tailscale at `registry.<tailnet>.ts.net`. Developers must:
1. Be connected to Tailscale
2. Build images for `linux/amd64` (cluster architecture)
3. Push to Harbor with proper authentication
4. Reference images correctly in Kubernetes manifests

## Step 1: Gather Information

Use the AskUserQuestion tool to collect:

**Question 1 - Application name**: "What is your application name?"
- This determines the image name (e.g., `myapp` becomes `registry.<tailnet>/library/myapp`)

**Question 2 - Dockerfile location**: "Where is your Dockerfile?"
- Options: "Current directory", "Subdirectory (specify path)", "Need to create one"

**Question 3 - Development machine**: "What machine are you building on?"
- Options: "ARM Mac (M1/M2/M3/M4)", "Intel Mac", "Linux x86_64"
- This determines if `--platform linux/amd64` is needed

**Question 4 - Harbor credentials**: "Do you have Harbor login credentials?"
- Options: "Yes, I have them", "No, I need to get them from admin"

## Step 2: Verify Prerequisites

After gathering info, verify:

```bash
# Check Tailscale connection
tailscale status

# Get tailnet suffix for registry URL
tailscale status --json | jq -r '.MagicDNSSuffix'
```

If not connected, instruct: "Run `tailscale up` to connect to the network."

## Step 3: Provide Customized Instructions

Based on their answers, provide a complete workflow. Use their actual application name.

### For ARM Mac users, emphasize:

```bash
# CRITICAL: Always use --platform flag or image won't run on cluster
docker build --platform linux/amd64 -t <app-name>:v1 .
```

### Docker login:

```bash
# Login to Harbor (only needed once, credentials are cached)
docker login registry.<tailnet-suffix>
```

### Tag and push:

```bash
# Tag for Harbor registry
docker tag <app-name>:v1 registry.<tailnet-suffix>/library/<app-name>:v1

# Push to Harbor
docker push registry.<tailnet-suffix>/library/<app-name>:v1
```

### Kubernetes deployment snippet:

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
          image: registry.<tailnet-suffix>/library/<app-name>:v1
```

Note: The `default` namespace has image pull credentials configured. For other namespaces, ask the cluster admin.

## Step 4: Verification Commands

Provide commands to verify the setup worked:

```bash
# Verify image was pushed (check Harbor UI or use skopeo)
skopeo inspect docker://registry.<tailnet-suffix>/library/<app-name>:v1

# Verify architecture is correct
skopeo inspect --format '{{.Architecture}}' docker://registry.<tailnet-suffix>/library/<app-name>:v1
# Should output: amd64
```

## Step 5: Quick Reference Card

After setup is complete, provide a copy-pasteable quick reference:

```bash
# Build (ARM Mac)
docker build --platform linux/amd64 -t <app-name>:<tag> .

# Tag
docker tag <app-name>:<tag> registry.<tailnet-suffix>/library/<app-name>:<tag>

# Push
docker push registry.<tailnet-suffix>/library/<app-name>:<tag>
```

## Troubleshooting Tips

If they encounter issues, reference these solutions:

- **"unauthorized"**: Run `docker login registry.<tailnet-suffix>` again
- **"no such host"**: Check `tailscale status` - must be connected
- **"exec format error" in cluster**: Image built for wrong architecture - rebuild with `--platform linux/amd64`
- **Image not found in cluster**: Verify push succeeded and image path matches exactly

## Output Style

Be conversational and guide them step-by-step. Replace all `<placeholders>` with their actual values. Confirm each step works before proceeding to the next.
