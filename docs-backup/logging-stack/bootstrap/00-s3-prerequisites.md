# S3 Prerequisites for Loki Deployment

## Overview

This guide ensures Ceph ObjectStore (S3) is fully operational before deploying Loki. The S3-First approach eliminates migration complexity and ensures production-ready scalability from day one.

## Why S3-First?

- **No Migration Required**: Deploy once with the correct storage backend
- **Unlimited Scalability**: No PVC size limits or resize operations
- **Cost Efficiency**: Object storage pricing + 10:1 compression
- **Production Ready**: Enterprise-grade durability and availability
- **Future Proof**: Supports multi-tenancy and advanced retention policies

## Prerequisites Checklist

### 0. Clean Up Previous Failed Attempts (if applicable)

If you had previous ObjectStore deployment issues:

```bash
# Run cleanup script to remove stuck resources
./scripts/fix-stuck-ceph-resources.ts

# Verify cleanup
kubectl get cephobjectstore -A
kubectl get cephcluster -A
# Should only show healthy 'rook-ceph' cluster
```

### 1. Fix and Enable Ceph ObjectStore

First, ensure the ObjectStore configuration is correct to avoid multisite issues:

```bash
# Update the objectstore.yaml to use simplified configuration
cat > kubernetes/apps/storage/rook-ceph-objectstore/app/objectstore.yaml << 'EOF'
---
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
    parameters:
      compression_mode: passive
  preservePoolsOnDelete: false
  gateway:
    port: 80
    instances: 2
    priorityClassName: system-cluster-critical
    resources:
      requests:
        cpu: "100m"
        memory: "1Gi"
      limits:
        memory: "2Gi"
EOF

# Ensure all references use 'storage' as the ObjectStore name
sed -i '' 's/objectStoreName: .*/objectStoreName: storage/' kubernetes/apps/storage/rook-ceph-objectstore/app/storageclass.yaml
sed -i '' 's/name: rook-ceph-rgw-.*/name: rook-ceph-rgw-storage/' kubernetes/apps/storage/rook-ceph-objectstore/app/ingress.yaml

# Enable the ObjectStore if disabled
if [ -f kubernetes/apps/storage/rook-ceph-objectstore/ks.yaml.disabled ]; then
  mv kubernetes/apps/storage/rook-ceph-objectstore/ks.yaml.disabled kubernetes/apps/storage/rook-ceph-objectstore/ks.yaml
fi

# Commit and push the changes
git add -A
git commit -m "feat(storage): enable Ceph ObjectStore with simplified config for S3"
git push

# Force reconciliation
flux reconcile kustomization cluster-apps --with-source
```

### 2. Monitor ObjectStore Deployment

```bash
# Watch for ObjectStore pods
watch kubectl get pods -n storage -l app=rook-ceph-rgw

# Expected pods:
# - rook-ceph-rgw-storage-a-* (RADOS Gateway)
# - Additional RGW pods based on replicas

# Check ObjectStore status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
```

**Expected Duration**: 30-45 minutes for full deployment

### 3. Verify S3 Endpoint

```bash
# Get the S3 endpoint
kubectl -n storage get service rook-ceph-rgw-storage -o jsonpath='{.spec.clusterIP}'

# Should return something like: 10.43.x.x

# Test S3 connectivity (from inside cluster)
kubectl run -it --rm s3-test --image=minio/mc:latest --restart=Never -- \
  /bin/sh -c "mc alias set ceph http://rook-ceph-rgw-storage.storage.svc.cluster.local hello hello && mc ls ceph"
```

### 4. Create ObjectBucketClaim for Loki

Create `kubernetes/apps/monitoring/loki-s3-bucket/obc.yaml`:

```yaml
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: loki-bucket
  namespace: monitoring
spec:
  generateBucketName: loki-
  storageClassName: ceph-bucket
  additionalConfig:
    maxObjects: "1000000"
    maxSize: "500Gi"
```

Deploy the bucket claim:

```bash
kubectl apply -f kubernetes/apps/monitoring/loki-s3-bucket/obc.yaml

# Wait for bucket to be bound
kubectl get obc -n monitoring loki-bucket -w
```

### 5. Configure S3 Credentials via External Secrets

The ObjectBucketClaim will create a secret with S3 credentials. Create an ExternalSecret to make it available:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: loki-s3-credentials
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: kubernetes
    kind: SecretStore
  target:
    name: loki-s3-credentials
    template:
      data:
        endpoint: "{{ .endpoint }}"
        bucket: "{{ .bucket }}"
        access_key_id: "{{ .access_key_id }}"
        secret_access_key: "{{ .secret_access_key }}"
  dataFrom:
    - extract:
        key: loki-bucket # Secret created by OBC
```

### 6. Validate S3 Readiness

Run these validation steps before proceeding with Loki deployment:

```bash
# 1. Check if RGW pods are running
kubectl get pods -n storage -l app=rook-ceph-rgw

# 2. Verify ObjectStore is created
kubectl get cephobjectstore -n storage

# 3. Confirm bucket claim is bound
kubectl get obc -n monitoring

# 4. Check secret was created
kubectl get secret -n monitoring loki-bucket

# 5. Test S3 connectivity from monitoring namespace
kubectl run -it --rm s3-validate --namespace=monitoring \
  --image=amazon/aws-cli:latest --restart=Never -- \
  s3 ls --endpoint-url=http://rook-ceph-rgw-storage.storage.svc.cluster.local
```

## Troubleshooting

### RGW Pods Not Starting

```bash
# Check operator logs
kubectl logs -n storage deployment/rook-ceph-operator | grep -i rgw

# Check for PG issues
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail
```

### S3 Connection Refused

```bash
# Verify service exists
kubectl get svc -n storage rook-ceph-rgw-storage

# Check endpoint from inside cluster
kubectl run -it --rm debug --image=nicolaka/netshoot --restart=Never -- \
  curl -I http://rook-ceph-rgw-storage.storage.svc.cluster.local
```

### Bucket Creation Failed

```bash
# Check OBC controller logs
kubectl logs -n storage deployment/rook-ceph-operator | grep -i bucket

# Manually create bucket if needed
kubectl -n storage exec deploy/rook-ceph-tools -- \
  radosgw-admin bucket create --bucket=loki-logs
```

## Success Criteria

Before proceeding with Loki deployment, ensure:

- [ ] All RGW pods are Running (1/1 or 2/2)
- [ ] ObjectStore shows HEALTH_OK in Ceph status
- [ ] S3 endpoint responds to health checks
- [ ] ObjectBucketClaim is Bound
- [ ] S3 credentials secret exists
- [ ] Test bucket operations succeed

## Next Steps

Once all success criteria are met:

1. Proceed to add Grafana Helm repository
2. Deploy Loki with S3 backend configuration
3. Follow the main [Implementation Guide](02-implementation-guide.md)

## Time Estimate

- Enable ObjectStore: 5 minutes
- Wait for deployment: 30-45 minutes  
- Create bucket and credentials: 10 minutes
- Validation: 10 minutes
- **Total**: 60-70 minutes

This one-time investment ensures a production-ready logging infrastructure with no future migrations required.