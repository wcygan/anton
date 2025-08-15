# Rook Ceph GitOps Structure for Anton Homelab

**Purpose**: Define the Flux GitOps structure for Rook Ceph deployment  
**Inspiration**: Based on proven patterns from onedr0p and joryirving home-ops repositories  
**Status**: Template ready for implementation

## Overview

This document outlines the **Hybrid Progressive GitOps structure** for deploying Rook Ceph in your homelab using Flux. This approach uniquely combines onedr0p's operational simplicity with joryirving's enterprise-ready structure, allowing you to start simple while maintaining a clear path for future expansion.

## Core Principles

1. **Hybrid Progressive Architecture**
   - Start with onedr0p's minimal block storage
   - Use joryirving's directory structure from day one
   - Enable features only when needed

2. **Safety First** (both repositories)
   - Prune disabled on critical resources
   - Extended timeouts for cluster operations
   - Health checks before proceeding

3. **Future-Ready Structure**
   - Full directory tree created upfront
   - Phased population of components
   - No refactoring needed for expansion

## Hybrid Progressive Directory Structure

```
kubernetes/
├── apps/
│   └── storage/
│       ├── kustomization.yaml          # Namespace aggregator
│       ├── namespace.yaml              # rook-ceph namespace
│       │
│       # PHASE 1: Deploy these immediately
│       ├── rook-ceph-operator/         # ✓ Active
│       │   ├── ks.yaml
│       │   └── app/
│       │       ├── kustomization.yaml
│       │       └── helmrelease.yaml
│       │
│       ├── rook-ceph-cluster/          # ✓ Active (block only)
│       │   ├── ks.yaml
│       │   └── app/
│       │       ├── kustomization.yaml
│       │       ├── helmrelease.yaml
│       │       ├── cluster.yaml
│       │       ├── dashboard/
│       │       │   ├── kustomization.yaml
│       │       │   └── ingress.yaml
│       │       └── storage-classes/
│       │           ├── kustomization.yaml
│       │           └── block.yaml    # ✓ Phase 1
│       │
│       # PHASE 2: Structure ready, deploy when needed
│       ├── rook-ceph-filesystem/       # ⧖ Empty until needed
│       │   ├── ks.yaml.disabled       # Rename when ready
│       │   └── app/
│       │       ├── kustomization.yaml
│       │       ├── filesystem.yaml
│       │       └── storageclass.yaml
│       │
│       # PHASE 3: Structure ready, deploy when needed
│       ├── rook-ceph-objectstore/      # ⧖ Empty until needed
│       │   ├── ks.yaml.disabled       # Rename when ready
│       │   └── app/
│       │       ├── kustomization.yaml
│       │       ├── objectstore.yaml
│       │       └── storageclass.yaml
│       │
│       └── volsync/                    # ✓ Active with Phase 1
│           ├── ks.yaml
│           └── app/
│               ├── kustomization.yaml
│               └── helmrelease.yaml
│
├── components/
│   └── volsync/                        # Reusable templates
│       ├── kustomization.yaml
│       └── restic/
│           ├── claim.yaml
│           ├── replicationsource.yaml
│           └── secret.yaml
│
└── flux/
    └── meta/
        └── repos/
            └── rook-release.yaml       # Helm repository
```

### Phase Activation Guide

```bash
# Phase 1: Already active (operator + cluster with block)
# Phase 2: When CephFS needed
mv rook-ceph-filesystem/ks.yaml.disabled rook-ceph-filesystem/ks.yaml
# Phase 3: When Object storage needed  
mv rook-ceph-objectstore/ks.yaml.disabled rook-ceph-objectstore/ks.yaml
```

## Key Component Specifications

### 1. Flux Kustomization Pattern

Both repositories use this pattern for safe deployments:

```yaml
# Pattern for ks.yaml files
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app rook-ceph-operator
  namespace: flux-system
spec:
  targetNamespace: storage
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  timeout: 15m           # Extended for Ceph operations
  prune: false          # Safety measure
  wait: true
  healthChecks:
    - apiVersion: helm.toolkit.fluxcd.io/v2
      kind: HelmRelease
      name: rook-ceph-operator
      namespace: storage
  path: ./kubernetes/apps/storage/rook-ceph-operator/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
```

### 2. Dependency Management

Clear dependency chain inspired by both repositories:

```
rook-ceph-operator
    ↓
rook-ceph-cluster (depends on operator)
    ↓
volsync (depends on cluster for snapshots)
    ↓
applications (depend on storage classes)
```

### 3. HelmRelease Structure

Operator deployment (lightweight, fixed resources):

```yaml
# Operator HelmRelease pattern
spec:
  chart:
    spec:
      chart: rook-ceph
      version: v1.17.4
  values:
    monitoring:
      enabled: true
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
```

Cluster deployment (main configuration):

```yaml
# Cluster HelmRelease pattern
spec:
  chart:
    spec:
      chart: rook-ceph-cluster
      version: v1.17.4
  values:
    monitoring:
      enabled: true
      createPrometheusRules: true
    cephClusterSpec:
      # Detailed configuration
```

### 4. Hybrid Progressive Implementation

#### Phase 1: Minimal Block Storage (onedr0p style)
```yaml
# storage-classes/block.yaml - ONLY storage class in Phase 1
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-block
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  pool: replicapool
  imageFormat: "2"
  imageFeatures: layering
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: rook-ceph
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-rbd-node
  csi.storage.k8s.io/node-stage-secret-namespace: rook-ceph
  csi.storage.k8s.io/fstype: ext4
reclaimPolicy: Delete
allowVolumeExpansion: true
```

#### Phase 2: Add Filesystem (joryirving expansion)
```yaml
# rook-ceph-filesystem/app/filesystem.yaml - Deploy when RWX needed
apiVersion: ceph.rook.io/v1
kind: CephFilesystem
metadata:
  name: ceph-filesystem
  namespace: rook-ceph
spec:
  metadataPool:
    replicated:
      size: 3
  dataPools:
    - name: data0
      replicated:
        size: 3
  metadataServer:
    activeCount: 1
    activeStandby: true
```

#### Phase 3: Add Object Storage (full stack completion)
```yaml
# rook-ceph-objectstore/app/objectstore.yaml - Deploy when S3 needed
apiVersion: ceph.rook.io/v1
kind: CephObjectStore
metadata:
  name: ceph-objectstore
  namespace: rook-ceph
spec:
  metadataPool:
    replicated:
      size: 3
  dataPool:
    replicated:
      size: 3
  gateway:
    instances: 2
```

### 5. Phase-Specific Configuration

```yaml
# Phase tracking in cluster.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ceph-deployment-phase
  namespace: rook-ceph
data:
  current_phase: "1"
  phases_enabled:
    block: "true"
    filesystem: "false"  # Enable in Phase 2
    object: "false"      # Enable in Phase 3
```

## Integration Patterns

### 1. Monitoring Integration

Both repositories emphasize monitoring:

```yaml
# In cluster values
monitoring:
  enabled: true
  createPrometheusRules: true
  prometheusEndpoint: http://prometheus.monitoring.svc.cluster.local:9090
```

### 2. Dashboard Access

Tailscale ingress pattern from your setup:

```yaml
# dashboard/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rook-ceph-dashboard
  annotations:
    tailscale.com/funnel: "true"
spec:
  ingressClassName: tailscale
  # Configuration details
```

### 3. Secret Management

1Password integration via External Secrets:

```yaml
# Dashboard password from 1Password
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: rook-ceph-dashboard
spec:
  secretStoreRef:
    name: onepassword-connect
    kind: ClusterSecretStore
  target:
    name: rook-ceph-dashboard-password
  data:
    - secretKey: password
      remoteRef:
        key: rook-ceph
        property: dashboard_password
```

### 4. Backup Integration (Volsync)

Proven pattern from both repositories:

```yaml
# Volsync configuration
- Hourly snapshots
- Retention: 24h, 10d, 5w, 3m
- CSI snapshot integration
- Local + remote destinations
```

## Bootstrap Automation

Inspired by onedr0p's script approach:

```bash
#!/bin/bash
# bootstrap/rook-ceph-wipe.sh

wipe_rook_disks() {
  ROOK_DISK="nvme-WDC_WD_BLACK"  # Your disk pattern
  
  # Check if Rook is running
  if kubectl get pods -n storage | grep -q rook-ceph-operator; then
    echo "Rook is running, skipping disk wipe"
    return
  fi
  
  # Wipe disks on all nodes
  for node in k8s-1 k8s-2 k8s-3; do
    echo "Wiping disks on $node"
    # Talos-specific wipe commands
  done
}
```

## Safety Measures

### 1. Pre-deployment Checklist
- [ ] Verify kernel modules (RBD)
- [ ] Backup existing data
- [ ] Document disk serial numbers
- [ ] Test in isolated namespace first

### 2. Flux Safety Features
- `prune: false` on storage resources
- Extended timeouts (15m)
- Health checks before dependencies
- Drift detection disabled initially

### 3. Operational Safety
- Never force-delete Ceph resources
- Use suspend/resume for maintenance
- Monitor health states continuously
- Document all customizations

## Migration Strategy

### From Local-Path to Ceph

1. **Parallel Operation**
   - Deploy Ceph alongside local-path
   - No immediate migration required

2. **Test Workloads First**
   - Create test namespace
   - Deploy sample applications
   - Validate performance

3. **Gradual Migration**
   - Start with non-critical apps
   - Use Volsync for data migration
   - Maintain rollback capability

## Resource Specifications

Based on both repositories' experience:

### Minimal Start (onedr0p)
```yaml
# Just operator resources
operator:
  cpu: 100m
  memory: 128Mi
```

### Production Ready (joryirving)
```yaml
# Full component resources
mds:
  cpu: 100m / 2000m
  memory: 1Gi / 4Gi
rgw:
  cpu: 100m / 1000m
  memory: 1Gi / 2Gi
```

## Monitoring & Alerting

### Key Metrics to Track
- Cluster health states
- OSD usage and performance
- PG status and distribution
- Network throughput

### Alert Rules
- Storage capacity warnings
- Component availability
- Performance degradation
- Backup failures

## Code Examples Available

Real implementation examples can be provided upon request for:

1. **Complete Flux Kustomizations**
   - Operator deployment
   - Cluster configuration
   - Storage class definitions

2. **CephCluster Specifications**
   - Device selection
   - Network configuration
   - Resource limits

3. **Integration Examples**
   - Volsync backup configs
   - Dashboard ingress
   - Monitoring setup

4. **Helper Scripts**
   - Disk preparation
   - Health checking
   - Migration utilities

## Best Practices Summary

1. **Start Simple** (onedr0p approach)
   - Block storage only
   - Minimal configuration
   - Prove stability first

2. **Expand Thoughtfully** (joryirving approach)
   - Add features gradually
   - Monitor resource usage
   - Document everything

3. **Maintain Safety**
   - Use GitOps for all changes
   - Never edit resources directly
   - Keep backups current

4. **Stay Current**
   - Regular operator updates
   - Monitor Rook releases
   - Test upgrades carefully

## Hybrid Progressive Advantages

This unique approach offers several key benefits:

1. **Immediate Simplicity**
   - Start with just block storage (onedr0p style)
   - Minimal learning curve
   - Quick time to value

2. **Zero Refactoring**
   - Full structure exists from day one
   - Future phases just activate existing directories
   - No Git history pollution from restructuring

3. **Clear Growth Path**
   - `.disabled` suffix clearly shows what's available
   - Simple activation when features needed
   - Each phase builds on the previous

4. **Best Practices Built-In**
   - Safety measures from both repositories
   - Monitoring ready from Phase 1
   - Backup integration included

## Implementation Timeline

- **Week 1**: Phase 1 deployment (block only)
- **Month 1-3**: Gain operational experience
- **When Triggered**: Phase 2 (filesystem) activation
- **When Triggered**: Phase 3 (object) activation

## Next Steps

1. **Create** the full directory structure (including empty Phase 2/3)
2. **Deploy** Phase 1 components only
3. **Test** with non-critical workloads
4. **Monitor** for Phase 2/3 triggers
5. **Activate** additional phases as needed

This Hybrid Progressive GitOps structure provides the optimal balance between immediate simplicity and future flexibility. By combining the best patterns from onedr0p and joryirving, you get a production-ready storage solution that grows with your needs without requiring repository restructuring.