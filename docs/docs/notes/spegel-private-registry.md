# Spegel and Private Registry Integration

This document explains how Spegel (P2P registry mirror) interacts with private registries like Harbor, and how to configure them to work together.

## The Problem

Spegel is a peer-to-peer registry mirror that caches container images across cluster nodes. By default, it creates a catch-all configuration (`_default`) that intercepts **all** registry requests. This causes issues with private registries like Harbor because:

1. Spegel intercepts the pull request
2. Spegel checks its P2P peers for the image
3. Peers return 404 (they don't have the private image)
4. Spegel has no fallback to the actual registry for non-standard registries
5. The pull fails with "not found" even though the image exists

## Symptoms

- Image pulls from Harbor fail with `ErrImagePull` or `ImagePullBackOff`
- Error messages like "not found" or "manifest unknown"
- The same image pulls successfully from a workstation but fails on cluster nodes
- Pulls work initially after a node reboot, then fail after Spegel starts

## Root Cause

Spegel's default behavior creates `/etc/cri/conf.d/hosts/_default/hosts.toml`:

```toml
# This intercepts ALL registries
[host.'http://192.168.1.100:29999']
capabilities = ['pull', 'resolve']
dial_timeout = '200ms'
```

For standard registries (docker.io, ghcr.io), this works because Spegel's mirrors can fallback to the upstream. For private registries like Harbor, there's no fallback path - Spegel doesn't know how to reach Harbor.

## Solution

Configure Spegel to only mirror specific registries, leaving private registries untouched.

### 1. Update Spegel HelmRelease

Edit `kubernetes/apps/kube-system/spegel/app/helmrelease.yaml`:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: spegel
spec:
  chartRef:
    kind: OCIRepository
    name: spegel
  interval: 1h
  values:
    spegel:
      containerdSock: /run/containerd/containerd.sock
      containerdRegistryConfigPath: /etc/cri/conf.d/hosts
      # WHY: Explicitly list registries for Spegel to mirror.
      # Without this, Spegel uses _default which intercepts ALL registries
      # including Harbor, but can't fallback to non-standard registries after 404.
      mirroredRegistries:
        - https://docker.io
        - https://ghcr.io
        - https://gcr.io
        - https://registry.k8s.io
        - https://quay.io
        - https://mcr.microsoft.com
```

**Key insight**: The value is `mirroredRegistries`, not `registries`. Empty list means "mirror all" (bad for private registries).

### 2. Verify Configuration

After applying, check that `_default` is gone:

```bash
# Should NOT show _default
talosctl -n <node-ip> ls /etc/cri/conf.d/hosts/

# Expected output:
# docker.io
# gcr.io
# ghcr.io
# mcr.microsoft.com
# quay.io
# registry.k8s.io
```

### 3. Restart Spegel Pods

Force Spegel to recreate its configuration:

```bash
flux reconcile hr spegel -n kube-system
kubectl rollout restart ds/spegel -n kube-system
```

## Debugging Checklist

When Harbor image pulls fail, check these in order:

### 1. Check if Spegel is intercepting Harbor

```bash
# Look for _default directory (bad) or your Harbor hostname
talosctl -n <node-ip> ls /etc/cri/conf.d/hosts/

# If _default exists, Spegel is intercepting all registries
talosctl -n <node-ip> read /etc/cri/conf.d/hosts/_default/hosts.toml
```

### 2. Check for stale containerd ingests

Stuck downloads can block new pulls:

```bash
# Should be empty or have recent timestamps
talosctl -n <node-ip> ls /var/lib/containerd/io.containerd.content.v1.content/ingest/

# If stuck ingests exist (older than 5 minutes), reboot the node
talosctl -n <node-ip> reboot
```

### 3. Verify Harbor DNS resolution

```bash
# Check /etc/hosts on node
talosctl -n <node-ip> read /etc/hosts | grep harbor

# Should show: <tailscale-ip> registry.<tailnet>.ts.net
```

### 4. Test direct connectivity

```bash
# From a pod or node, test Harbor is reachable
curl -I https://registry.<tailnet>.ts.net/v2/
```

### 5. Check imagePullSecrets

```bash
# Verify secret exists in namespace
kubectl get secret harbor-pull -n <namespace>

# Verify ServiceAccount has imagePullSecrets
kubectl get sa default -n <namespace> -o yaml | grep -A 5 imagePullSecrets
```

### 6. Watch CRI logs during pull

```bash
# Real-time CRI activity
talosctl -n <node-ip> logs cri -f | grep -i pull
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Pod Pull Request                         │
│                    (registry.example.ts.net/image)               │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                          containerd                              │
│                                                                  │
│  Checks /etc/cri/conf.d/hosts/<registry-hostname>/hosts.toml    │
└─────────────────────────────────────────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
            Config exists?              No config found
                    │                           │
                    ▼                           ▼
┌───────────────────────────┐   ┌───────────────────────────────┐
│   Use configured mirrors   │   │  Direct to registry hostname  │
│   (Spegel P2P for docker.io│   │  (Harbor via Tailscale)       │
│    ghcr.io, etc.)          │   │                               │
└───────────────────────────┘   └───────────────────────────────┘
```

**Goal**: Harbor should NOT have a hosts.toml in Spegel's config directory, so containerd goes directly to Harbor.

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Using `registries:` instead of `mirroredRegistries:` | Spegel ignores the config | Use correct key: `mirroredRegistries:` |
| Empty `mirroredRegistries: []` | Spegel mirrors everything (including Harbor) | List specific registries to mirror |
| Not restarting Spegel after config change | Old _default config persists | `kubectl rollout restart ds/spegel -n kube-system` |
| Stale containerd ingest | Pulls hang indefinitely | Reboot the affected node |

## Related Documentation

- [Harbor Developer Guide](./harbor-developer-guide.md) - How to push/pull images with Harbor
- [Harbor Registry Setup](./harbor-registry.md) - Initial Harbor configuration
- [Tailscale Extension](./tailscale-extension.md) - Tailscale networking for nodes
