# Airflow Persistent Logging Setup

> **⚠️ DEPRECATED**: This approach is no longer used. We now use Alloy + Loki for centralized logging.  
> See [Airflow Alloy Logging](./airflow-alloy-logging.md) for the current implementation.

---

# Legacy Documentation: Airflow Persistent Logging Setup

## Problem

The original Airflow deployment was experiencing log persistence issues where
logs were lost when pods were terminated or restarted. This resulted in errors
like:

```
Could not read served logs: HTTPConnectionPool(host='hello-world-say-hello-0t7l11l5', port=8793):
Max retries exceeded with url: /log/dag_id=hello_world/run_id=manual__2025-06-03T03:47:28.608910+00:00/task_id=say_hello/attempt=1.log
(Caused by NameResolutionError: Failed to resolve 'hello-world-say-hello-0t7l11l5')
```

This happens because Airflow was trying to fetch logs from pods that no longer
exist.

## Solution

We implemented persistent logging using a Persistent Volume Claim (PVC) that
stores all Airflow logs on persistent storage, ensuring logs remain available
even after pod termination.

### Key Changes Made

#### 1. HelmRelease Configuration Updates

**File**: `kubernetes/apps/airflow/airflow/app/helmrelease.yaml`

Added the following configurations:

```yaml
# Persistent logging configuration
logs:
  persistence:
    enabled: true
    size: 10Gi
    storageClassName: local-path # Uses cluster's default storage class
    accessMode: ReadWriteOnce

# Configure Airflow to use local file logging
config:
  logging:
    remote_logging: "False" # Disable remote logging
    logging_level: "INFO"
    fab_logging_level: "WARN"
    log_retention_days: "30"
  core:
    base_log_folder: "/opt/airflow/logs" # Persistent volume mount point
    enable_xcom_pickling: "False"
  webserver:
    log_fetch_timeout_sec: "5"
    log_auto_tailing_offset: "30"
    log_animation_speed: "1000"

# Mount persistent volume to all components
webserver:
  extraVolumes:
    - name: airflow-logs
      persistentVolumeClaim:
        claimName: airflow-logs
  extraVolumeMounts:
    - name: airflow-logs
      mountPath: /opt/airflow/logs

scheduler:
  extraVolumes:
    - name: airflow-logs
      persistentVolumeClaim:
        claimName: airflow-logs
  extraVolumeMounts:
    - name: airflow-logs
      mountPath: /opt/airflow/logs

workers:
  extraVolumes:
    - name: airflow-logs
      persistentVolumeClaim:
        claimName: airflow-logs
  extraVolumeMounts:
    - name: airflow-logs
      mountPath: /opt/airflow/logs
```

#### 2. Enhanced Test DAG

**File**: `kubernetes/apps/airflow/airflow/dags/hello_world_dag.py`

Enhanced the test DAG to include comprehensive logging for testing:

- Added Python task with multiple log levels (INFO, WARNING, ERROR)
- Added multi-line bash output
- Added timestamp logging
- Added task dependencies for testing workflow

#### 3. Test Script

**File**: `scripts/test-airflow-logging.ts`

Created a comprehensive test script with the following capabilities:

- `--deploy`: Deploy updated Airflow configuration
- `--test`: Trigger test DAG and monitor execution
- `--logs`: Check log persistence and PVC status
- `--cleanup`: Clean up test resources

## How It Works

### Before (Problem)

1. Airflow tasks run in ephemeral pods
2. Logs are stored locally in pod filesystem
3. When pod terminates, logs are lost
4. Airflow UI tries to fetch logs from non-existent pod hostnames
5. Users see "Could not read served logs" errors

### After (Solution)

1. Airflow tasks run in pods with persistent volume mounted
2. All logs are written to `/opt/airflow/logs` (persistent storage)
3. When pods terminate, logs remain on persistent volume
4. New pods can access historical logs from persistent storage
5. Airflow UI successfully serves logs from local files

## Deployment Instructions

### 1. Deploy the Configuration

```bash
# From the anton directory
./scripts/test-airflow-logging.ts --deploy
```

Or manually:

```bash
flux reconcile kustomization airflow -n airflow --with-source
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=airflow -n airflow --timeout=300s
```

### 2. Verify Persistent Volume

```bash
kubectl get pvc -n airflow
kubectl get pv
```

You should see an `airflow-logs` PVC bound to a persistent volume.

### 3. Test Logging

```bash
# Trigger test DAG and check logs
./scripts/test-airflow-logging.ts --test

# Check log persistence
./scripts/test-airflow-logging.ts --logs
```

### 4. Verify in Airflow UI

1. Access Airflow UI via your ingress
2. Navigate to the `hello_world` DAG
3. Trigger a manual run
4. Click on task instances to view logs
5. Logs should now display properly without connection errors

## Verification Steps

### 1. Check PVC Status

```bash
kubectl get pvc -n airflow
# Should show airflow-logs as Bound
```

### 2. Check Log Directory

```bash
kubectl exec -n airflow deployment/airflow-webserver -- ls -la /opt/airflow/logs/
# Should show log directories organized by DAG
```

### 3. Check Airflow Configuration

```bash
kubectl exec -n airflow deployment/airflow-webserver -- airflow config get-value logging remote_logging
# Should return: False

kubectl exec -n airflow deployment/airflow-webserver -- airflow config get-value core base_log_folder
# Should return: /opt/airflow/logs
```

### 4. Test Log Persistence

1. Trigger a DAG run
2. Wait for completion
3. Delete the worker pod: `kubectl delete pod -n airflow -l component=worker`
4. Check logs in UI - they should still be accessible

## Storage Considerations

### Storage Class

- Currently configured to use `local-path` storage class
- Suitable for single-node or local development clusters
- For production, consider using your cluster's preferred storage class

### Storage Size

- Configured for 10Gi by default
- Adjust based on your log retention needs and DAG frequency
- Monitor usage:
  `kubectl exec -n airflow deployment/airflow-webserver -- df -h /opt/airflow/logs`

### Log Retention

- Configured for 30-day retention
- Airflow will automatically clean up old logs
- Adjust `log_retention_days` in configuration as needed

## Alternative Solutions

### Option 1: Remote Logging (S3/GCS)

For production environments, consider remote logging to cloud storage:

```yaml
config:
  logging:
    remote_logging: "True"
    remote_base_log_folder: "s3://your-bucket/airflow-logs"
    remote_log_conn_id: "aws_default"
```

### Option 2: Shared NFS Storage

For multi-node clusters, consider NFS-based storage:

```yaml
logs:
  persistence:
    enabled: true
    storageClassName: "nfs-client" # Your NFS storage class
    accessMode: ReadWriteMany
```

## Troubleshooting

### Logs Still Not Persisting

1. Check PVC is bound: `kubectl get pvc -n airflow`
2. Check volume mounts: `kubectl describe pod -n airflow -l component=webserver`
3. Check Airflow config:
   `kubectl exec -n airflow deployment/airflow-webserver -- airflow config list`

### Storage Issues

1. Check available storage: `kubectl get pv`
2. Check storage class: `kubectl get storageclass`
3. Check local-path-provisioner: `kubectl get pods -n storage`

### Permission Issues

1. Check pod security context
2. Verify volume permissions:
   `kubectl exec -n airflow deployment/airflow-webserver -- ls -la /opt/airflow/`

## Monitoring

### Log Volume Usage

```bash
kubectl exec -n airflow deployment/airflow-webserver -- du -sh /opt/airflow/logs/
```

### Recent Log Files

```bash
kubectl exec -n airflow deployment/airflow-webserver -- find /opt/airflow/logs/ -name "*.log" -mtime -1
```

### Airflow Metrics

Monitor Airflow metrics via Prometheus (enabled in configuration):

- Task success/failure rates
- DAG run durations
- Log file sizes

This persistent logging setup ensures reliable log access and improves the
overall Airflow user experience by eliminating the "Could not read served logs"
errors.
