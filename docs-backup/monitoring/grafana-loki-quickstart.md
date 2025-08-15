# Grafana with Loki Quick Start Guide

## Access Grafana

Your Grafana instance is accessible via Tailscale at:
- **URL**: https://grafana.walleye-monster.ts.net
- **Authentication**: Check your 1Password for credentials if required

## Verify Loki Data Source

1. Navigate to **Configuration → Data Sources** in Grafana
2. Look for the Loki data source (should be pre-configured)
3. Click on it and hit **Test** to verify connectivity

## Useful LogQL Queries

### Basic Queries

```logql
# Show all logs from a specific namespace
{namespace="kube-system"}

# Show logs from a specific pod
{namespace="flux-system", pod="source-controller-*"}

# Show error logs across all namespaces
{job="monitoring/alloy"} |= "error"

# Show logs with specific log level
{namespace="monitoring"} | json | level="error"

# Show logs from the last 5 minutes with errors
{namespace="kube-system"} |= "error" | rate(5m)
```

### Advanced Queries for Your Cluster

```logql
# Flux GitOps errors
{namespace="flux-system"} |~ "error|fail|warning" | json

# Ceph storage warnings
{namespace="storage", app_kubernetes_io_name="rook-ceph-operator"} |~ "warn|error|fail"

# Airflow DAG execution logs
{namespace="airflow", app_kubernetes_io_name="airflow"} | json | component="scheduler"

# Kubernetes API server audit logs
{namespace="kube-system", app_kubernetes_io_name="kube-apiserver"} | json

# Ingress controller access logs
{namespace="network", app_kubernetes_io_name="ingress-nginx"} | json | status >= 400

# External Secrets Operator sync failures
{namespace="external-secrets"} |~ "SecretSyncError|failed to sync"

# Node problem detector issues
{namespace="system-health", app_kubernetes_io_name="node-problem-detector"} |~ "NodeCondition"
```

### Performance and Rate Queries

```logql
# Log volume by namespace (last hour)
sum by (namespace) (rate({job="monitoring/alloy"}[1h]))

# Error rate by pod
sum by (pod) (rate({namespace="flux-system"} |= "error" [5m]))

# Top 10 pods by log volume
topk(10, sum by (pod) (rate({job="monitoring/alloy"}[5m])))
```

## Creating a Dashboard

Here's a dashboard configuration for monitoring your critical apps. You can import this JSON in Grafana:

1. Go to **Dashboards → Import**
2. Upload or paste the contents of `/docs/monitoring/loki-dashboard.json`
3. Select your Loki data source when prompted

The dashboard includes:
- Log volume by namespace (time series)
- Flux errors by pod (table)
- Critical system errors (log panel)
- Ingress HTTP errors by status code
- Ceph storage warnings

## Setting Up Alert Rules

To set up alerting for critical errors:

1. Navigate to **Alerting → Alert rules**
2. Click **Import alert rules**
3. Upload the file at `/docs/monitoring/loki-alert-rules.yaml`
4. Update the `${loki_datasource_uid}` placeholder with your actual Loki datasource UID

The alert rules monitor:
- **Flux GitOps Errors**: Triggers when Flux experiences consistent errors
- **Ceph Storage Health**: Alerts on storage degradation or OSD failures
- **External Secrets Sync**: Warns about secret synchronization failures
- **Ingress Error Rate**: Monitors for high rates of 5xx errors
- **Node Conditions**: Critical node problems detected by node-problem-detector

### Configure Contact Points

To receive alerts, configure contact points in Grafana:

1. Go to **Alerting → Contact points**
2. Click **Add contact point**
3. Configure your preferred notification channel:
   - **Slack**: For team notifications
   - **Email**: For backup notifications
   - **PagerDuty**: For critical on-call alerts

## Quick Test Query

To verify Loki is working, run this simple query in the Explore view:

```logql
{job="monitoring/alloy"} | json | line_format "{{.namespace}} {{.pod}} {{.message}}" | limit 10
```

This should return recent logs collected by Alloy from across your cluster.

## Troubleshooting

### No Data in Loki
1. Check Alloy pods are running: `kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy`
2. Verify Loki is healthy: `kubectl get pods -n monitoring -l app.kubernetes.io/name=loki`
3. Check Alloy logs: `kubectl logs -n monitoring -l app.kubernetes.io/name=alloy --tail=50`

### Queries Timing Out
1. Reduce the time range of your query
2. Add more specific label filters
3. Use `limit` to restrict results

### Missing Logs from Specific Apps
1. Ensure the app is producing logs to stdout/stderr
2. Check if the namespace is excluded in Alloy configuration
3. Verify pod labels match Alloy's discovery configuration