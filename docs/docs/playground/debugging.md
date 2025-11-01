---
sidebar_position: 7
sidebar_label: Debugging Deployments
---

# Debugging Deployments

This guide documents common issues encountered when deploying databases in the playground environment and their solutions.

## Architecture Overview

```mermaid
flowchart TD
    subgraph playground[Playground Namespace]
        tidb[TiDB Cluster<br/>1 PD, 1 TiKV, 1 TiDB]
        dragonfly[Dragonfly<br/>1 replica]
        scylla[Scylla Cluster<br/>1 node]
    end

    subgraph databases[Databases Namespace]
        redpanda[Redpanda<br/>1 broker]
        redpanda_op[Redpanda Operator]
        scylla_op[Scylla Operator]
        tidb_op[TiDB Operator]
        dragonfly_op[Dragonfly Operator]
    end

    subgraph scylla_mgr_ns[Scylla Manager Namespace]
        manager[Scylla Manager]
        manager_db[Manager's Internal<br/>Scylla Cluster]
    end

    redpanda --> redpanda_op
    scylla --> scylla_op
    tidb --> tidb_op
    dragonfly --> dragonfly_op
    manager --> manager_db
    manager --> scylla_op

    classDef db fill:#4db6ac,color:white
    classDef operator fill:#ff8a65,color:white
    classDef mgmt fill:#9575cd,color:white

    class tidb,dragonfly,scylla,redpanda db
    class redpanda_op,scylla_op,tidb_op,dragonfly_op operator
    class manager,manager_db mgmt
```

## Common Issues & Solutions

### 1. Redpanda Memory Requirements

**Issue**: Redpanda crashes with memory check failure
```
ERROR Memory: '857735168' below recommended: '1073741824'
Crash loop detected. Too many consecutive crashes
```

**Root Cause**: Redpanda requires at least 2GB memory per core and validates this at startup.

**Solution**: Allocate proper resources
```yaml
resources:
  cpu:
    cores: 1
  memory:
    container:
      min: 2Gi
      max: 2Gi  # Must match for stability
```

**Key Points**:
- Minimum: 2GB per core (2.22 GiB recommended)
- Set min and max equal for QoS guaranteed class
- After crash loop, delete pod to clear crash history

```mermaid
flowchart LR
    config[Resource Config] --> validation{Memory Check}
    validation -->|< 2GB| crash[Crash Loop]
    validation -->|>= 2GB| start[Startup Success]
    crash --> limit{Crash Count}
    limit -->|>= 5| lockout[Startup Blocked]
    limit -->|< 5| retry[Retry]
    lockout -->|Delete Pod| clean[Clean State]
```

**Reference**: [Redpanda Kubernetes Requirements](https://docs.redpanda.com/current/deploy/redpanda/kubernetes/k-requirements/)

### 2. Scylla Manager Configuration

**Issue**: Manager's internal Scylla cluster fails to deploy
```
Pod name "scylla-manager-scylla-manager-manager-dc-manager-rack-HASH"
exceeds 63 character limit
storageclass.storage.k8s.io "scylladb-local-xfs" not found
Nodes must have label scylla.scylladb.com/node-type=scylla
```

**Root Causes**:
1. Kubernetes label length limit (63 chars)
2. Missing storage class
3. Node affinity requirement

**Solution**: Configure internal cluster for home lab
```yaml
scylla:
  developerMode: true
  datacenter: dc1  # Short name
  racks:
    - name: rack1  # Short name
      members: 1
      storage:
        capacity: 2Gi
        storageClassName: ceph-block  # Use available storage
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: 1000m
          memory: 1Gi
      placement: {}  # Remove node affinity
```

**Pod Name Construction**:
```
{helmrelease-name}-{datacenter}-{rack}-{hash}
scylla-manager-scylla-manager-dc1-rack1-84cc8b5966  # 46 chars ✓
```

```mermaid
flowchart TD
    subgraph manager[Scylla Manager Chart]
        mgr_pod[Manager Pod<br/>API: 5080<br/>Metrics: 5090]
        internal[Internal Scylla<br/>Cluster]
    end

    mgr_pod -->|Stores metadata| internal
    mgr_pod -->|Manages| playground[Playground<br/>Scylla Clusters]

    internal -->|Requires| storage[Storage Class<br/>ceph-block]
    internal -->|Placement| nodes[Any K8s Node<br/>placement: {}]

    classDef component fill:#7e57c2,color:white
    classDef resource fill:#42a5f5,color:white

    class mgr_pod,internal component
    class storage,nodes resource
```

**Reference**: [Scylla Operator Helm Installation](https://operator.docs.scylladb.com/stable/installation/helm.html)

### 3. Namespace-Scoped Operators

**Issue**: Redpanda operator doesn't see clusters in other namespaces
```
Redpanda cluster in 'playground' namespace status: "Waiting for controller"
```

**Root Cause**: Redpanda operator is namespace-scoped and only manages clusters in the same namespace.

**Solution**: Deploy clusters in the operator's namespace
```yaml
# Redpanda cluster must be in 'databases' namespace
spec:
  targetNamespace: databases  # Same as operator
```

**Operator Scope Comparison**:

| Operator | Scope | Cluster Location |
|----------|-------|-----------------|
| TiDB | Namespace-scoped | Any namespace (with ServiceAccount) |
| Dragonfly | Namespace-scoped | Same as operator |
| Redpanda | Namespace-scoped | Same as operator |
| Scylla | Cluster-scoped | Any namespace |

```mermaid
flowchart TD
    subgraph databases[Databases Namespace]
        redpanda_op[Redpanda Operator]
        redpanda_cluster[Redpanda Cluster]
    end

    subgraph playground[Playground Namespace]
        tidb[TiDB Cluster]
        dragonfly[Dragonfly]
        scylla[Scylla Cluster]
    end

    subgraph cluster[Cluster Scope]
        scylla_op[Scylla Operator]
    end

    redpanda_op -->|Manages| redpanda_cluster
    redpanda_op -.->|Cannot see| playground
    scylla_op -->|Manages| scylla

    classDef same fill:#66bb6a,color:white
    classDef cross fill:#ef5350,color:white
    classDef global fill:#42a5f5,color:white

    class redpanda_op,redpanda_cluster same
    class scylla_op global
```

### 4. Storage Class Configuration

**Issue**: PVC stuck in Pending state
```
persistentvolumeclaim/data-scylla Pending
storageclass.storage.k8s.io "scylladb-local-xfs" not found
```

**Root Cause**: Chart defaults to production storage classes not available in home labs.

**Solution**: Override with available storage
```yaml
storage:
  capacity: 2Gi
  storageClassName: ceph-block  # Use default storage class
```

**Check Available Storage Classes**:
```bash
kubectl get storageclass
# NAME                   PROVISIONER
# ceph-block (default)   storage.rbd.csi.ceph.com
# ceph-filesystem        storage.cephfs.csi.ceph.com
```

### 5. Developer Mode for Testing

**Issue**: Production requirements too strict for playground

**Solution**: Enable developer mode
```yaml
scylla:
  developerMode: true  # Relaxes production requirements
```

**Developer Mode Disables**:
- XFS filesystem requirement
- CPU pinning checks
- Memory locking validation
- Strict I/O configuration
- Node tuning requirements

## Verification Commands

### Check All Clusters
```bash
# Playground clusters
kubectl get tidbcluster,dragonfly,scyllacluster -n playground

# Redpanda
kubectl get redpanda -n databases

# Scylla Manager
kubectl get scyllacluster,pods -n scylla-manager
```

### Pod Status
```bash
# All playground pods
kubectl get pods -n playground

# Operator pods
kubectl get pods -n databases

# Check specific pod logs
kubectl logs -n databases redpanda-playground-0 -c redpanda --tail=50
```

### Resource Status
```bash
# HelmReleases
flux get hr -A

# Kustomizations
flux get ks -A

# Storage
kubectl get pvc -A
```

## Resource Allocations

### Final Working Configuration

| Database | CPU | Memory | Storage | Notes |
|----------|-----|--------|---------|-------|
| TiDB (total) | ~2 cores | ~2Gi | 3Gi | 1 PD + 1 TiKV + 1 TiDB |
| Dragonfly | 100m | 256Mi | - | In-memory only |
| Scylla | 500m-1000m | 512Mi-1Gi | 2Gi | Developer mode |
| Redpanda | 1 core | 2Gi | 2Gi | Strict requirements |
| Scylla Manager | 500m-1000m | 512Mi-1Gi | 2Gi | Internal cluster |

**Total Playground Resources**: ~4.5 cores, ~7Gi RAM, 9Gi storage

## Troubleshooting Workflow

```mermaid
flowchart TD
    start[Deployment Issue] --> check_hr{HelmRelease<br/>Ready?}
    check_hr -->|No| hr_logs[Check: kubectl describe hr]
    check_hr -->|Yes| check_cluster{Cluster CR<br/>Ready?}

    hr_logs --> schema{Schema<br/>Error?}
    schema -->|Yes| fix_values[Fix values.yaml]
    schema -->|No| check_deps[Check dependencies]

    check_cluster -->|No| describe[kubectl describe cluster]
    check_cluster -->|Yes| check_pods{Pods<br/>Running?}

    describe --> events[Check Events]
    events --> common{Common Issue?}

    common -->|Label too long| shorten[Shorten names]
    common -->|Storage not found| fix_storage[Update storageClassName]
    common -->|Node affinity| remove_affinity[Remove placement]

    check_pods -->|No| pod_logs[kubectl logs pod]
    check_pods -->|Yes| success[Healthy]

    pod_logs --> crash{Crash<br/>Loop?}
    crash -->|Memory| increase_mem[Increase resources]
    crash -->|Other| investigate[Check logs]

    classDef issue fill:#ef5350,color:white
    classDef action fill:#66bb6a,color:white
    classDef check fill:#42a5f5,color:white

    class start,schema,crash issue
    class fix_values,shorten,fix_storage,remove_affinity,increase_mem action
    class check_hr,check_cluster,check_pods,common check
```

## Additional Resources

- [Redpanda Kubernetes Requirements](https://docs.redpanda.com/current/deploy/redpanda/kubernetes/k-requirements/)
- [Scylla Operator Installation](https://operator.docs.scylladb.com/stable/installation/overview.html)
- [TiDB Operator Documentation](https://docs.pingcap.com/tidb-in-kubernetes/stable)
- [Dragonfly Documentation](https://www.dragonflydb.io/docs)
