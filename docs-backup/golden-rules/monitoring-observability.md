# Monitoring & Observability Golden Rules

## The Golden Rule

**Never disable monitoring to save resources.** You cannot fix what you cannot see. The cost of debugging without metrics far exceeds the resource cost of monitoring.

## Critical Rules

### 1. Never Delete Prometheus PVCs Without Backup

**WRONG:**
```bash
kubectl delete pvc prometheus-data -n monitoring
```

**RIGHT:**
```bash
# First, snapshot the data
kubectl exec -n monitoring prometheus-0 -- \
  promtool tsdb snapshot /prometheus

# Copy snapshot to backup location
kubectl cp monitoring/prometheus-0:/prometheus/snapshots backup/

# Then safely remove if needed
kubectl delete pvc prometheus-data -n monitoring
```

**Why:** Historical metrics are invaluable for debugging recurring issues.

### 2. Always Set Retention Based on Available Storage

**WRONG:**
```yaml
# Setting retention without checking storage
prometheusSpec:
  retention: 365d  # A year of data!
```

**RIGHT:**
```bash
# First, calculate storage needs
# Ingestion rate (samples/sec) × 2 bytes × retention seconds

# Check available storage
kubectl exec -n monitoring prometheus-0 -- df -h /prometheus

# Set retention with buffer
prometheusSpec:
  retention: 30d
  retentionSize: 80GB  # Leave 20% buffer
```

**Why:** Prometheus will crash when storage fills, losing all monitoring.

### 3. Never Ignore High Cardinality Metrics

**WRONG:**
```yaml
# Scraping everything without thought
- job_name: 'kubernetes-pods'
  kubernetes_sd_configs:
  - role: pod
  # No relabeling to drop high cardinality!
```

**RIGHT:**
```yaml
# Drop high cardinality labels
metric_relabel_configs:
  - source_labels: [__name__]
    regex: 'apiserver_request_duration_seconds.*'
    action: drop  # This metric has huge cardinality
  
  - regex: 'container_id|image_id'
    action: labeldrop  # Drop high cardinality labels
```

**Why:** High cardinality kills Prometheus performance and storage.

### 4. Always Monitor the Monitors

**WRONG:**
```yaml
# No monitoring of monitoring stack
alerting:
  alertmanagers: []
```

**RIGHT:**
```yaml
# Prometheus self-monitoring
- alert: PrometheusDown
  expr: up{job="prometheus"} == 0
  for: 5m

# AlertManager monitoring  
- alert: AlertmanagerDown
  expr: up{job="alertmanager"} == 0
  for: 5m

# Grafana monitoring
- alert: GrafanaDown
  expr: up{job="grafana"} == 0
  for: 5m
```

**Why:** Silent monitoring failures mean you miss critical alerts.

### 5. Never Scrape Faster Than Necessary

**WRONG:**
```yaml
global:
  scrape_interval: 1s      # Too fast!
  evaluation_interval: 1s
```

**RIGHT:**
```yaml
global:
  scrape_interval: 30s     # Standard interval
  evaluation_interval: 30s

# Override for specific critical metrics only
- job_name: 'critical-app'
  scrape_interval: 10s    # Faster only where needed
```

**Why:** Fast scraping multiplies storage needs and CPU usage.

## Observability Stack Standards

### Metrics Retention Tiers

```yaml
# Prometheus (Hot Storage) - 30 days
prometheusSpec:
  retention: 30d
  
# Thanos (Warm Storage) - 90 days
compact:
  retentionResolution5m: 90d
  
# S3 (Cold Storage) - 1 year
objectStorageConfig:
  retention: 365d
```

### Log Retention Strategy

```yaml
# Loki Retention
limits_config:
  retention_period: 168h  # 7 days
  
# Per-Namespace Override
per_tenant_override_config:
  critical-apps:
    retention_period: 720h  # 30 days
```

### Dashboard Management

```yaml
# Grafana Dashboard as Code
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-dashboard
  labels:
    grafana_dashboard: "1"  # Auto-import
data:
  app-dashboard.json: |
    {
      "dashboard": { ... },
      "folderId": 0,
      "overwrite": true
    }
```

## Critical Alerts Configuration

### Must-Have Alerts

```yaml
groups:
  - name: critical
    rules:
      # Disk space
      - alert: DiskSpaceLow
        expr: node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes < 0.1
        for: 5m
        
      # Memory pressure
      - alert: MemoryPressure
        expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.1
        for: 5m
        
      # Pod restarts
      - alert: PodCrashLooping
        expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
        for: 5m
```

## ServiceMonitor Best Practices

### Standard ServiceMonitor Pattern

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: app-metrics
  namespace: monitoring  # Always in monitoring namespace
spec:
  namespaceSelector:
    matchNames:
      - app-namespace
  selector:
    matchLabels:
      app: my-app
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
      relabelings:
        - sourceLabels: [__meta_kubernetes_pod_name]
          targetLabel: pod
```

## Recovery Procedures

### Prometheus Storage Full

```bash
# Emergency: Delete old blocks
kubectl exec -n monitoring prometheus-0 -- \
  find /prometheus -name "01*" -type d -mtime +7 -exec rm -rf {} \;

# Proper fix: Adjust retention
kubectl edit prometheus -n monitoring
# Reduce retention or retentionSize
```

### High Cardinality Explosion

```bash
# Identify high cardinality metrics
kubectl exec -n monitoring prometheus-0 -- \
  promtool tsdb analyze /prometheus

# Drop problematic metrics
# Add to metric_relabel_configs
```

### Lost Dashboards

```bash
# Restore from Git
kubectl apply -f dashboards/

# Restore from Grafana backup
kubectl exec -n monitoring grafana-0 -- \
  grafana-cli admin data-migration restore /var/lib/grafana/backup
```

## Pre-Operation Checklist

- [ ] Current metrics retention vs storage checked
- [ ] Cardinality impact analyzed for new metrics
- [ ] ServiceMonitor tested in dev first
- [ ] Alert rules validated with promtool
- [ ] Dashboard changes committed to Git
- [ ] Backup of Prometheus data recent
- [ ] Monitoring of monitors configured

## Incidents

### 2024-09-12: Prometheus OOM
- **What happened:** Added new service with 10k+ pods
- **Impact:** Prometheus crashed, 6 hours of missing metrics
- **Root cause:** Each pod had unique label (pod ID in metric)
- **Lesson:** Always check cardinality before scraping

### 2024-11-28: Silent Failures
- **What happened:** AlertManager died, no alerts for 2 days
- **Impact:** Missed disk full on critical service
- **Root cause:** No monitoring of monitoring stack
- **Lesson:** Always monitor the monitors