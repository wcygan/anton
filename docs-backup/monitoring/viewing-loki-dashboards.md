# How to View Your New Loki Dashboards in Grafana

## 1. Access Grafana

Open your browser and go to:
```
https://grafana.walleye-monster.ts.net
```

## 2. Navigate to Dashboards

Once logged in:
1. Click **Dashboards** in the left sidebar (four squares icon)
2. You'll see a list of all dashboards

## 3. Find Your New Dashboards

Your new dashboards are organized in folders:

### **Homelab** Folder
- **Homelab Logging Overview** - Simple overview of log volume by namespace

### **Logging** Folder  
- **Homelab Critical Apps Monitoring** - Comprehensive dashboard with:
  - Log Volume by Namespace
  - Flux Errors by Pod
  - Critical System Errors (live stream)
  - Ingress Activity
  - Ceph Storage Warnings
  - Top 10 Pods by Log Volume

## 4. Using the Dashboards

### Quick Navigation
1. Click on any dashboard name to open it
2. Time range selector (top right) - adjust to see different time periods
3. Refresh button - manually refresh data
4. Auto-refresh dropdown - set to 10s for live monitoring

### Dashboard Features
- **Click and drag** on graphs to zoom in on specific time periods
- **Hover** over graph lines to see exact values
- **Click legend items** to show/hide specific metrics
- **Expand panels** using the title dropdown → View

## 5. Exploring Logs

In the "Critical System Errors" panel:
- Click on any log line to see full details
- Use the search box to filter logs
- Click "Show context" to see surrounding log entries

## 6. Creating Custom Queries

To explore logs further:
1. Click **Explore** in the left sidebar
2. Select **Loki** as the data source
3. Try queries like:
   ```logql
   # All logs from Airflow
   {namespace="airflow"}
   
   # Errors in the last hour
   {namespace=~"flux-system|storage"} |= "error"
   
   # Specific pod logs
   {pod="loki-0"}
   ```

## 7. Dashboard Organization

The dashboards are automatically synced via GitOps:
- Located in: `kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/`
- Any changes to JSON files are automatically applied
- Version controlled and backed up in Git

## 8. Customizing Dashboards

To modify a dashboard:
1. Open the dashboard in Grafana
2. Click the settings gear icon (top right)
3. Make your changes
4. Click "Save dashboard"
5. Copy the JSON model
6. Update the file in Git and push

## Quick Checks

Run these commands to verify everything is working:

```bash
# Check dashboard ConfigMaps
kubectl get cm -n monitoring | grep grafana-dashboard

# See dashboard labels (these trigger auto-import)
kubectl describe cm grafana-dashboard-loki -n monitoring | grep -A3 Labels

# Check Grafana sidecar logs (it imports dashboards)
kubectl logs -n monitoring deployment/kube-prometheus-stack-grafana -c grafana-sc-dashboard --tail=20
```

## Troubleshooting

If dashboards don't appear:
1. Wait 1-2 minutes for the sidecar to pick them up
2. Try refreshing the browser (Ctrl+F5)
3. Check folder filters in dashboard list
4. Restart Grafana pod if needed:
   ```bash
   kubectl rollout restart deployment/kube-prometheus-stack-grafana -n monitoring
   ```

Your dashboards are now live and automatically updating with your cluster's log data!