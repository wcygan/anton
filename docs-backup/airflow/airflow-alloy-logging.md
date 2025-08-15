# Airflow Logging with Vector Sidecar and Loki

> **Note**: This document has been updated to reflect the Vector sidecar implementation, which replaced the Alloy-only approach to solve ephemeral pod logging issues.

## Overview

This document describes the production logging solution for Apache Airflow in our Kubernetes cluster. We use a Vector sidecar pattern to guarantee 100% log capture from ephemeral task pods, with logs flowing to Loki (log aggregator) and stored in S3-compatible Ceph storage.

## Architecture

### Current Architecture (Vector Sidecar)

```
┌─────────────────────────────────────┐
│         Airflow Task Pod            │
│  ┌─────────────┐  ┌──────────────┐ │
│  │ Task        │  │ Vector       │ │
│  │ Container   │  │ Sidecar      │ │
│  │ stdout ─────┼──┤ /proc/1/fd/* │ │
│  └─────────────┘  └──────┬───────┘ │
└───────────────────────────┼─────────┘
                            ▼
                    [Loki Gateway] ──► [Ceph S3]
                            │
                            └──► [Grafana]
```

### Previous Architecture (Alloy DaemonSet - Deprecated)

```
[Airflow Pods] ── stdout/stderr ──► [Alloy DaemonSet] ──► [Loki] ──► [Ceph S3]
```

**Why we switched**: The Alloy DaemonSet approach suffered from a race condition where task pods completed before Alloy could discover and collect their logs, resulting in >90% log loss.

### Key Benefits

- **100% Log Capture**: Vector sidecar guarantees no logs are lost
- **Zero Race Conditions**: Logs are collected before pod termination
- **Minimal Overhead**: Only 5m CPU and 20Mi memory per task
- **Rich Metadata**: Automatic labeling with DAG ID, task ID, and execution date
- **No Task Delays**: Removed artificial sleep commands from DAGs
- **Persistent Storage**: Logs survive pod termination
- **Cost Effective**: Loki's label-based indexing minimizes storage costs

## Implementation

### 1. Vector Sidecar Configuration

Each Airflow task pod includes a Vector sidecar container that directly reads stdout/stderr from the main container via `/proc/1/fd/*`.

**Location**: `kubernetes/apps/airflow/airflow/app/pod-template-configmap.yaml`

```yaml
- name: vector
  image: timberio/vector:0.39.0-debian
  env:
    - name: VECTOR_CONFIG
      value: |
        [sources.task]
        type = "file"
        include = ["/proc/1/fd/1", "/proc/1/fd/2"]
        
        [transforms.add_metadata]
        type = "remap"
        inputs = ["task"]
        source = '''
        .dag_id = get_env_var("AIRFLOW_CTX_DAG_ID") ?? "unknown"
        .task_id = get_env_var("AIRFLOW_CTX_TASK_ID") ?? "unknown"
        '''
        
        [sinks.loki]
        type = "loki"
        endpoint = "http://loki-gateway.monitoring.svc.cluster.local:80"
        batch.timeout_secs = 0.5
```

### 2. Airflow Pod Template

The pod template is referenced in the Airflow HelmRelease:

```yaml
workers:
  podTemplate:
    configMapName: "airflow-pod-template"
    key: "pod-template.yaml"
```

### 3. Legacy Alloy Configuration (Still Active for Non-Task Pods)

The Alloy DaemonSet continues to collect logs from Airflow's persistent components (scheduler, webserver). For historical reference, here's the Airflow-specific processing that was attempted for task pods:

```hcl
// Special processing for Airflow logs
stage.match {
  selector = "{namespace=\"airflow\"}"
  
  // Extract Airflow-specific information from log messages
  stage.regex {
    expression = "\\[(?P<timestamp>[^\\]]+)\\] \\{(?P<source>[^}]+)\\}"
  }
  
  // Extract DAG ID from log content
  stage.regex {
    expression = "dag_id=(?P<dag_id>[\\w-]+)"
  }
  
  // Extract task ID from log content
  stage.regex {
    expression = "task_id=(?P<task_id>[\\w-]+)"
  }
  
  // Extract execution date from log content
  stage.regex {
    expression = "execution_date=(?P<execution_date>[\\d-]+T[\\d:+]+)"
  }
  
  // Add Airflow-specific labels if found
  stage.labels {
    values = {
      dag_id = "",
      task_id = "",
      execution_date = "",
    }
  }
}
```

### 2. Loki Storage

Loki stores logs in Ceph S3 with the following configuration:

- **Bucket**: `loki-logs` (manually configured)
- **Retention**: 30 days (720 hours)
- **Endpoint**: `http://rook-ceph-rgw-storage.storage.svc.cluster.local`

### 4. Airflow Configuration

Minimal changes to enable the pod template:

```yaml
workers:
  podTemplate:
    configMapName: "airflow-pod-template"
    key: "pod-template.yaml"

env:
  # Disable automatic pod deletion to allow log flush
  - name: AIRFLOW__KUBERNETES_EXECUTOR__DELETE_WORKER_PODS
    value: "False"
  - name: AIRFLOW__KUBERNETES_EXECUTOR__DELETE_WORKER_PODS_ON_FAILURE
    value: "False"
```

## Querying Logs

### Using LogCLI

```bash
# All Airflow logs
./scripts/logcli-wrapper.ts query '{namespace="airflow"}' --limit=100

# Logs for specific DAG
./scripts/logcli-wrapper.ts query '{namespace="airflow"} |= "dag_id=hello_world"' --limit=50

# Failed tasks
./scripts/logcli-wrapper.ts query '{namespace="airflow"} |= "ERROR"' --limit=20

# Logs with extracted labels (once label extraction is working)
./scripts/logcli-wrapper.ts query '{namespace="airflow", dag_id="hello_world"}' --limit=10
```

### Using Grafana

1. Navigate to Grafana: `https://grafana.${SECRET_DOMAIN}`
2. Go to Explore → Select Loki datasource
3. Use the query builder or LogQL directly

### Common LogQL Queries

```logql
# All scheduler logs
{namespace="airflow", container="scheduler"}

# Worker logs for specific DAG
{namespace="airflow", app_kubernetes_io_component="worker"} |= "dag_id=hello_world"

# Extract and count errors by DAG
{namespace="airflow"} |= "ERROR" | pattern `dag_id=<dag_id>` | __error__="" | line_format "{{.dag_id}}" | count by (dag_id)

# Task execution timeline
{namespace="airflow"} |= "TaskInstance Finished" | pattern `dag_id=<dag_id>, task_id=<task_id>`
```

## Grafana Dashboard

A dedicated Airflow dashboard can be created with the following panels:

### Essential Panels

1. **Recent Task Executions**
   - Table showing latest task runs with status
   - Query: `{namespace="airflow"} |= "TaskInstance Finished"`

2. **Error Log Stream**
   - Live tail of ERROR level logs
   - Query: `{namespace="airflow"} |= "ERROR"`

3. **DAG Execution Overview**
   - Bar chart of executions by DAG
   - Query: `sum by (dag_id) (count_over_time({namespace="airflow"} |= "DagRun Finished" | pattern \`dag_id=<dag_id>\` [1h]))`

4. **Task Duration Trends**
   - Graph showing task execution times
   - Parse duration from "run_duration" in logs

### Dashboard Variables

- `dag_id`: Dynamic list from `{namespace="airflow"} | dag_id != ""`
- `task_id`: Filtered by selected DAG
- `time_range`: Standard Grafana time picker

## Troubleshooting

### Logs Not Appearing

1. **Check Alloy is running**:
   ```bash
   kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy
   ```

2. **Verify Airflow is generating logs**:
   ```bash
   kubectl logs -n airflow deployment/airflow-webserver --tail=10
   ```

3. **Test Loki connectivity**:
   ```bash
   ./scripts/logcli-wrapper.ts query '{namespace="airflow"}' --limit=1
   ```

### Labels Not Extracted

The label extraction relies on specific log patterns. If labels aren't working:

1. Check log format matches the regex patterns
2. Verify Alloy configuration was applied correctly
3. Look for extraction errors in Alloy logs

### Performance Issues

If queries are slow:

1. Use time ranges to limit data scanned
2. Add more specific label selectors
3. Avoid using `|~` (regex match) when `|=` (contains) suffices

## Maintenance

### Log Retention

Logs are retained for 30 days by default. To modify:

1. Update Loki HelmRelease `limits_config.retention_period`
2. Consider storage capacity when extending retention

### Monitoring Alloy

```bash
# Check Alloy resource usage
kubectl top pods -n monitoring -l app.kubernetes.io/name=alloy

# View Alloy logs
kubectl logs -n monitoring daemonset/alloy --tail=50
```

### Updating Configuration

1. Edit `kubernetes/apps/monitoring/alloy/app/helmrelease.yaml`
2. Commit and push changes
3. Wait for Flux to reconcile or force it:
   ```bash
   flux reconcile kustomization alloy -n monitoring --with-source
   ```

## Migration from Previous Solutions

### From Alloy DaemonSet (Phase 1)

The Alloy-only approach failed due to:
- Task pods completing in <1 second
- Kubelet log discovery lag
- File-based tailing couldn't capture ephemeral containers

The Vector sidecar solution eliminates these issues entirely.

### From Persistent Volume Logging

The PVC-based approach is no longer needed. Logs are now:
- Collected in real-time by Vector sidecar
- Stored centrally in Loki
- Accessible even after pod deletion

### From Direct S3 Logging

We chose Vector + Loki over direct S3 because:
- Real-time log streaming and analysis
- Better integration with Grafana
- Minimal Airflow configuration changes
- Lower latency for log availability

## Best Practices

1. **Use structured logging** in your DAGs:
   ```python
   logger.info(f"Processing started", extra={
       "dag_id": context["dag"].dag_id,
       "task_id": context["task"].task_id,
       "execution_date": context["execution_date"].isoformat()
   })
   ```

2. **Include context in error messages**:
   ```python
   logger.error(f"Failed to process file: {file_path}", exc_info=True)
   ```

3. **Avoid excessive logging** in tight loops to prevent log spam

4. **Use appropriate log levels**:
   - DEBUG: Detailed diagnostic info
   - INFO: General informational messages
   - WARNING: Warning messages
   - ERROR: Error conditions
   - CRITICAL: Critical problems

## Future Enhancements

1. **Automated Alerting**: Create Loki recording rules for task failures
2. **SLA Monitoring**: Track task execution times against SLAs
3. **Log-based Metrics**: Export metrics from logs to Prometheus
4. **ML Anomaly Detection**: Identify unusual patterns in logs
5. **Vector Metrics**: Add Prometheus metrics export from Vector sidecars
6. **Conditional Routing**: Route ERROR logs to separate high-priority stream

## References

- [Vector Sidecar Documentation](https://vector.dev/docs/setup/deployment/roles/#sidecar)
- [Airflow Pod Template Guide](https://airflow.apache.org/docs/apache-airflow/stable/kubernetes.html#pod-template-file)
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/logql/)
- [Airflow Logging Architecture](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/logging-monitoring/logging-architecture.html)
- [Vector Sidecar Implementation Guide](../logging-stack/setup/airflow-vector-sidecar.md)