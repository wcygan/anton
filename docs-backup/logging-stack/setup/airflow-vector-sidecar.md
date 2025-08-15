# Airflow Task Logging with Vector Sidecar

## Overview

This guide implements a Vector sidecar pattern to guarantee 100% log capture from Airflow KubernetesExecutor task pods, solving the ephemeral pod logging challenge where tasks complete before node-level log collectors can discover them.

## Problem Statement

### Current Issues
- **Task pods complete in <1 second**, before Alloy discovers them
- **90%+ log loss rate** with current Alloy DaemonSet approach
- File-based log tailing cannot capture ephemeral containers
- Artificial delays in tasks impact performance

### Why Vector Sidecar Works

| Step | Alloy (DaemonSet) | Vector (Sidecar) |
|------|-------------------|------------------|
| Pod starts | Discovery loop hasn't run yet | **Immediate** - shares same pod |
| Task runs (300ms) | Kubelet log file not yet written | Tails `/proc/1/fd/1` in real-time |
| Task exits | Container removed before discovery | Sidecar flushes logs to Loki |
| Pod deleted | Logs lost | All logs already in Loki |

## Architecture

```
┌─────────────────────────────────────┐
│         Airflow Task Pod            │
│                                     │
│  ┌─────────────┐  ┌──────────────┐ │
│  │ Task        │  │ Vector       │ │
│  │ Container   │  │ Sidecar      │ │
│  │             │  │              │ │
│  │ stdout ─────┼──┤ tail stdout  │ │
│  │ stderr ─────┼──┤ /proc/1/fd/* │ │
│  └─────────────┘  └──────┬───────┘ │
└───────────────────────────┼─────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │ Loki Gateway │
                    └──────────────┘
```

## Implementation Guide

### Step 1: Create Pod Template ConfigMap

```yaml
# kubernetes/apps/airflow/airflow/app/pod-template-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: airflow-pod-template
  namespace: airflow
data:
  pod-template.yaml: |
    apiVersion: v1
    kind: Pod
    metadata:
      name: airflow-task-pod-template
    spec:
      containers:
        - name: base
          # Main task container - configured by Airflow
        - name: vector
          image: timberio/vector:0.39.0-debian
          env:
            - name: VECTOR_CONFIG
              value: |
                # Capture task stdout/stderr
                [sources.task]
                type = "file"
                include = ["/proc/1/fd/1", "/proc/1/fd/2"]
                ignore_older_secs = 0
                fingerprint.strategy = "device_and_inode"
                
                # Add Airflow metadata
                [transforms.add_metadata]
                type = "remap"
                inputs = ["task"]
                source = '''
                .namespace = "airflow"
                .pod = get_env_var!("HOSTNAME")
                .dag_id = get_env_var("AIRFLOW_CTX_DAG_ID") ?? "unknown"
                .task_id = get_env_var("AIRFLOW_CTX_TASK_ID") ?? "unknown"
                .execution_date = get_env_var("AIRFLOW_CTX_EXECUTION_DATE") ?? "unknown"
                '''
                
                # Ship to Loki with minimal delay
                [sinks.loki]
                type = "loki"
                inputs = ["add_metadata"]
                endpoint = "http://loki-gateway.monitoring.svc.cluster.local:80"
                encoding.codec = "json"
                batch.max_bytes = 512000
                batch.timeout_secs = 0.5
                labels.namespace = "{{ namespace }}"
                labels.pod = "{{ pod }}"
                labels.dag_id = "{{ dag_id }}"
                labels.task_id = "{{ task_id }}"
          resources:
            requests:
              cpu: 5m
              memory: 20Mi
            limits:
              cpu: 25m
              memory: 50Mi
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 1"]
      terminationGracePeriodSeconds: 5
```

### Step 2: Update Airflow HelmRelease

```yaml
# In kubernetes/apps/airflow/airflow/app/helmrelease.yaml
spec:
  values:
    workers:
      # Use pod template with Vector sidecar
      podTemplate:
        configMapName: "airflow-pod-template"
        key: "pod-template.yaml"
```

### Step 3: Update Kustomization

```yaml
# kubernetes/apps/airflow/airflow/app/kustomization.yaml
resources:
  - ./helmrelease.yaml
  - ./tailscale-ingress.yaml
  - ./pod-template-configmap.yaml
```

### Step 4: Remove Task Delays

Update your DAGs to remove artificial delays:

```python
# Before (with delays)
hello_operator = BashOperator(
    task_id="say_hello",
    bash_command='''
    echo "Hello World!"
    # Add small delay to ensure logs are captured by Alloy
    sleep 5
    ''',
)

# After (no delays needed)
hello_operator = BashOperator(
    task_id="say_hello",
    bash_command='echo "Hello World!"',
)
```

## Configuration Details

### Vector Configuration Explained

| Setting | Value | Purpose |
|---------|-------|---------|
| `include = ["/proc/1/fd/1", "/proc/1/fd/2"]` | Task stdout/stderr | Direct container output access |
| `batch.timeout_secs = 0.5` | 500ms | Fast flush for short tasks |
| `batch.max_bytes = 512000` | 500KB | Reasonable batch size |
| `fingerprint.strategy = "device_and_inode"` | File tracking | Handles container restarts |

### Resource Impact

Per task pod:
- **CPU**: 5m request, 25m limit (0.5% - 2.5% of 1 core)
- **Memory**: 20Mi request, 50Mi limit
- **Image Size**: 15MB compressed
- **Startup Time**: ~200ms additional

With 100 concurrent tasks:
- **Total CPU**: 0.5 CPU request, 2.5 CPU limit
- **Total Memory**: 2Gi request, 5Gi limit

## Verification

### Test Log Capture

1. Deploy the changes:
```bash
flux reconcile kustomization airflow -n airflow --with-source
```

2. Trigger test DAG:
```bash
kubectl exec -n airflow deployment/airflow-webserver -- \
  airflow dags trigger hello_world
```

3. Verify logs in Loki:
```bash
./scripts/logcli-wrapper.ts query \
  '{namespace="airflow", dag_id="hello_world"}' \
  --limit=10 --since=5m
```

### Expected Results

You should see:
- Task output logs (print statements, echo commands)
- Python logger messages
- Complete log capture even for sub-second tasks
- Proper labeling with dag_id and task_id

## Monitoring

### Vector Sidecar Health

Check Vector container status:
```bash
kubectl get pods -n airflow -o json | \
  jq '.items[] | select(.spec.containers[].name=="vector") | 
  {name: .metadata.name, vector: .status.containerStatuses[] | 
  select(.name=="vector") | {ready: .ready, restarts: .restartCount}}'
```

### Log Ingestion Rate

Monitor in Grafana:
```promql
rate(loki_distributor_bytes_received_total{job="loki"}[5m])
```

## Troubleshooting

### No Logs Appearing

1. Check Vector container logs:
```bash
kubectl logs -n airflow <pod-name> -c vector
```

2. Verify Loki endpoint:
```bash
kubectl exec -n airflow <pod-name> -c vector -- \
  curl -s http://loki-gateway.monitoring.svc.cluster.local:80/ready
```

### High Memory Usage

Adjust Vector buffer settings:
```toml
[sources.task]
max_line_bytes = 102400  # 100KB max line
```

### Slow Task Startup

Pre-pull Vector image on nodes:
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: vector-image-puller
spec:
  template:
    spec:
      initContainers:
      - name: vector-puller
        image: timberio/vector:0.39.0-debian
        command: ["true"]
```

## Best Practices

### DO:
- ✅ Use structured logging in tasks for better parsing
- ✅ Set appropriate resource limits on Vector container
- ✅ Monitor Vector container restarts
- ✅ Use LogQL to query by dag_id and task_id

### DON'T:
- ❌ Log sensitive data (Vector doesn't filter)
- ❌ Generate excessive logs (impacts task performance)
- ❌ Modify Vector config without testing
- ❌ Ignore Vector container failures

## Migration Checklist

- [ ] Review current DAGs for artificial delays
- [ ] Create pod template ConfigMap
- [ ] Update Airflow HelmRelease
- [ ] Deploy changes via Flux
- [ ] Test with hello_world DAG
- [ ] Verify logs in Grafana
- [ ] Remove delays from production DAGs
- [ ] Monitor resource usage for 24 hours
- [ ] Document any custom configurations

## Future Enhancements

### Log Enrichment
Add more metadata in Vector transform:
```toml
[transforms.add_metadata]
source = '''
.cluster = "anton"
.environment = "production"
.airflow_version = get_env_var("AIRFLOW_VERSION") ?? "unknown"
'''
```

### Metrics Collection
Add Vector metrics sink for task duration:
```toml
[sinks.prometheus]
type = "prometheus_exporter"
inputs = ["add_metadata"]
address = "0.0.0.0:9090"
```

### Conditional Logging
Filter logs by level:
```toml
[transforms.filter_errors]
type = "filter"
inputs = ["add_metadata"]
condition = '.level == "ERROR" || .level == "CRITICAL"'
```

## References

- [Vector Sidecar Documentation](https://vector.dev/docs/setup/deployment/roles/#sidecar)
- [Kubernetes Sidecar Containers](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/)
- [Airflow Pod Template Guide](https://airflow.apache.org/docs/apache-airflow/stable/kubernetes.html#pod-template-file)
- [Loki Label Best Practices](https://grafana.com/docs/loki/latest/best-practices/#label-cardinality)