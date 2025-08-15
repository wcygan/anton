# Rook Ceph Helm Charts Quickstart

This document provides a comprehensive guide for deploying Rook Ceph storage on Kubernetes using Helm charts.

## Overview

Rook Ceph consists of two primary Helm charts:
1. **Rook Ceph Operator**: Manages the lifecycle of Ceph clusters
2. **Rook Ceph Cluster**: Deploys and configures the actual Ceph storage cluster

## Prerequisites

- Kubernetes 1.21+ cluster
- Helm 3.x installed
- Sufficient raw storage devices on worker nodes
- At least 3 nodes for production deployments (recommended)

## Rook Ceph Operator Chart

### Repository Setup

```bash
helm repo add rook-release https://charts.rook.io/release
helm repo update
```

### Installation

```bash
helm install --create-namespace --namespace rook-ceph rook-ceph rook-release/rook-ceph -f values.yaml
```

### Key Configuration Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Rook operator image | `rook/ceph` |
| `image.tag` | Image tag | Latest release |
| `csi.enabled` | Enable Ceph CSI drivers | `true` |
| `csi.cephfs.enabled` | Enable CephFS CSI driver | `true` |
| `csi.rbd.enabled` | Enable RBD CSI driver | `true` |
| `monitoring.enabled` | Enable Prometheus monitoring | `false` |
| `crds.enabled` | Install CRDs | `true` |

### Important Notes

- **Namespace**: Always deploy in `rook-ceph` namespace
- **CRDs**: Never disable CRDs unless you're managing them separately
- **Disaster Recovery**: If CRDs are accidentally deleted, consult the disaster recovery guide

## Rook Ceph Cluster Chart

### Prerequisites

The Rook Operator must be running before deploying the cluster chart.

### Installation

```bash
helm install --create-namespace --namespace rook-ceph rook-ceph-cluster \
    --set operatorNamespace=rook-ceph rook-release/rook-ceph-cluster -f values.yaml
```

### Key Configuration Options

| Parameter | Description | Example |
|-----------|-------------|---------|
| `operatorNamespace` | Namespace where operator is installed | `rook-ceph` |
| `cephClusterSpec.mon.count` | Number of Ceph monitors | `3` |
| `cephClusterSpec.dashboard.enabled` | Enable Ceph dashboard | `true` |
| `cephClusterSpec.storage.useAllNodes` | Use all nodes for storage | `true` |
| `cephClusterSpec.storage.useAllDevices` | Use all available devices | `false` |
| `cephBlockPools[].name` | Block pool name | `replicapool` |
| `cephBlockPools[].spec.replicated.size` | Replication factor | `3` |

### Storage Configuration Examples

#### Block Storage Pool
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
      isDefault: true
      reclaimPolicy: Delete
```

#### CephFS Filesystem
```yaml
cephFileSystems:
  - name: cephfs
    spec:
      metadataPool:
        replicated:
          size: 3
      dataPools:
        - replicated:
            size: 3
    storageClass:
      enabled: true
      name: ceph-filesystem
```

#### Object Storage
```yaml
cephObjectStores:
  - name: ceph-objectstore
    spec:
      metadataPool:
        replicated:
          size: 3
      dataPool:
        replicated:
          size: 3
      gateway:
        instances: 1
    storageClass:
      enabled: true
      name: ceph-bucket
```

## Production Recommendations

1. **Hardware Requirements**
   - Minimum 3 nodes for data redundancy
   - Dedicated storage devices (not OS disks)
   - 10GB+ network for optimal performance

2. **Resource Allocation**
   ```yaml
   cephClusterSpec:
     resources:
       mon:
         requests:
           cpu: 1000m
           memory: 1Gi
         limits:
           cpu: 2000m
           memory: 2Gi
       osd:
         requests:
           cpu: 1000m
           memory: 4Gi
         limits:
           cpu: 2000m
           memory: 8Gi
   ```

3. **Monitoring**
   - Enable Prometheus monitoring in both charts
   - Configure alerts for disk usage and cluster health
   - Monitor OSD status and placement group health

4. **Security**
   - Enable network encryption between Ceph daemons
   - Use separate network for Ceph cluster traffic
   - Regularly rotate encryption keys

## Upgrade Process

1. **Upgrade Operator First**
   ```bash
   helm upgrade --namespace rook-ceph rook-ceph rook-release/rook-ceph
   ```

2. **Wait for Operator to be Ready**
   ```bash
   kubectl -n rook-ceph wait --for=condition=ready pod -l app=rook-ceph-operator
   ```

3. **Upgrade Cluster**
   ```bash
   helm upgrade --namespace rook-ceph rook-ceph-cluster rook-release/rook-ceph-cluster
   ```

## Uninstallation

**Warning**: This will not remove data from host devices.

1. **Delete Cluster**
   ```bash
   helm delete --namespace rook-ceph rook-ceph-cluster
   ```

2. **Delete Operator**
   ```bash
   helm delete --namespace rook-ceph rook-ceph
   ```

3. **Clean Host Devices** (if needed)
   - Follow official cleanup documentation
   - Wipe disks if redeploying

## Troubleshooting

### Common Issues

1. **OSD Pods Not Starting**
   - Check available devices: `kubectl -n rook-ceph logs -l app=rook-ceph-operator`
   - Verify devices are empty and not formatted
   - Check node selectors and taints

2. **Slow Performance**
   - Verify network bandwidth between nodes
   - Check OSD resource limits
   - Monitor placement group distribution

3. **Storage Class Not Working**
   - Verify CSI drivers are running
   - Check RBAC permissions
   - Validate pool configuration

### Useful Commands

```bash
# Check cluster health
kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph status

# List storage devices
kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph osd tree

# Check placement groups
kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph pg stat
```

## References

- [Rook Documentation](https://rook.io/docs/rook/latest-release/)
- [Ceph Documentation](https://docs.ceph.com/)
- [Helm Charts Repository](https://github.com/rook/rook/tree/master/deploy/charts)