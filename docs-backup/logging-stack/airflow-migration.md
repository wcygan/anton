# Airflow to Centralized Logging Migration

This document describes the migration of Apache Airflow from file-based logging with a 100Gi PVC to centralized logging using Loki + Alloy.

## Migration Overview

### Before Migration
- Airflow configured with 100Gi PVC for triggerer logs
- Task logs stored in pod filesystems
- Difficult to search across DAG executions
- Storage inefficient (100Gi allocated, <1% used)

### After Migration
- All logs sent to stdout/stderr
- Collected by Alloy DaemonSet
- Stored in Loki with S3 backend
- Searchable via Grafana with LogQL
- 100Gi PVC removed

## Changes Made

### 1. HelmRelease Configuration

Updated `kubernetes/apps/airflow/airflow/app/helmrelease.yaml`:

- Removed `triggerer.persistence` section (100Gi PVC)
- Enhanced logging configuration for stdout
- Added PYTHONUNBUFFERED=1 to all components
- Configured log formatting for better parsing

### 2. Vector Sidecar

The existing Vector sidecar configuration for KubernetesExecutor worker pods:
- Collects logs from `/proc/1/fd/1` and `/proc/1/fd/2` (stdout/stderr)
- Adds Airflow metadata (dag_id, task_id, run_id, execution_date)
- Ships to Loki at `http://loki-gateway.monitoring.svc.cluster.local:80`

### 3. Grafana Dashboard

Created Airflow-specific dashboard with:
- DAG execution log volume
- Task error tracking
- Component log monitoring
- Live error stream
- Top tasks by log volume

## LogQL Queries for Airflow

### View All Airflow Logs
```logql
{namespace="airflow"}
```

### Logs for Specific DAG
```logql
{namespace="airflow", dag_id="my_dag_name"}
```

### Logs for Specific Task
```logql
{namespace="airflow", dag_id="my_dag", task_id="my_task"}
```

### All Task Errors
```logql
{namespace="airflow", dag_id=~".+"} |~ "(?i)(error|exception|failed|critical)"
```

### Scheduler Activity
```logql
{namespace="airflow", pod=~"airflow-scheduler.*"} |~ "(?i)(dag|task|queue|executor)"
```

### Webserver Logs
```logql
{namespace="airflow", pod=~"airflow-webserver.*"}
```

### Task Execution by Run ID
```logql
{namespace="airflow", run_id="scheduled__2024-01-15T12:00:00+00:00"}
```

### Failed Tasks in Last Hour
```logql
{namespace="airflow"} |~ "Task failed" | json | dag_id != "" | line_format "{{.dag_id}}/{{.task_id}}: {{.msg}}"
```

### Worker Pod Logs
```logql
{namespace="airflow", component="worker"}
```

### DAG Processing Errors
```logql
{namespace="airflow", pod=~"airflow-scheduler.*"} |~ "ERROR.*processor"
```

## Accessing Logs in Grafana

1. Navigate to Grafana: http://localhost:3000 (or your Grafana URL)
2. Go to Explore → Select Loki datasource
3. Use the queries above or explore with label filters
4. For structured view, use the "Airflow Logs" dashboard

## Troubleshooting

### Logs Not Appearing

1. Check Alloy is running on all nodes:
   ```bash
   kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy
   ```

2. Verify Vector sidecar in worker pods:
   ```bash
   kubectl get pod <worker-pod> -n airflow -o jsonpath='{.spec.containers[*].name}'
   ```

3. Check Vector logs:
   ```bash
   kubectl logs <worker-pod> -n airflow -c vector
   ```

### Missing DAG/Task Labels

Ensure worker pods have the correct environment variables:
```bash
kubectl describe pod <worker-pod> -n airflow | grep -E "AIRFLOW_CTX_"
```

### Query Performance

For better performance:
- Use specific time ranges
- Include dag_id or task_id labels
- Limit query scope with namespace selector

## Benefits of Migration

1. **Cost Efficiency**: Removed 100Gi unused PVC
2. **Searchability**: Full-text search across all logs
3. **Correlation**: Link logs with metrics and traces
4. **Retention**: Automatic 7-day retention policy
5. **Real-time**: Live log streaming in Grafana
6. **No Data Loss**: Vector ensures reliable delivery

## Rollback Plan

If needed to rollback:

1. Re-enable triggerer persistence in HelmRelease
2. Remove logging configuration changes
3. Apply HelmRelease changes
4. Logs will resume writing to PVC

Note: Logs written to Loki during migration will remain accessible for 7 days.

## Future Enhancements

1. **Structured Logging**: Parse Airflow's JSON logs for better filtering
2. **Alerting**: Create alerts for task failures and DAG issues
3. **Metrics Correlation**: Link log spikes with performance metrics
4. **Long-term Storage**: Consider extended retention for audit logs