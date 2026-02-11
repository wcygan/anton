# Harbor Developer Guide

Quick reference for pushing and pulling container images from the private Harbor registry.

## Prerequisites

- Docker installed
- On the same LAN as the cluster (192.168.1.x network)
- Docker configured with `192.168.1.105` as an insecure registry (see below)

**Important**: Cluster nodes run `linux/amd64`. If you're on an ARM Mac (M1/M2/M3), always build with `--platform linux/amd64` or images will fail to run.

## Docker Insecure Registry Setup

Harbor is exposed over HTTP on `192.168.1.105`. Docker requires explicit opt-in for HTTP registries.

**Docker Desktop**: Settings → Docker Engine → add to the JSON config:

```json
{
  "insecure-registries": ["192.168.1.105"]
}
```

Then restart Docker Desktop.

## Login

```bash
docker login 192.168.1.105
```

Get credentials from the cluster admin or Harbor UI.

## Push an Image

```bash
# Tag your local image for Harbor
docker tag myapp:v1 192.168.1.105/library/myapp:v1

# Push
docker push 192.168.1.105/library/myapp:v1
```

**Projects**: `library` is the default public project. Ask an admin to create additional projects if needed.

## Pull an Image

```bash
docker pull 192.168.1.105/library/myapp:v1
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
          image: 192.168.1.105/library/myapp:v1
```

The cluster handles authentication automatically in the `default` namespace. For other namespaces, ask the cluster admin to configure image pull credentials.

## Building for the Cluster (ARM Mac Users)

```bash
docker build --platform linux/amd64 -t myapp:v1 .
docker tag myapp:v1 192.168.1.105/library/myapp:v1
docker push 192.168.1.105/library/myapp:v1
```

## Web UI

Browse images and check vulnerability scans via Tailscale at:

```
https://registry.<tailnet-name>.ts.net
```

The web UI is still accessible via Tailscale Ingress for remote access.

## Off-LAN Push/Pull

When not on the cluster LAN, use port-forward:

```bash
# Terminal 1: Port-forward to Harbor
kubectl port-forward svc/harbor -n harbor 8080:80

# Terminal 2: Push via localhost
docker tag myapp:v1 localhost:8080/library/myapp:v1
docker push localhost:8080/library/myapp:v1
```

## Troubleshooting

### "unauthorized" error on push/pull

Run `docker login` again. Credentials may have expired.

### Connection refused or timeout

Verify you're on the cluster LAN (192.168.1.x) and can reach the Harbor IP:

```bash
curl http://192.168.1.105/api/v2.0/health
```

### Image works locally but fails in cluster

Check architecture. Cluster nodes are `amd64`:

```bash
docker inspect myapp:v1 | jq '.[0].Architecture'
```

If it shows `arm64`, rebuild with `--platform linux/amd64`.
