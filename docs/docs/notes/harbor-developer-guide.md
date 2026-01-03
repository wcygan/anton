# Harbor Developer Guide

Quick reference for pushing and pulling container images from the private Harbor registry.

## Prerequisites

- Docker installed
- Connected to the Tailscale network

**Important**: Cluster nodes run `linux/amd64`. If you're on an ARM Mac (M1/M2/M3), always build with `--platform linux/amd64` or images will fail to run.

## Find Your Registry URL

Get your tailnet suffix:

```bash
tailscale status --json | jq -r '.MagicDNSSuffix'
```

Your registry URL is: `registry.<tailnet-suffix>`

For example, if the command returns `example.ts.net`, your registry is `registry.example.ts.net`.

## Login

```bash
docker login registry.<tailnet-suffix>
```

Get credentials from the cluster admin or Harbor UI.

## Push an Image

```bash
# Tag your local image for Harbor
docker tag myapp:v1 registry.<tailnet-suffix>/library/myapp:v1

# Push
docker push registry.<tailnet-suffix>/library/myapp:v1
```

**Projects**: `library` is the default public project. Ask an admin to create additional projects if needed.

## Pull an Image

```bash
docker pull registry.<tailnet-suffix>/library/myapp:v1
```

## Use in Kubernetes

Reference the full image path in your deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
        - name: myapp
          image: registry.<tailnet-suffix>/library/myapp:v1
```

The cluster handles authentication automatically in the `default` namespace. For other namespaces, ask the cluster admin to configure image pull credentials.

## Building for the Cluster (ARM Mac Users)

```bash
docker build --platform linux/amd64 -t myapp:v1 .
docker tag myapp:v1 registry.<tailnet-suffix>/library/myapp:v1
docker push registry.<tailnet-suffix>/library/myapp:v1
```

## Web UI

Browse images and check vulnerability scans at:

```
https://registry.<tailnet-suffix>
```

## Troubleshooting

### "unauthorized" error on push/pull

Run `docker login` again. Credentials may have expired.

### "no such host" error

Verify you're connected to Tailscale:

```bash
tailscale status
```

### Image works locally but fails in cluster

Check architecture. Cluster nodes are `amd64`:

```bash
docker inspect myapp:v1 | jq '.[0].Architecture'
```

If it shows `arm64`, rebuild with `--platform linux/amd64`.
