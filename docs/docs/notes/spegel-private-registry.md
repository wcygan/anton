# Harbor Registry with Spegel

This document explains how to use the private Harbor registry in the cluster, and how Spegel (P2P registry mirror) is configured to work alongside it.

---

## Quick Start

### Push an Image (from workstation)

```bash
# 1. Build for the correct architecture (ARM Mac users)
docker build --platform linux/amd64 -t myapp:v1 .

# 2. Tag for Harbor (LAN LoadBalancer IP)
docker tag myapp:v1 192.168.1.105/library/myapp:v1

# 3. Login and push (works from any machine on the cluster LAN)
docker login 192.168.1.105
docker push 192.168.1.105/library/myapp:v1
```

**Note**: Requires Docker insecure registry config for HTTP. See [Harbor Developer Guide](./harbor-developer-guide.md).

**Off-LAN push via port-forward**:

```bash
# Terminal 1: Port-forward to Harbor
kubectl port-forward svc/harbor -n harbor 8080:80

# Terminal 2: Push via localhost
docker tag myapp:v1 localhost:8080/library/myapp:v1
docker push localhost:8080/library/myapp:v1
```

### Pull an Image (in Kubernetes)

Simply reference the image in your pod spec:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp
spec:
  containers:
    - name: myapp
      image: 192.168.1.105/library/myapp:v1
```

Cluster nodes automatically pull via the internal ClusterIP mirror for fast in-cluster pulls.

---

## How It Works

```
Workstation Push                          Cluster Pull
─────────────────                         ────────────────
docker push                               Pod: image: 192.168.1.105/library/myapp:v1
     │                                           │
     ▼                                           ▼
LAN ──────────────────────────────────>  containerd checks hosts.toml
     │                                           │
     ▼                                           ▼
Harbor LoadBalancer                      Mirror: http://harbor.harbor.svc.cluster.local
(192.168.1.105)                                  │
     │                                           ▼
     ▼                                   Harbor ClusterIP (10.43.216.243)
Harbor Registry                                  │
(stores image)                                   ▼
                                         Pull completes in ~500ms (37MB)
```

**Key insight**: Pods reference images using the LoadBalancer IP, but containerd redirects pulls to the internal ClusterIP. This gives:
- **Push**: Works from any machine on the cluster LAN (direct, no Tailscale needed)
- **Pull**: Fast internal path via ClusterIP mirror

---

## Configuration Pattern

Use this pattern when adding a private registry to a Talos cluster with Spegel.

### 1. Include in Spegel's mirroredRegistries

Configure Spegel to manage the Harbor registry's hosts.toml alongside public registries:

```yaml
# kubernetes/apps/kube-system/spegel/app/helmrelease.yaml
spec:
  values:
    spegel:
      mirroredRegistries:
        - https://docker.io
        - https://ghcr.io
        - https://gcr.io
        - https://registry.k8s.io
        - https://quay.io
        - https://mcr.microsoft.com
        - http://192.168.1.105
      # WHY: Preserve Talos-managed containerd mirror configs
      prependExisting: true
```

### 2. Configure Registry Mirror (Talos)

Add to `talos/patches/global/machine-network.yaml`:

```yaml
machine:
  registries:
    mirrors:
      # Maps LoadBalancer IP to internal service
      192.168.1.105:
        endpoints:
          - http://harbor.harbor.svc.cluster.local
    config:
      # Auth for the internal endpoint
      harbor.harbor.svc.cluster.local:
        auth:
          username: ${HARBOR_ROBOT_USERNAME}
          password: ${HARBOR_ROBOT_PASSWORD}
  network:
    extraHostEntries:
      # containerd runs on host, can't resolve k8s service names
      # Map to Harbor ClusterIP so internal pulls work
      - ip: 10.43.216.243
        aliases:
          - harbor.harbor.svc.cluster.local
```

### 3. Add Credentials to talenv.sops.yaml

```yaml
# talos/talenv.sops.yaml (encrypted)
HARBOR_ROBOT_USERNAME: robot$cluster-pull
HARBOR_ROBOT_PASSWORD: <robot-account-token>
```

### 4. Apply Configuration

```bash
# Regenerate Talos configs
task talos:generate-config

# Apply to all nodes
task talos:apply-node IP=192.168.1.98 MODE=auto
task talos:apply-node IP=192.168.1.99 MODE=auto
task talos:apply-node IP=192.168.1.100 MODE=auto

# Verify (should show hosts.toml for your registry)
talosctl -n 192.168.1.98 ls /etc/cri/conf.d/hosts/
```

---

## Verification

### Check Pull Speed

```bash
# Should complete in <1s for ~40MB images
kubectl run test --image=192.168.1.105/library/myapp:v1 --restart=Never
kubectl describe pod test | grep "Pulled"
# Expected: "Successfully pulled image ... in 542ms"
```

### Check Node Configuration

```bash
# Verify hosts.toml exists
talosctl -n <node-ip> read /etc/cri/conf.d/hosts/192.168.1.105/hosts.toml

# Verify auth is configured
talosctl -n <node-ip> read /etc/cri/conf.d/cri.toml | grep -A 4 "harbor.harbor.svc.cluster.local"
```

### Check Spegel Configuration

```bash
# Should show 192.168.1.105 alongside public registries
talosctl -n <node-ip> ls /etc/cri/conf.d/hosts/

# Expected: docker.io  gcr.io  ghcr.io  mcr.microsoft.com  quay.io  registry.k8s.io  192.168.1.105
```

---

## Troubleshooting

### Image pull fails with "unauthorized"

**Symptom**: Pod stuck in `ImagePullBackOff` with 401 error.

**Checks**:
1. Verify robot credentials in `talenv.sops.yaml`
2. Check CRI has auth configured: `talosctl -n <ip> read /etc/cri/conf.d/cri.toml | grep -A 4 harbor`
3. Test auth manually: `curl -u 'robot$cluster-pull:<password>' http://harbor.harbor.svc.cluster.local/v2/`

### Image pull hangs or is slow

**Symptom**: Pull takes >30s for small images.

**Checks**:
1. Verify internal mirror is used: `talosctl -n <ip> read /etc/cri/conf.d/hosts/192.168.1.105/hosts.toml`
2. Check extraHostEntries: `talosctl -n <ip> read /etc/hosts | grep harbor`
3. If internal path broken, pulls fall back to LoadBalancer IP (still works, slightly slower)

### Spegel intercepts Harbor requests

**Symptom**: Pull fails with "not found" even though image exists in Harbor.

**Checks**:
1. Look for `_default` directory: `talosctl -n <ip> ls /etc/cri/conf.d/hosts/`
2. If `_default` exists, Spegel is intercepting all registries
3. Fix: Add `mirroredRegistries` list to Spegel HelmRelease and restart

```bash
flux reconcile hr spegel -n kube-system
kubectl rollout restart ds/spegel -n kube-system
```

### Stale containerd downloads

**Symptom**: Pulls hang indefinitely.

**Check**: `talosctl -n <ip> ls /var/lib/containerd/io.containerd.content.v1.content/ingest/`

**Fix**: If stuck ingests exist (>5 min old), reboot the node.

---

## Architecture Details

### Why This Configuration?

| Challenge | Solution |
|-----------|----------|
| Docker auth realm must be reachable from containerd | LoadBalancer IP (192.168.1.105) on host network |
| Spegel must manage Harbor's hosts.toml | Include in `mirroredRegistries` with `prependExisting: true` |
| containerd can't resolve k8s service names | Add `extraHostEntries` mapping to ClusterIP |
| Harbor requires auth even for "public" projects | Configure robot credentials in `machine.registries.config` |

### File Locations

| Purpose | File |
|---------|------|
| Registry mirror + auth | `talos/patches/global/machine-network.yaml` |
| Robot credentials | `talos/talenv.sops.yaml` |
| Spegel mirror list | `kubernetes/apps/kube-system/spegel/app/helmrelease.yaml` |
| Harbor deployment | `kubernetes/apps/harbor/harbor/app/helmrelease.yaml` |

### Key IPs

| Service | IP | Port |
|---------|-----|------|
| Harbor LoadBalancer | `192.168.1.105` | 80 |
| Harbor ClusterIP (internal) | `10.43.216.243` | 80 |

---

## Related Documentation

- [Harbor Developer Guide](./harbor-developer-guide.md) - Detailed push/pull workflow
- [Harbor Registry Setup](./harbor-registry.md) - Initial Harbor configuration and architecture
