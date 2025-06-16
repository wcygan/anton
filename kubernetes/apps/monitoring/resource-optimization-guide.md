# Resource Optimization Implementation Guide

This guide provides step-by-step instructions for implementing the resource optimizations in your homelab cluster.

## Overview

The optimizations target:
1. Critical pods without resource specifications
2. Over-provisioned workloads (especially Trino)
3. Monitoring stack efficiency
4. Storage system resource usage

## Implementation Steps

### 1. Apply Critical Pod Resources

For each of the critical components, update their HelmRelease values:

#### kube-state-metrics
```yaml
# In kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml
spec:
  values:
    kube-state-metrics:
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 256Mi
```

#### node-exporter (DaemonSet)
```yaml
# In kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml
spec:
  values:
    prometheus-node-exporter:
      resources:
        requests:
          cpu: 50m
          memory: 64Mi
        limits:
          cpu: 200m
          memory: 128Mi
```

#### local-path-provisioner
```yaml
# In kubernetes/apps/storage/local-path-provisioner/app/helmrelease.yaml
spec:
  values:
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
```

#### reloader
```yaml
# In kubernetes/apps/kube-system/reloader/app/helmrelease.yaml
spec:
  values:
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
```

#### snapshot-controller
```yaml
# In kubernetes/apps/kube-system/snapshot-controller/app/helmrelease.yaml
spec:
  values:
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 256Mi
```

### 2. Optimize Trino Resources

Update the Trino HelmRelease with more efficient resource allocations:

```yaml
# In kubernetes/apps/data-platform/trino/app/helmrelease.yaml
spec:
  values:
    coordinator:
      jvm:
        maxHeapSize: "3G"  # Reduced from 4G
      resources:
        requests:
          cpu: "500m"      # Reduced from 1000m
          memory: "3Gi"    # Reduced from 4Gi
        limits:
          cpu: "1500m"     # Reduced from 2000m
          memory: "4Gi"    # Keep same
    
    worker:
      jvm:
        maxHeapSize: "4G"  # Reduced from 6G
      resources:
        requests:
          cpu: "1000m"     # Reduced from 1500m
          memory: "4Gi"    # Reduced from 6Gi
        limits:
          cpu: "2000m"     # Reduced from 3000m
          memory: "5Gi"    # Reduced from 6Gi
```

### 3. Optimize Monitoring Stack

Update the kube-prometheus-stack HelmRelease:

```yaml
# In kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml
spec:
  values:
    prometheusOperator:
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 256Mi
    
    grafana:
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 512Mi
    
    prometheus:
      prometheusSpec:
        resources:
          requests:
            cpu: 500m
            memory: 2Gi
          limits:
            cpu: 2000m
            memory: 4Gi
        retention: 7d
        retentionSize: 10GB
        walCompression: true
    
    alertmanager:
      alertmanagerSpec:
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
```

### 4. Deploy Monitoring Dashboards

Add the new dashboards to your kustomization:

```yaml
# In kubernetes/apps/monitoring/kube-prometheus-stack/app/kustomization.yaml
resources:
  - helmrelease.yaml
  - servicemonitor.yaml
  - resource-alerts.yaml  # Add this
configMapGenerator:
  - name: grafana-dashboards
    files:
      - dashboards/cluster-resource-efficiency.json
      - dashboards/namespace-resource-utilization.json
      # ... other existing dashboards
```

### 5. Enable Resource Alerts

The PrometheusRule for resource monitoring is already created. Ensure it's included in your kustomization and that your alerting channels are configured.

### 6. Monitor the Changes

After applying the changes:

1. **Check pod restarts**: 
   ```bash
   kubectl get pods -A -o wide | grep -E "(Restart|CrashLoop)"
   ```

2. **Monitor resource usage**:
   ```bash
   ./scripts/k8s-health-check.ts --verbose
   ```

3. **Check for throttling**:
   ```bash
   kubectl top pods -A --sort-by=cpu
   ```

4. **View new dashboards**:
   - Navigate to Grafana
   - Find "Cluster Resource Efficiency" dashboard
   - Check for over/under-provisioned pods

### 7. Fine-tuning

Based on monitoring data after 24-48 hours:

1. **For under-provisioned pods** (>80% usage consistently):
   - Increase requests by 20-50%
   - Monitor for throttling

2. **For over-provisioned pods** (<20% usage consistently):
   - Reduce requests by 30-50%
   - Keep limits higher for burst capacity

3. **For critical services**:
   - Maintain conservative limits
   - Focus on request accuracy

## Rollback Plan

If issues occur:

1. **Immediate rollback**:
   ```bash
   flux suspend hr <app-name> -n <namespace>
   git revert HEAD
   git push
   flux resume hr <app-name> -n <namespace>
   ```

2. **Gradual adjustment**:
   - Increase problematic resource limits first
   - Monitor for stability
   - Adjust requests after confirmation

## Expected Benefits

After implementation:
- **CPU efficiency**: 15-30% reduction in requested CPU
- **Memory efficiency**: 20-40% reduction in requested memory
- **Better scheduling**: More room for new workloads
- **Cost optimization**: Better resource utilization
- **Stability**: Appropriate limits prevent resource starvation

## Monitoring Success

Track these metrics:
- CPU/Memory efficiency per namespace (target: 50-80%)
- Pod throttling rate (target: <5%)
- OOM kills (target: 0)
- Cluster resource headroom (target: >20%)