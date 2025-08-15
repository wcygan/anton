# Airflow Health Monitoring Implementation Guide

## Overview

This guide documents the implementation of automated Kubernetes cluster health monitoring using Apache Airflow.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Airflow         │────▶│ Health Check │────▶│ Alert Manager   │
│ Scheduler       │     │ Scripts      │     │ (Prometheus)    │
└─────────────────┘     └──────────────┘     └─────────────────┘
         │                      │                      │
         ▼                      ▼                      ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ DAG: cluster_   │     │ ConfigMap:   │     │ Grafana         │
│ health_monitor  │     │ Results      │     │ Dashboard       │
└─────────────────┘     └──────────────┘     └─────────────────┘
```

## Implementation Steps

### Step 1: Deploy Script Access

The health check scripts need to be accessible to Airflow pods. Choose one approach:

#### Option A: Git-Sync Sidecar (Recommended)
```yaml
# Add to Airflow HelmRelease values
gitSync:
  enabled: true
  repo: https://github.com/wcygan/homelab.git
  branch: main
  subPath: scripts
  wait: 60
```

#### Option B: Build Custom Image
```dockerfile
FROM denoland/deno:alpine-1.47.0
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.ts
```

#### Option C: ConfigMap Mount (Current)
- Using placeholder ConfigMap for initial testing
- Replace with actual script content or volume mount

### Step 2: Configure Airflow

1. **Apply the health monitoring DAG**:
   ```bash
   # The DAG is automatically loaded from the dags/ directory
   kubectl -n airflow get pods -l component=scheduler -o name | \
     xargs -I {} kubectl -n airflow exec {} -- airflow dags list | grep cluster_health
   ```

2. **Create required resources**:
   ```bash
   # Apply ConfigMaps and RBAC
   kubectl apply -f kubernetes/apps/airflow/airflow/app/health-scripts-configmap.yaml
   kubectl apply -f kubernetes/apps/airflow/airflow/app/airflow-alerting-config.yaml
   ```

3. **Grant Airflow RBAC permissions**:
   ```yaml
   # kubernetes/apps/airflow/airflow/app/rbac.yaml
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRole
   metadata:
     name: airflow-health-checker
   rules:
   - apiGroups: [""]
     resources: ["nodes", "pods", "services", "configmaps", "persistentvolumeclaims"]
     verbs: ["get", "list", "create", "update", "patch"]
   - apiGroups: ["apps"]
     resources: ["deployments", "statefulsets", "daemonsets"]
     verbs: ["get", "list"]
   - apiGroups: ["kustomize.toolkit.fluxcd.io"]
     resources: ["kustomizations"]
     verbs: ["get", "list"]
   - apiGroups: ["helm.toolkit.fluxcd.io"]
     resources: ["helmreleases"]
     verbs: ["get", "list"]
   ```

### Step 3: Configure Alerting

1. **Prometheus AlertManager Integration**:
   - The DAG sends alerts to AlertManager on critical failures
   - Configure AlertManager routes for health check alerts

2. **Email Alerts** (Optional):
   ```yaml
   # Add to Airflow HelmRelease
   config:
     smtp:
       smtp_host: smtp.gmail.com
       smtp_port: 587
       smtp_user: your-email@gmail.com
       smtp_password: app-specific-password
       smtp_mail_from: airflow@homelab.local
   ```

3. **Slack Integration** (Optional):
   - Create Slack webhook
   - Update `airflow-alerting-config` ConfigMap with webhook URL

### Step 4: Validate Deployment

1. **Trigger DAG manually**:
   ```bash
   kubectl -n airflow exec deploy/airflow-webserver -- \
     airflow dags trigger cluster_health_monitoring
   ```

2. **Check execution**:
   ```bash
   # View DAG runs
   kubectl -n airflow exec deploy/airflow-webserver -- \
     airflow dags list-runs -d cluster_health_monitoring
   
   # Check task logs
   kubectl -n airflow logs -l dag_id=cluster_health_monitoring
   ```

3. **Verify ConfigMap storage**:
   ```bash
   kubectl get configmap -l type=health-check
   kubectl describe configmap health-check-$(date +%Y-%m-%d)
   ```

## Monitoring the Monitor

### Key Metrics to Track

1. **DAG Success Rate**:
   - Target: >95% successful runs
   - Alert if: 2 consecutive failures

2. **Execution Time**:
   - Target: <5 minutes for all checks
   - Alert if: >10 minutes

3. **Resource Usage**:
   - Monitor pod CPU/memory during execution
   - Adjust resource limits if needed

### Grafana Dashboard

Create a dashboard showing:
- Health check history (from ConfigMaps)
- Failure trends by check type
- Execution duration trends
- Alert frequency

## Troubleshooting

### Common Issues

1. **Script Not Found**:
   - Check ConfigMap is mounted correctly
   - Verify script paths in DAG match ConfigMap keys

2. **Permission Denied**:
   - Ensure RBAC is configured
   - Check serviceAccount has required permissions

3. **Timeout Errors**:
   - Increase task timeout in DAG
   - Check script performance

4. **No Alerts Received**:
   - Verify AlertManager endpoint
   - Check network policies
   - Test webhook manually

## Next Steps

1. [ ] Production script deployment (git-sync or custom image)
2. [ ] Grafana dashboard creation
3. [ ] Alert routing configuration
4. [ ] SLA monitoring setup
5. [ ] Historical trend analysis

## References

- [Airflow KubernetesPodOperator](https://airflow.apache.org/docs/apache-airflow-providers-cncf-kubernetes/stable/operators.html)
- [Health Check Scripts](../../scripts/)
- [Prometheus AlertManager](https://prometheus.io/docs/alerting/latest/alertmanager/)