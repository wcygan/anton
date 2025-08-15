# Flux GitOps Monitoring

This guide covers the monitoring setup for Flux v2 GitOps operations in the homelab cluster.

## Overview

The Flux monitoring stack provides:
- Real-time visibility into GitOps reconciliation status
- Performance metrics for all Flux controllers
- Alerting for failures and performance degradation
- Historical data for troubleshooting

## Components

### 1. Grafana Dashboard

**Dashboard Name**: Flux Cluster Stats  
**Dashboard UID**: `flux-cluster-stats`  
**Location**: `kubernetes/apps/monitoring/grafana-dashboards/flux/`

The dashboard provides:
- **Overview Stats**: Failing resources, success rate, ready resources, average reconciliation time
- **Resource Status**: Table view of all resources with their readiness state
- **Resource Distribution**: Pie chart showing resources by kind
- **Performance Metrics**: Reconciliation rate and duration by resource type
- **Source Updates**: Git repository sync status
- **Error Tracking**: Failed reconciliations and suspended resources

### 2. Prometheus Alerts

**Alert Rules**: `flux-alerts`  
**Location**: `kubernetes/apps/monitoring/kube-prometheus-stack/app/prometheusrules/flux-alerts.yaml`

Configured alerts:
- **FluxReconciliationFailure**: Resources failing to reconcile for >10 minutes
- **FluxReconciliationStalled**: Resources in stalled state for >10 minutes
- **FluxSuspendedResource**: Resources suspended for >24 hours
- **FluxHighReconciliationTime**: P95 reconciliation time >60 seconds
- **FluxSourceNotFound**: Missing source references
- **FluxHelmReleaseNotReady**: HelmRelease failures >15 minutes
- **FluxKustomizationNotReady**: Kustomization failures >15 minutes
- **FluxGitRepositoryNotReady**: GitRepository sync failures >15 minutes
- **FluxSystemDown**: Flux controllers not running

## Accessing the Dashboard

### Via Tailscale
1. Navigate to: `https://grafana.walleye-monster.ts.net`
2. Login with credentials:
   - Username: `admin`
   - Password: `prom-operator`
3. Go to Dashboards → Browse → Flux Cluster Stats

### Direct Access
```bash
# Port forward Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

# Access at http://localhost:3000
```

## Key Metrics

### Success Rate
```promql
sum(rate(gotk_reconcile_duration_seconds_count{success="true"}[5m])) / 
sum(rate(gotk_reconcile_duration_seconds_count[5m]))
```
Target: >99% success rate

### Reconciliation Duration
```promql
histogram_quantile(0.95, 
  sum by (kind, le) (
    rate(gotk_reconcile_duration_seconds_bucket[5m])
  )
)
```
Target: <30s for most resources

### Failed Resources
```promql
sum(gotk_reconcile_condition{type="Ready",status="False"})
```
Target: 0 failed resources

## Troubleshooting

### Common Issues

1. **High Reconciliation Time**
   - Check resource intervals in `ks.yaml`
   - Verify source repository accessibility
   - Check for large manifests or complex dependencies

2. **Reconciliation Failures**
   - Check controller logs: `kubectl logs -n flux-system deployment/kustomize-controller`
   - Verify RBAC permissions
   - Check for syntax errors in manifests

3. **Missing Metrics**
   - Ensure Flux was installed with `--export` flag
   - Verify ServiceMonitor is created
   - Check Prometheus targets

### Useful Commands

```bash
# Check Flux status
flux check

# Get all resources status
flux get all -A

# Check specific resource
flux get kustomization <name> -n <namespace>

# Force reconciliation
flux reconcile kustomization <name> -n <namespace> --with-source

# Check events
kubectl events -n flux-system --for deployment/kustomize-controller
```

## Performance Tuning

### Reconciliation Intervals
Based on resource criticality:
- Critical infrastructure: 5m
- Core services: 15m
- Standard applications: 30m-1h

### Resource Limits
Flux controllers have been configured with:
- CPU: 100m request, 500m limit
- Memory: 256Mi request, 512Mi limit

### Concurrency Settings
Default concurrency is usually sufficient, but can be tuned:
```yaml
# In flux-instance HelmRelease
spec:
  values:
    kustomize-controller:
      concurrent: 10  # Default is 4
```

## Maintenance

### Dashboard Updates
The dashboard is managed via GitOps:
1. Edit `flux-cluster-dashboard.json`
2. Commit and push changes
3. Flux will automatically update the ConfigMap

### Alert Tuning
To adjust alert thresholds:
1. Edit `flux-alerts.yaml`
2. Update threshold values or durations
3. Commit and push changes

## Integration with CI/CD

### Webhook Notifications
Flux can send notifications on reconciliation events:
```yaml
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Alert
metadata:
  name: flux-system
  namespace: flux-system
spec:
  providerRef:
    name: alertmanager
  eventSeverity: error
  eventSources:
    - kind: Kustomization
      name: '*'
```

### GitHub Commit Status
Flux can update GitHub commit status:
```yaml
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Provider
metadata:
  name: github-status
  namespace: flux-system
spec:
  type: githubdispatch
  address: https://github.com/YOUR_ORG/YOUR_REPO
  secretRef:
    name: github-token
```

## Best Practices

1. **Monitor Reconciliation Times**: Keep an eye on P95 durations
2. **Set Appropriate Intervals**: Don't over-reconcile, it wastes resources
3. **Use Health Checks**: Configure health checks in Kustomizations
4. **Implement Alerts**: Act on alerts promptly to prevent cascading failures
5. **Regular Reviews**: Review suspended resources monthly

## References

- [Flux Monitoring Guide](https://fluxcd.io/flux/monitoring/)
- [Prometheus Operator](https://prometheus-operator.dev/)
- [Grafana Dashboard Repository](https://grafana.com/grafana/dashboards/15268-flux2/)