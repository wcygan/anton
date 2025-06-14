# Adding Ceph Storage to Anton Cluster

## Executive Summary

Successfully deployed Rook-Ceph v1.17.4 distributed storage solution to the Anton Kubernetes cluster. The deployment provides highly available, distributed block storage across 6 NVMe drives (2 per node) with 3-way replication. The cluster achieved HEALTH_OK status and is actively serving persistent volume claims.

### Key Achievements
-  Wiped and prepared 6 NVMe drives for Ceph OSDs
-  Deployed Rook operator and Ceph cluster via GitOps
-  Configured ceph-block as default storage class
-  Integrated 1Password for dashboard credentials
-  Set up Tailscale ingress for dashboard access
-  Verified PVC provisioning with test workload

### Outstanding Items & Next Steps

1. **Prometheus Monitoring** - Currently disabled due to template error with `external` field
   - Need to fix HelmRelease values to properly configure Prometheus rules
   - Re-enable `createPrometheusRules: true` once resolved

2. **VolumeSnapshot Support** - Snapshot class creation commented out
   - Enable after CSI driver stabilizes
   - Required for backup/restore functionality

3. **Volsync Integration** - Currently failing with chart version mismatch
   - Fix HelmChart reference for volsync v0.11.1
   - Required for cross-cluster replication

4. **Storage Migration** - Local-path provisioner still has existing PVCs
   - Plan migration of existing workloads to Ceph storage
   - Update applications to use new storage class

5. **Performance Tuning** - Using default Ceph configuration
   - Consider tuning based on workload patterns
   - Monitor and adjust resource limits as needed

## Prerequisites Completed

### Hardware Preparation
- 3x MS-01 nodes with 2x 1TB NVMe drives each
- Removed Talos mount configurations for NVMe drives
- Wiped existing partitions from all 6 drives

### Network Configuration
- Ceph using host network mode
- MON endpoints on node IPs: 192.168.1.98-100
- No dedicated storage network (using primary network)

## Implementation Process

### 1. Talos Configuration Updates

Removed legacy storage mount patches and regenerated Talos configuration:

```bash
# Deleted legacy mount configurations
rm -rf talos/patches/legacy/storage-with-mounts

# Regenerated Talos configs
task configure

# Applied to all nodes
task talos:apply-node IP=192.168.1.98 MODE=auto
task talos:apply-node IP=192.168.1.99 MODE=auto
task talos:apply-node IP=192.168.1.100 MODE=auto
```

### 2. GitOps Structure Creation

Created Rook-Ceph deployment following Hybrid Progressive approach:

```
kubernetes/
   flux/meta/repos/
      rook-release.yaml              # Helm repository
   apps/storage/
       rook-ceph-operator/            # Phase 1: Operator
          ks.yaml
          app/
              helmrelease.yaml
              kustomization.yaml
       rook-ceph-cluster/             # Phase 2: Cluster + Block
           ks.yaml
           app/
               helmrelease.yaml
               kustomization.yaml
               dashboard/
                   kustomization.yaml
                   certificate.yaml
                   ingress.yaml
                   secret.yaml
```

### 3. Key Configuration Decisions

#### Storage Class Configuration
```yaml
cephBlockPools:
  - name: replicapool
    spec:
      failureDomain: host
      replicated:
        size: 3
    storageClass:
      enabled: true
      name: ceph-block
      isDefault: true  # Set as default storage class
```

#### Resource Allocation
```yaml
resources:
  mgr:
    requests: { cpu: "100m", memory: "512Mi" }
    limits: { memory: "1Gi" }
  mon:
    requests: { cpu: "100m", memory: "512Mi" }
    limits: { memory: "2Gi" }
  osd:
    requests: { cpu: "500m", memory: "2Gi" }
    limits: { memory: "4Gi" }
```

#### Dashboard Access
- Created 1Password item for dashboard credentials
- Configured Tailscale ingress at `ceph-dashboard`
- Disabled SSL for internal access

### 4. Deployment Issues & Resolutions

#### Issue 1: Kubernetes API Timeout
After node reboots, kubectl commands failed with timeout.

**Resolution**:
```bash
talosctl -n 192.168.1.98 kubeconfig --force
```

#### Issue 2: OSD Creation Blocked
OSDs failed to create due to existing XFS partitions on NVMe drives.

**Resolution**:
```bash
# Wiped all NVMe drives on each node
talosctl -n 192.168.1.98 wipe disk nvme0n1 nvme1n1
talosctl -n 192.168.1.99 wipe disk nvme0n1 nvme1n1
talosctl -n 192.168.1.100 wipe disk nvme0n1 nvme1n1
```

#### Issue 3: PVC Provisioning Failure
Test PVCs remained in Pending state despite healthy cluster.

**Resolution**:
- Set `clusterName: storage` in cephClusterSpec
- Fixed clusterID mismatch between storage class and CSI configuration
- Removed duplicate default storage class annotation

#### Issue 4: HelmRelease Template Errors
Prometheus rules failed with missing `external` field.

**Temporary Resolution**:
```yaml
monitoring:
  createPrometheusRules: false  # TODO: Fix external field issue
```

### 5. Verification Steps

#### Cluster Health Check
```bash
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
```

Output showing healthy cluster:
```
cluster:
  id:     58ae2262-9536-478a-aa14-fa34b8d7ff07
  health: HEALTH_OK

services:
  mon: 3 daemons, quorum a,b,c
  mgr: a(active), standbys: b
  osd: 6 osds: 6 up, 6 in

data:
  pools:   12 pools, 393 pgs
  objects: 247 objects, 3.8 MiB
  usage:   178 MiB used, 5.5 TiB / 5.5 TiB avail
```

#### Storage Class Verification
```bash
kubectl get storageclass
```

Output:
```
NAME                   PROVISIONER                  RECLAIMPOLICY   VOLUMEBINDINGMODE      
ceph-block (default)   rook-ceph.rbd.csi.ceph.com   Delete          Immediate              
local-path             rancher.io/local-path        Delete          WaitForFirstConsumer   
```

#### PVC Test
Created test PVC and pod to verify provisioning:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-ceph-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-block
  resources:
    requests:
      storage: 1Gi
```

Result: PVC successfully bound and mounted by test pod.

## Migration Considerations

### Current Storage Usage
- Existing PVCs on local-path provisioner need migration
- Applications requiring persistent storage should be updated
- Consider data migration strategy for stateful workloads

### Recommended Migration Order
1. Test/development workloads first
2. Non-critical applications
3. Monitoring and logging systems
4. Critical production workloads

## Monitoring & Maintenance

### Dashboard Access
- URL: `https://ceph-dashboard` (via Tailscale)
- Credentials: Stored in 1Password vault
- Features: Cluster health, pool statistics, OSD performance

### Health Monitoring Commands
```bash
# Overall cluster health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health

# OSD status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd status

# Pool statistics
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df

# I/O statistics
kubectl -n storage exec deploy/rook-ceph-tools -- ceph iostat
```

### Maintenance Tasks
- Regular health checks via monitoring scripts
- OSD disk usage monitoring (currently at ~3% usage)
- Performance baseline establishment
- Backup strategy implementation (pending volsync)

## Future Enhancements

### Phase 3: CephFS Implementation
- Shared filesystem for multi-pod access
- ReadWriteMany (RWX) support
- Useful for shared data volumes

### Phase 4: Object Storage (S3)
- S3-compatible object storage
- Integration with backup solutions
- Media and artifact storage

### Performance Optimization
- Enable compression for specific workloads
- Tune PG numbers based on usage patterns
- Consider cache tiering for hot data

### Disaster Recovery
- Cross-site replication setup
- Automated backup procedures
- Recovery testing protocols

## Troubleshooting Guide

### Common Issues

1. **PVC Stuck in Pending**
   - Check storage class exists: `kubectl get sc`
   - Verify CSI pods running: `kubectl get pods -n storage | grep csi`
   - Check provisioner logs: `kubectl logs -n storage -l app=csi-rbdplugin-provisioner`

2. **OSD Won't Start**
   - Check disk availability: `kubectl -n storage logs -l app=rook-ceph-osd-prepare`
   - Verify no existing partitions
   - Check node resources

3. **Cluster Health Warnings**
   - Use ceph tools pod for diagnostics
   - Check mon quorum status
   - Verify network connectivity between nodes

### Support Resources
- [Rook Documentation](https://rook.io/docs/rook/latest)
- [Ceph Documentation](https://docs.ceph.com/)
- Cluster-specific notes in `/docs/ceph/`

## Conclusion

The Rook-Ceph deployment provides Anton cluster with enterprise-grade distributed storage. While core functionality is operational, several enhancements and integrations remain to be completed. The system is production-ready for block storage workloads with appropriate monitoring and maintenance procedures in place.