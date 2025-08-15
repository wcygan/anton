# Storage Operations Golden Rules

## Rule #1: Never Force Delete Storage Resources

**Storage resources have data gravity - they can't just be recreated.**

### NEVER Do This:
```bash
# CATASTROPHIC - Will cause data loss
kubectl delete pvc my-database-pvc --force --grace-period=0
kubectl delete cephcluster -n storage --force
```

### Safe Approach:
```bash
# 1. Check what's using the PVC
kubectl get pods -A -o json | jq '.items[] | select(.spec.volumes[]?.persistentVolumeClaim.claimName=="my-pvc")'

# 2. Scale down workloads first
kubectl scale deployment my-app --replicas=0

# 3. Backup data if needed
kubectl exec -it my-pod -- tar czf /tmp/backup.tar.gz /data

# 4. Then delete PVC normally
kubectl delete pvc my-pvc
```

## Rule #2: Monitor Ceph Health Before Operations

**Never modify storage during degraded state.**

### Pre-Operation Checks:
```bash
# Check Ceph cluster health
kubectl exec -n storage deploy/rook-ceph-tools -- ceph status

# Ensure HEALTH_OK before proceeding
kubectl exec -n storage deploy/rook-ceph-tools -- ceph health detail

# Check OSD status
kubectl exec -n storage deploy/rook-ceph-tools -- ceph osd tree
```

### Warning Signs (DO NOT PROCEED):
- `HEALTH_WARN` or `HEALTH_ERR`
- Any OSD marked as `down`
- Rebalancing in progress
- Low space warnings (<20% free)

## Rule #3: Respect Storage Capacity Limits

**Monitor usage proactively - Ceph fails catastrophically when full.**

### Capacity Monitoring:
```bash
# Check cluster usage
kubectl exec -n storage deploy/rook-ceph-tools -- ceph df

# Check pool usage
kubectl exec -n storage deploy/rook-ceph-tools -- ceph osd pool stats

# Check PVC usage
kubectl exec -it <pod> -- df -h
```

### Capacity Thresholds:
- **50%**: Start planning for expansion
- **70%**: Order new drives
- **80%**: Actively migrate data
- **85%**: CRITICAL - Immediate action required
- **90%**: Cluster may become read-only

## Rule #4: Backup Before Storage Changes

**All storage operations should be preceded by backups.**

### Before Any Storage Operation:
```bash
# 1. List all PVCs
kubectl get pvc -A

# 2. For each critical PVC, create backup
kubectl exec -it <pod> -- mysqldump > backup.sql
kubectl exec -it <pod> -- pg_dump > backup.sql
kubectl exec -it <pod> -- tar czf - /data | gzip > backup.tar.gz

# 3. Verify backup
tar -tzf backup.tar.gz | head
```

## Rule #5: Never Resize Without Checking Support

**Not all storage classes support expansion.**

### Check Before Resize:
```bash
# Check if storage class supports expansion
kubectl get storageclass -o json | jq '.items[] | {name: .metadata.name, allowVolumeExpansion: .allowVolumeExpansion}'

# Safe resize process
kubectl patch pvc my-pvc -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'

# Monitor resize
kubectl describe pvc my-pvc | grep -A5 "Conditions:"
```

## Rule #6: Handle Failed Pods Carefully

**Storage-related pod failures need investigation, not deletion.**

### When Pods Won't Start:
```bash
# 1. Check events
kubectl describe pod <pod-name> | grep -A10 Events

# 2. Common storage issues:
# - "failed to attach volume" → Check node status
# - "volume is already attached" → Check for zombie attachments
# - "failed to mount" → Check filesystem corruption

# 3. Fix attachment issues
kubectl delete volumeattachment <attachment-name>
```

## Rule #7: Maintain Rook-Ceph Carefully

**Rook operator and Ceph have complex interdependencies.**

### Upgrade Process:
```bash
# 1. Check current versions
kubectl -n storage get cephcluster -o jsonpath='{.items[0].spec.cephVersion.image}'

# 2. Always upgrade operator first
helm upgrade rook-ceph-operator rook-release/rook-ceph

# 3. Wait for operator to stabilize
kubectl -n storage wait --for=condition=ready pod -l app=rook-ceph-operator

# 4. Then upgrade cluster
kubectl -n storage patch cephcluster storage --type merge -p '{"spec":{"cephVersion":{"image":"..."}}}'
```

## Rule #8: Clean Up Properly

**Storage resources can leave orphaned objects.**

### Proper Cleanup Sequence:
```bash
# 1. Delete workload
kubectl delete deployment my-app

# 2. Delete PVC
kubectl delete pvc my-app-data

# 3. Verify PV is released
kubectl get pv | grep my-app

# 4. If PV stuck in "Released"
kubectl patch pv <pv-name> -p '{"spec":{"claimRef": null}}'

# 5. Clean up Ceph RBD images if needed
kubectl exec -n storage deploy/rook-ceph-tools -- rbd ls replicapool
```

## Rule #9: Monitor Storage Performance

**Degraded performance often precedes failures.**

### Performance Monitoring:
```bash
# Check I/O stats
kubectl exec -n storage deploy/rook-ceph-tools -- ceph osd perf

# Check slow requests
kubectl exec -n storage deploy/rook-ceph-tools -- ceph health detail | grep slow

# Test performance
kubectl exec -it <pod> -- dd if=/dev/zero of=/data/test bs=1M count=1000
```

## Rule #10: Document Storage Layout

**Keep track of what data lives where.**

### Storage Documentation:
```yaml
# storage-map.yaml
applications:
  postgresql:
    pvc: postgres-data
    size: 50Gi
    backupSchedule: "0 2 * * *"
    criticalData: true
  
  monitoring:
    pvc: prometheus-data
    size: 100Gi
    retentionDays: 30
    criticalData: false
```

## Emergency Procedures

### Ceph Cluster Unhealthy:
```bash
# 1. Don't panic
# 2. Check what's wrong
kubectl exec -n storage deploy/rook-ceph-tools -- ceph health detail

# 3. Common fixes:
# - Clock skew: Sync time on all nodes
# - OSD down: Check node health
# - PG stuck: May self-resolve, monitor

# 4. Enable debug logging if needed
kubectl exec -n storage deploy/rook-ceph-tools -- ceph config set global debug_osd 10
```

### Data Recovery:
```bash
# If PVC deleted but PV remains
kubectl patch pv <pv-name> --type json -p '[{"op": "remove", "path": "/spec/claimRef"}]'

# Create new PVC with same name
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: recovered-pvc
spec:
  volumeName: <pv-name>
  # ... rest of spec
EOF
```

## Remember

> **Storage is stateful. Unlike pods, you can't just delete and recreate. Every operation needs careful planning and often backups.**