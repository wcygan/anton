# Logging Stack Recovery Plan

## MCP Server Usage for Recovery

Use MCP servers to guide the recovery process:

### Current State Analysis
```bash
# Assess current deployment
/mcp kubernetes:kubectl_get "helmrelease" "monitoring" 
/mcp kubernetes:kubectl_get "pods" "monitoring" "-l app.kubernetes.io/part-of=loki"

# Check storage backend
/mcp kubernetes:kubectl_describe "statefulset" "monitoring" "loki"
/mcp kubernetes:kubectl_get "pvc" "monitoring"

# Verify Ceph health
/mcp kubernetes:kubectl_get "cephcluster" "storage" "storage"
/mcp kubernetes:kubectl_describe "cephobjectstore" "storage" "storage"
```

### Recovery Planning
```bash
# Analyze migration path
/mcp sequential-thinking:sequential_thinking "We have Loki deployed with filesystem storage and Promtail. Design a zero-downtime migration plan to switch to S3 storage with Alloy, considering data retention and service continuity"

# Research best practices
/mcp context7:get-library-docs /grafana/loki "migrate storage backend" 4000
/mcp context7:get-library-docs /grafana/alloy "replace promtail migration" 3000
```

## Current State
- ❌ Deviated from S3-first approach
- ❌ Using Promtail instead of Alloy
- ❌ Filesystem storage instead of S3
- ✅ Ceph cluster is healthy
- ✅ Stuck resources cleaned up

## Recovery Steps

### Phase 1: Remove Current Deployment

#### MCP Commands for Safe Removal
```bash
# Backup current configuration first
/mcp kubernetes:kubectl_get "helmrelease" "monitoring" "loki" "-o yaml" > loki-backup.yaml
/mcp kubernetes:kubectl_get "configmap" "monitoring" "-l app.kubernetes.io/name=promtail" "-o yaml" > promtail-config-backup.yaml

# Check for any dependent resources
/mcp kubernetes:kubectl_get "all" "monitoring" "-l app.kubernetes.io/part-of=loki"

# Safe removal process
/mcp kubernetes:kubectl_delete "kustomization" "flux-system" "loki"
/mcp kubernetes:kubectl_delete "kustomization" "flux-system" "promtail"

# Wait for cleanup
/mcp kubernetes:kubectl_get "pods" "monitoring" "-l app.kubernetes.io/name=loki" "--watch"
```

```bash
# Delete current logging stack
kubectl delete kustomization loki promtail -n monitoring
kubectl delete helmrelease loki promtail -n monitoring
kubectl delete pvc storage-loki-0 -n monitoring

# Remove the deployments
rm -rf kubernetes/apps/monitoring/loki
rm -rf kubernetes/apps/monitoring/promtail
```

### Phase 2: Fix Ceph ObjectStore

#### MCP Commands for ObjectStore Validation
```bash
# Check current ObjectStore status
/mcp kubernetes:kubectl_get "cephobjectstore" "storage" 
/mcp kubernetes:kubectl_describe "cephobjectstore" "storage" "storage"

# Monitor deployment
/mcp kubernetes:kubectl_get "pods" "storage" "-l app=rook-ceph-rgw" "--watch"

# Verify S3 endpoint
/mcp kubernetes:kubectl_get "service" "storage" "rook-ceph-rgw-storage"

# Test S3 connectivity
/mcp kubernetes:kubectl_generic "run" "-it" "--rm" "s3-test" "--image=minio/mc:latest" "--restart=Never" "--" "mc" "alias" "set" "test" "http://rook-ceph-rgw-storage.storage.svc.cluster.local" "test" "test"
```

1. **Create proper ObjectStore configuration** without multisite:
```yaml
apiVersion: ceph.rook.io/v1
kind: CephObjectStore
metadata:
  name: storage
  namespace: storage
spec:
  metadataPool:
    replicated:
      size: 3
  dataPool:
    replicated:
      size: 3
  preservePoolsOnDelete: false
  gateway:
    port: 80
    instances: 2
    priorityClassName: system-cluster-critical
```

2. **Re-enable ObjectStore**:
```bash
cd kubernetes/apps/storage/rook-ceph-objectstore/
# Ensure ks.yaml exists (not disabled)
git add -A && git commit -m "fix(storage): re-enable ObjectStore with simplified config"
git push
```

### Phase 3: Deploy Alloy (not Promtail)

#### MCP Commands for Alloy Deployment
```bash
# Research Alloy deployment
/mcp context7:get-library-docs /grafana/alloy "helm chart values" 3000

# Check available versions
/mcp sequential-thinking:sequential_thinking "What are the key differences between Alloy and Promtail for Kubernetes log collection, and what migration considerations should be addressed?"

# Monitor deployment
/mcp kubernetes:kubectl_get "daemonset" "monitoring" "alloy" "--watch"
/mcp kubernetes:kubectl_logs "monitoring" "-l app.kubernetes.io/name=alloy" "--tail=50"
```

The correct Alloy chart is available as `grafana/alloy` (not just `alloy`):
- Chart: `grafana/alloy`
- Latest version: Check with `helm search repo grafana/alloy -l`

### Phase 4: Deploy Loki with S3

#### MCP Commands for Loki S3 Deployment
```bash
# Research S3 configuration
/mcp context7:get-library-docs /grafana/loki "s3 storage config ceph" 4000

# Validate deployment
/mcp kubernetes:kubectl_get "statefulset" "monitoring" "-l app.kubernetes.io/component=write"
/mcp kubernetes:kubectl_get "deployment" "monitoring" "-l app.kubernetes.io/component=read"

# Check S3 connectivity from Loki
/mcp kubernetes:kubectl_exec "monitoring" "loki-write-0" "--" "curl" "-I" "http://rook-ceph-rgw-storage.storage.svc.cluster.local"

# Monitor logs for S3 issues
/mcp kubernetes:kubectl_logs "monitoring" "loki-write-0" "--tail=100" | grep -i "s3"
```

Once S3 is working:
1. Deploy Loki in Simple Scalable mode
2. Configure S3 backend with Ceph
3. Use proper production configuration

## Why This Approach

1. **S3-First**: Avoids migration complexity later
2. **Alloy**: Modern, more features than Promtail
3. **Production Ready**: Scalable from day one
4. **No Technical Debt**: Clean implementation

## Decision Point

Do we:
1. **Option A**: Clean up and start fresh with S3-first approach
2. **Option B**: Keep current deployment and migrate later
3. **Option C**: Fix ObjectStore in parallel while using current deployment

Recommendation: **Option A** - Clean slate with proper S3 setup