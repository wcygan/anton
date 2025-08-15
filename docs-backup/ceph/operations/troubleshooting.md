# Ceph Troubleshooting Guide

## Overview
This guide provides solutions for common Ceph storage issues in the homelab cluster.

## Quick Diagnostics

### Get Detailed Cluster Status
```bash
# Full health detail
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail

# Recent cluster log entries
kubectl -n storage exec deploy/rook-ceph-tools -- ceph log last 20
```

## Common Issues and Solutions

### 1. HEALTH_WARN: X slow ops

**Symptoms**: 
- Cluster shows HEALTH_WARN
- Slow operations reported
- Application performance degraded

**Diagnosis**:
```bash
# Check which OSDs have slow ops
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail | grep slow

# Check OSD performance
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd perf
```

**Solution**:
1. Identify affected OSDs
2. Check node for high CPU/memory usage
3. Check network connectivity between nodes
4. If persistent, restart affected OSD:
   ```bash
   kubectl -n storage delete pod rook-ceph-osd-X-xxxxx
   ```

### 2. OSD Down or Out

**Symptoms**:
- `osd.X is down` in health status
- Reduced redundancy warnings

**Diagnosis**:
```bash
# Check OSD tree
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd tree

# Check specific OSD logs
kubectl -n storage logs rook-ceph-osd-X-xxxxx --tail=100
```

**Solution**:
1. Check if OSD pod is running:
   ```bash
   kubectl -n storage get pods | grep osd-X
   ```
2. If pod is crashed, check node health:
   ```bash
   talosctl -n 192.168.1.XX health
   ```
3. If disk failed, follow OSD replacement procedure

### 3. PVC Stuck in Pending

**Symptoms**:
- New PVC won't bind
- Events show provisioning errors

**Diagnosis**:
```bash
# Check PVC events
kubectl describe pvc <pvc-name> -n <namespace>

# Check CSI provisioner logs
kubectl -n storage logs -l app=csi-rbdplugin-provisioner --tail=50
```

**Solution**:
1. Verify storage class exists:
   ```bash
   kubectl get storageclass ceph-block
   ```
2. Check if pool has space:
   ```bash
   kubectl -n storage exec deploy/rook-ceph-tools -- ceph df
   ```
3. Check for resource quotas:
   ```bash
   kubectl describe resourcequota -n <namespace>
   ```

### 4. High Memory Usage on Ceph Pods

**Symptoms**:
- OSD or MON pods using excessive memory
- Pods getting OOMKilled

**Diagnosis**:
```bash
# Check pod resource usage
kubectl -n storage top pods

# Check OSD cache settings
kubectl -n storage exec deploy/rook-ceph-tools -- ceph config show osd.0 | grep cache
```

**Solution**:
1. Adjust OSD memory target in HelmRelease:
   ```yaml
   cephClusterSpec:
     resources:
       osd:
         limits:
           memory: "4Gi"
   ```
2. Apply changes:
   ```bash
   flux reconcile hr rook-ceph-cluster -n storage
   ```

### 5. Monitor Quorum Issues

**Symptoms**:
- `mon is down` warnings
- Monitor quorum at risk

**Diagnosis**:
```bash
# Check monitor status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph mon stat

# Check monitor connectivity
kubectl -n storage exec deploy/rook-ceph-tools -- ceph ping mon.a
```

**Solution**:
1. Check monitor pod status
2. Verify network connectivity between nodes
3. If monitor data corrupted, remove and re-add:
   ```bash
   # Use with extreme caution!
   kubectl -n storage exec deploy/rook-ceph-tools -- ceph mon remove <mon-id>
   ```

### 6. Cluster Full or Near Full

**Symptoms**:
- `HEALTH_WARN: X nearfull osd(s)`
- Write operations failing

**Diagnosis**:
```bash
# Check usage by pool
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df detail

# Check OSD usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd df tree
```

**Solution**:
1. Identify large PVCs:
   ```bash
   kubectl get pv -o json | jq -r '.items[] | select(.spec.csi.driver=="storage.csi.ceph.com") | "\(.spec.capacity.storage) \(.spec.claimRef.namespace)/\(.spec.claimRef.name)"' | sort -h
   ```
2. Clean up unnecessary data
3. Rebalance if needed:
   ```bash
   kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd reweight-by-utilization
   ```

## Emergency Procedures

### Complete Cluster Recovery

If cluster is completely down:

1. Check all nodes are up:
   ```bash
   kubectl get nodes
   ```

2. Check Rook operator:
   ```bash
   kubectl -n storage logs deployment/rook-ceph-operator
   ```

3. Force monitor rebuild (LAST RESORT):
   ```bash
   kubectl -n storage delete deployment rook-ceph-mon-a rook-ceph-mon-b rook-ceph-mon-c
   kubectl -n storage delete pvc rook-ceph-mon-a rook-ceph-mon-b rook-ceph-mon-c
   ```

### Data Recovery from Failed OSD

1. Mark OSD as out:
   ```bash
   kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd out osd.X
   ```

2. Wait for recovery:
   ```bash
   kubectl -n storage exec deploy/rook-ceph-tools -- ceph -w
   ```

3. Remove failed OSD:
   ```bash
   kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd purge osd.X --yes-i-really-mean-it
   ```

## Performance Tuning

### Enable Aggressive Compression
Already enabled in cluster config, verify with:
```bash
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd pool ls detail | grep compression
```

### Adjust PG Numbers
If performance is poor:
```bash
# Check current PG distribution
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd pool autoscale-status
```

## Monitoring Integration

### Check Prometheus Metrics
```bash
# Verify metrics are being scraped
kubectl -n monitoring exec -it prometheus-kube-prometheus-stack-prometheus-0 -- wget -O- http://rook-ceph-mgr.storage:9283/metrics | head -20
```

### Grafana Dashboard Issues
1. Verify ServiceMonitor exists:
   ```bash
   kubectl -n storage get servicemonitor
   ```
2. Check Prometheus targets in Grafana

## Useful Commands Reference

```bash
# Watch cluster status in real-time
kubectl -n storage exec -it deploy/rook-ceph-tools -- watch ceph status

# Check recent OSD operations
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd pool stats

# List all Ceph commands
kubectl -n storage exec deploy/rook-ceph-tools -- ceph help

# Get cluster configuration
kubectl -n storage exec deploy/rook-ceph-tools -- ceph config dump
```

## External Resources

- Rook Troubleshooting: https://rook.io/docs/rook/latest/Troubleshooting/
- Ceph Documentation: https://docs.ceph.com/en/reef/rados/troubleshooting/
- Ceph Users Mailing List: https://lists.ceph.io/postorius/lists/ceph-users.ceph.io/