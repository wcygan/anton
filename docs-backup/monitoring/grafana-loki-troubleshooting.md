# Grafana Loki Troubleshooting Guide

## Dashboard Import Issues

Based on your screenshot, the dashboard is having issues connecting to Loki. Here's how to fix it:

### 1. Verify Loki Data Source

First, check if the Loki data source is properly configured:

```bash
# Check if Loki is accessible from within the cluster
kubectl exec -n monitoring deploy/kube-prometheus-stack-grafana -- wget -qO- http://loki-gateway.monitoring.svc.cluster.local:3100/ready
```

### 2. Manual Data Source Configuration

If the Loki data source isn't working, manually configure it:

1. Go to **Configuration → Data Sources** in Grafana
2. Click **Add data source**
3. Select **Loki**
4. Configure as follows:
   - **Name**: `Loki`
   - **URL**: `http://loki-gateway.monitoring.svc.cluster.local:3100`
   - **Access**: Server (default)
   - Leave other settings as default
5. Click **Save & test**

### 3. Import the Fixed Dashboard

I've created two fixed dashboard versions for you:

1. **Full Dashboard** (`loki-dashboard-fixed.json`):
   - Complete monitoring dashboard with all panels
   - Fixed datasource configuration
   - Simplified queries that should work immediately

2. **Test Dashboard** (`loki-test-dashboard.json`):
   - Simple test dashboard to verify Loki is working
   - Shows all logs, active namespaces, and log volume
   - Use this first to confirm connectivity

### 4. Import Steps

1. In Grafana, go to **Dashboards → Import**
2. Click **Upload JSON file**
3. Select `/docs/monitoring/loki-test-dashboard.json` first
4. Click **Import**
5. If the test dashboard works, import the full dashboard

### 5. Common Issues and Fixes

#### Issue: "Unable to get credentials"
This error suggests the datasource variable isn't resolving. The fixed dashboards use direct datasource references instead of variables.

#### Issue: "No data" in panels
Try these test queries in Grafana Explore:
```logql
# Simplest query - should return data
{job="monitoring/alloy"}

# Count logs by namespace
sum by (namespace) (count_over_time({job="monitoring/alloy"} [1m]))
```

#### Issue: Loki datasource not found
The datasource might be named differently. Check existing datasources:
```bash
kubectl exec -n monitoring deploy/kube-prometheus-stack-grafana -- \
  wget -qO- http://admin:prom-operator@localhost:3000/api/datasources | \
  jq -r '.[].name'
```

### 6. Alternative: Direct Query Test

Test Loki directly from the command line:
```bash
# Port-forward Loki
kubectl port-forward -n monitoring svc/loki-gateway 3100:3100 &

# Query Loki directly
curl -s "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="monitoring/alloy"} |= ""' \
  --data-urlencode 'limit=5' | jq '.data.result[0].values'
```

### 7. Quick Verification Commands

Run these to verify your logging stack:
```bash
# Check Alloy is collecting logs
kubectl logs -n monitoring daemonset/alloy --tail=10

# Check Loki is receiving logs
kubectl logs -n monitoring loki-0 -c loki --tail=10 | grep -i "push"

# Check for any errors
kubectl logs -n monitoring deployment/kube-prometheus-stack-grafana --tail=20
```

## Next Steps

1. Start with the test dashboard to verify basic connectivity
2. Once working, import the full monitoring dashboard
3. Customize queries based on your specific needs
4. Set up alerts using the provided alert rules

The key fix in the new dashboards is removing the datasource variable and using direct references to the "Loki" datasource, which should resolve the authentication errors you're seeing.