# Ceph Migration Log

## 2025-06-09 - Test Workload Migrations

### DragonflyDB Test Cache (df-test-cache-0)

**Status**: In Progress
**Start Time**: 2025-06-09T17:30:00Z

#### Pre-Migration State
- **PVC**: df-test-cache-0 
- **Namespace**: database
- **Size**: 1Gi
- **StorageClass**: local-path
- **Node**: k8s-3
- **Pod**: test-cache-0 (Running)

#### Migration Steps

1. **Create new PVC on Ceph** (17:30:00Z)
   - Created df-test-cache-0-ceph PVC
   - PVC bound successfully to Ceph

2. **Scale down workload** (17:32:00Z)
   - Scaled DragonFly replicas to 0
   - Pod terminated successfully

3. **Migration Result** (17:35:00Z)
   - **Status**: BLOCKED
   - **Issue**: DragonFly operator doesn't support changing storage class for existing StatefulSets
   - **Resolution**: Would require deleting and recreating the entire DragonFly CR
   - **Decision**: Skip this workload, proceed to PostgreSQL test cluster

### PostgreSQL Test Cluster (test-postgres-cluster-1)

**Status**: In Progress  
**Start Time**: 2025-06-09T17:40:00Z

#### Pre-Migration State
- **PVC**: test-postgres-cluster-1
- **Namespace**: database
- **Size**: 5Gi
- **StorageClass**: local-path
- **Node**: k8s-2
- **Type**: CloudNative-PG Cluster

#### Migration Steps

1. **Analyze CNPG migration options** (17:40:00Z)
   - CNPG requires specialized backup/restore procedures
   - Would need to use pg_dump/pg_restore or CNPG backup CRs
   - **Decision**: Skip for now, focus on simpler workloads first

## Application Storage Migrations

### Open WebUI (open-webui)

**Status**: Starting
**Start Time**: 2025-06-09T17:45:00Z

#### Pre-Migration State
- **PVC**: open-webui
- **Namespace**: kubeai
- **Size**: 2Gi
- **StorageClass**: local-path
- **Node**: k8s-2
- **Type**: Regular deployment (managed by Helm)

#### Migration Steps

1. **Migration Strategy Update** (17:45:00Z)
   - User confirmed: No need to preserve data
   - Strategy: Delete and recreate with Ceph storage
   - Approach: Direct replacement without data migration

## Simplified Migration Execution

### Storage Class Configuration Fix

**Status**: ✅ COMPLETED  
**Time**: 2025-06-09T18:15:00Z

1. **Fixed default storage class conflict**
   - Removed default annotation from local-path
   - Verified ceph-block is now the only default
   - Command: `kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'`

### 1. DragonflyDB Test Cache - Direct Recreation

**Status**: ✅ COMPLETED  
**Time**: 2025-06-09T18:16:00Z

1. **Delete existing DragonFly CR**
   - Command: `kubectl delete dragonfly test-cache -n database`
   - StatefulSet and pods deleted successfully
   
2. **Delete old PVC**
   - Command: `kubectl delete pvc df-test-cache-0 -n database`
   - PVC removed successfully
   
3. **Recreate with Ceph storage**
   - Command: `flux reconcile kustomization test-cache -n flux-system --with-source`
   - New PVC created: df-test-cache-0 with ceph-block storage class
   - Pod running successfully on Ceph storage

### 2. CNPG Test PostgreSQL Cluster - Direct Recreation

**Status**: ✅ COMPLETED  
**Time**: 2025-06-09T18:18:00Z

1. **Delete existing CNPG cluster**
   - Command: `kubectl delete cluster.postgresql.cnpg.io test-postgres-cluster -n database`
   - Cluster and all resources cleaned up
   
2. **Update cluster manifest**
   - Modified cluster.yaml to explicitly specify `storageClassName: "ceph-block"`
   - Git changes committed
   
3. **Recreate cluster**
   - Command: `flux reconcile kustomization test-db -n flux-system --with-source`
   - New PVC created: test-postgres-cluster-1 with ceph-block storage class
   - PostgreSQL cluster running on Ceph storage

## Migration Summary

### Completed Migrations (2025-06-09)

| Workload | Namespace | Old Storage | New Storage | Status |
|----------|-----------|-------------|-------------|---------|
| test-cache (DragonFly) | database | local-path | ceph-block | ✅ COMPLETED |
| test-postgres-cluster (CNPG) | database | local-path | ceph-block | ✅ COMPLETED |

### Remaining Workloads

| Workload | Namespace | Storage Class | Size | Notes |
|----------|-----------|---------------|------|-------|
| data-airflow-postgresql-0 | airflow | local-path | 8Gi | Requires Helm values update |
| logs-airflow-triggerer-0 | airflow | local-path | 100Gi | Requires Helm values update |
| open-webui | kubeai | local-path | 2Gi | Requires Helm values update |

### Key Learnings

1. **Operator-managed workloads require full recreation** - Cannot change storage class in-place
2. **Always specify storage class explicitly** in manifests to avoid default confusion
3. **Delete and recreate is simplest** when data preservation isn't required
4. **Fix infrastructure issues first** - Having two default storage classes caused confusion

### Next Steps

1. Update Airflow Helm values to specify ceph-block for PostgreSQL and Triggerer
2. Update Open WebUI Helm values to specify ceph-block
3. Create automated migration script for remaining workloads
4. Document this pattern for future migrations