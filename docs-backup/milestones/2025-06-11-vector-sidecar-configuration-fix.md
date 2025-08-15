# Milestone: Vector Sidecar Configuration Fix and Flux Issue Discovery

**Date**: 2025-06-11  
**Category**: Monitoring / Infrastructure  
**Status**: Partially Completed  
**Related**: [2025-06-11-airflow-vector-sidecar-deployment.md](./2025-06-11-airflow-vector-sidecar-deployment.md)

## Summary

Fixed Vector sidecar configuration errors in Airflow task pods and discovered critical Flux-system DNS/networking issues preventing GitOps reconciliation and Airflow deployment.

## Goals

- [x] Diagnose Vector sidecar deployment issues
- [x] Fix Vector configuration errors in pod template
- [x] Create ConfigMap for Vector configuration
- [ ] Complete validation tests (blocked by Flux issues)
- [ ] Verify log collection in Loki (blocked by Flux issues)

## Implementation Details

### Issues Discovered

1. **Vector Configuration Error**: The pod template was passing YAML config as a file path
   - Vector was interpreting the entire YAML as a glob pattern
   - Fixed by creating a separate ConfigMap and mounting it

2. **Critical Flux-System Issue**: 
   - DNS resolution failing: `lookup github.com: i/o timeout`
   - Internal service resolution failing: `lookup source-controller.flux-system.svc.cluster.local.: i/o timeout`
   - GitOps reconciliation completely blocked
   - Airflow HelmRelease not being deployed

### Configuration Changes

1. **Created Vector ConfigMap** (`vector-config.yaml`):
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: vector-sidecar-config
     namespace: airflow
   data:
     vector.yaml: |
       sources:
         task:
           type: file
           include: 
             - /proc/1/fd/1
             - /proc/1/fd/2
           read_from: beginning
       # ... rest of config
   ```

2. **Updated HelmRelease** to mount ConfigMap:
   ```yaml
   spec:
     volumes:
       - name: vector-config
         configMap:
           name: vector-sidecar-config
     containers:
       - name: vector
         args:
           - --config
           - /etc/vector/vector.yaml
         volumeMounts:
           - name: vector-config
             mountPath: /etc/vector
   ```

## Validation Status

### Completed
- ✅ Vector sidecar included in task pod spec
- ✅ Correct file paths configured (`/proc/1/fd/1` and `/proc/1/fd/2`)
- ✅ ConfigMap created and mounted properly

### Blocked by Flux Issues
- ❌ Cannot verify logs in Loki (Airflow not deployed)
- ❌ Cannot test Vector stability (no new task pods)
- ❌ Cannot measure performance impact
- ❌ Cannot verify Grafana dashboards

## Critical Issue: Flux-System Failure

### Symptoms
```
flux-system   cluster-apps   False     dependency 'flux-system/cluster-meta' is not ready
flux-system   cluster-meta   Unknown   Reconciliation in progress
flux-system   flux-system    False     failed to download archive: dial tcp: i/o timeout
```

### Impact
- No GitOps reconciliation occurring
- Latest git commits not being applied (stuck at sha1:e3ce86673...)
- Airflow deployment missing despite Kustomization existing
- Cannot complete Vector sidecar validation

### Root Cause Indicators
- DNS timeouts to external domains (github.com)
- DNS timeouts to internal services (*.svc.cluster.local)
- Possible CoreDNS or CNI networking issue

## Lessons Learned

1. **Vector Configuration**: The `--config-yaml` flag doesn't work as expected; use ConfigMap with file mount instead
2. **Dependency Chain**: GitOps failures cascade - when Flux can't reconcile, nothing deploys
3. **DNS Critical**: Cluster DNS issues affect both external connectivity and internal service discovery

## Next Steps

1. **URGENT**: Diagnose and fix Flux-system DNS/networking issues
   - Check CoreDNS pods and logs
   - Verify CNI (Cilium) health
   - Test DNS resolution from various pods
   - Check node networking

2. **After Flux Recovery**:
   - Verify Airflow deploys with Vector sidecar
   - Complete all validation tests from the original milestone
   - Monitor for 24 hours to ensure stability

## References

- [Original Vector Sidecar Milestone](./2025-06-11-airflow-vector-sidecar-deployment.md)
- [Vector Configuration Docs](https://vector.dev/docs/setup/deployment/roles/#sidecar)
- [Flux Troubleshooting](https://fluxcd.io/flux/troubleshooting/)