# Kubernetes Cluster Recovery Guide

This guide documents the process for recovering a Kubernetes cluster when critical infrastructure components fail, particularly focusing on Container Network Interface (CNI) and DNS failures.

## Table of Contents

- [Overview](#overview)
- [Symptoms of Infrastructure Failure](#symptoms-of-infrastructure-failure)
- [Root Cause Analysis](#root-cause-analysis)
- [Recovery Process](#recovery-process)
- [Prevention Strategies](#prevention-strategies)
- [Quick Reference](#quick-reference)

## Overview

The homelab cluster uses a two-phase bootstrap approach:
1. **Helmfile Bootstrap**: Deploys critical infrastructure (Cilium, CoreDNS, Cert-Manager, Flux)
2. **Flux GitOps**: Manages all other applications and configurations

When the CNI or DNS fails, the cluster cannot self-heal through GitOps and requires manual intervention using the helmfile bootstrap process.

## Symptoms of Infrastructure Failure

### Critical Indicators

1. **Pod Creation Failures**
   ```bash
   kubectl run test --image=busybox --rm -it --restart=Never -- echo "test"
   # Error: timed out waiting for the condition
   ```

2. **DNS Resolution Failures**
   ```bash
   # In Flux logs:
   dial tcp: lookup source-controller.flux-system.svc.cluster.local. on 10.43.0.10:53: i/o timeout
   ```

3. **Missing Core Components**
   ```bash
   kubectl get pods -n kube-system | grep -E "cilium|coredns"
   # No output - Cilium and CoreDNS pods missing
   ```

4. **Service Discovery Broken**
   ```bash
   kubectl get svc -n kube-system kube-dns
   # Error: No service found
   ```

### Secondary Symptoms

- Flux kustomizations stuck in "Not Ready" state
- All pod deployments failing
- Network timeouts in controller logs
- Pods unable to communicate with each other

## Root Cause Analysis

Use the Five Whys methodology to identify the root cause:

1. **Why are applications not deploying?**
   - Flux cannot reconcile due to network failures

2. **Why is Flux experiencing network failures?**
   - DNS lookups are timing out

3. **Why are DNS lookups timing out?**
   - CoreDNS is not running

4. **Why is CoreDNS not running?**
   - Pods cannot be scheduled without a CNI

5. **Why is there no CNI?**
   - Cilium is not deployed/running

## Recovery Process

### Prerequisites

Ensure you have:
- `kubectl` access to the cluster
- `helmfile` installed locally
- Access to the homelab repository
- The `ROOT_DIR` environment variable set to the repository root

### Step 1: Verify Node Health

```bash
# Check all nodes are Ready
kubectl get nodes -o wide

# Expected output:
# NAME    STATUS   ROLES           AGE   VERSION
# k8s-1   Ready    control-plane   28d   v1.33.1
# k8s-2   Ready    control-plane   28d   v1.33.1
# k8s-3   Ready    control-plane   28d   v1.33.1
```

### Step 2: Deploy Critical Infrastructure

```bash
# Set the repository root
export ROOT_DIR=$(pwd)

# Deploy all bootstrap components
helmfile --file bootstrap/helmfile.yaml sync

# Or deploy components individually:
# Deploy Cilium first
helmfile --file bootstrap/helmfile.yaml -l name=cilium sync

# Then CoreDNS
helmfile --file bootstrap/helmfile.yaml -l name=coredns sync

# Continue with remaining components
helmfile --file bootstrap/helmfile.yaml sync
```

### Step 3: Verify CNI and DNS

```bash
# Check Cilium pods
kubectl get pods -n kube-system -l app.kubernetes.io/name=cilium
# Or
kubectl get pods -n kube-system | grep cilium

# Check CoreDNS
kubectl get pods -n kube-system | grep coredns

# Verify DNS service
kubectl get svc -n kube-system kube-dns

# Test DNS resolution
kubectl run test-dns --image=busybox:1.36 --rm -it --restart=Never -- \
  nslookup kubernetes.default.svc.cluster.local
```

### Step 4: Restore Flux GitOps

If Flux components are missing after bootstrap:

```bash
# Check for FluxInstance
kubectl get fluxinstance -n flux-system

# If missing, recreate from helm manifest
helm get manifest flux-instance -n flux-system | kubectl apply -f -

# Wait for Flux controllers
kubectl get pods -n flux-system --watch
```

### Step 5: Force GitOps Reconciliation

```bash
# Once Flux is running, force reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster-meta
flux reconcile kustomization cluster-apps

# Monitor progress
flux get all -A
```

## Prevention Strategies

### 1. Regular Health Checks

Create a monitoring script that runs periodically:

```bash
#!/bin/bash
# Check critical components
echo "Checking CNI..."
kubectl get ds -n kube-system cilium >/dev/null 2>&1 || echo "WARNING: Cilium not found"

echo "Checking DNS..."
kubectl get deploy -n kube-system coredns >/dev/null 2>&1 || echo "WARNING: CoreDNS not found"

echo "Checking Flux..."
flux check || echo "WARNING: Flux unhealthy"
```

### 2. Bootstrap Verification

After any cluster maintenance:

```bash
# Run the bootstrap apps task
task bootstrap:apps

# Verify all components
helmfile --file bootstrap/helmfile.yaml list
```

### 3. Documentation and Runbooks

- Maintain this recovery guide
- Document any cluster-specific configurations
- Keep bootstrap files in version control
- Test recovery procedures periodically

### 4. Automated Recovery

Consider implementing:
- Automated health checks via monitoring
- Alerts for missing critical components
- Self-healing scripts for common failures

## Quick Reference

### Essential Commands

```bash
# Check cluster health
kubectl get nodes
kubectl get pods -n kube-system
flux get all -A

# Bootstrap recovery
export ROOT_DIR=$(pwd)
helmfile --file bootstrap/helmfile.yaml sync

# Test networking
kubectl run test --image=busybox --rm -it --restart=Never -- ping -c 3 8.8.8.8
kubectl run test-dns --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default

# Force Flux reconciliation
flux reconcile source git flux-system --with-source
```

### Component Dependencies

```
Nodes (Ready)
  └── Cilium CNI
      └── Pod Networking
          └── CoreDNS
              └── Service Discovery
                  └── Flux Controllers
                      └── GitOps Applications
```

### Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| Cilium not starting | Check node taints, verify kernel modules |
| CoreDNS CrashLoopBackOff | Check Cilium health first, verify DNS configmap |
| Flux timeout errors | Ensure DNS is working, check network policies |
| Helmfile "already installed" | Use `--force` flag or delete release first |

### Bootstrap Component Versions

From `bootstrap/helmfile.yaml`:
- Cilium: 1.17.4
- CoreDNS: 1.42.1
- Cert-Manager: v1.17.2
- Flux Operator: 0.20.0
- Flux Instance: 0.20.0

## Conclusion

Infrastructure failures in Kubernetes can seem catastrophic but are recoverable with the right approach. The key is understanding the dependency chain and having a reliable bootstrap mechanism. Always verify fundamental components (CNI, DNS) before troubleshooting higher-level issues.

Remember: When in doubt, start from the bottom of the stack and work your way up.