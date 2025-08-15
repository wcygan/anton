# LogQL Query Library

This document contains common LogQL queries for the Loki + Alloy logging stack.

## Basic Queries

### View All Logs from a Namespace
```logql
{namespace="flux-system"}
```

### View Logs from Specific Pod
```logql
{namespace="monitoring", pod="loki-0"}
```

### View Logs from All Alloy Collectors
```logql
{job="monitoring/alloy"}
```

## Error Detection

### Find All Errors Across Namespaces
```logql
{job="monitoring/alloy"} |~ "(?i)(error|fail|exception|panic)"
```

### Critical System Errors
```logql
{namespace=~"flux-system|storage|external-secrets|kube-system"} |~ "(?i)(error|fail|warning|exception)"
```

### Flux Controller Errors
```logql
{namespace="flux-system", pod=~".*-controller-.*"} |~ "error|Error|ERROR|fail"
```

## Application-Specific Queries

### Airflow Logs (when migrated)
```logql
{namespace="data", app="airflow"} | json | dag_id != ""
```

### Ceph Storage Warnings
```logql
{namespace="storage"} |~ "(?i)(health.*warn|health.*err|osd.*down|degraded|scrub)"
```

### Ingress Activity
```logql
{namespace="network", app=~"nginx.*"} | json | status >= 400
```

## Performance Analysis

### Log Volume by Namespace (last hour)
```logql
sum by (namespace) (count_over_time({job="monitoring/alloy"} [1h]))
```

### Top 10 Pods by Log Volume
```logql
topk(10, sum by (pod) (count_over_time({job="monitoring/alloy"} [5m])))
```

### Log Rate per Node
```logql
sum by (node_name) (rate({job="monitoring/alloy"} [5m]))
```

## Debugging Queries

### Recent Pod Restarts
```logql
{job="monitoring/alloy"} |~ "Back-off restarting failed container"
```

### OOMKilled Pods
```logql
{job="monitoring/alloy"} |~ "OOMKilled"
```

### Failed Deployments
```logql
{namespace="flux-system"} |~ "reconciliation failed"
```

## Advanced Filtering

### Exclude Noisy Logs
```logql
{job="monitoring/alloy"} 
  | namespace != "kube-public" 
  | pod !~ ".*-canary-.*"
  |~ "error"
```

### JSON Parsing with Field Extraction
```logql
{namespace="monitoring", app="loki"} 
  | json 
  | level="error" 
  | line_format "{{.ts}} {{.level}} {{.msg}}"
```

### Rate Limiting Detection
```logql
{job="monitoring/alloy"} |~ "rate.*limit|throttl"
```

## Grafana Integration Tips

### Using Variables in Dashboards
```logql
{namespace="$namespace", pod=~"$pod"}
```

### Time Range Best Practices
- Use `[5m]` for real-time monitoring
- Use `[1h]` for trend analysis
- Use `[24h]` for daily reports
- Avoid queries > 7 days (retention limit)

## Performance Optimization

### Efficient Label Selectors
```logql
# Good - specific namespace
{namespace="monitoring", app="loki"}

# Bad - regex on high cardinality label
{pod=~".*loki.*"}
```

### Use Stream Selectors First
```logql
# Good - filter at stream level
{namespace="monitoring"} |~ "error"

# Bad - filter after selecting all logs
{job="monitoring/alloy"} | namespace="monitoring" |~ "error"
```

## Common Issues and Solutions

### Query Timeout
- Reduce time range
- Add more specific label selectors
- Use `limit` parameter

### No Data
- Check if Alloy is running: `{job="monitoring/alloy"}`
- Verify namespace exists
- Check time range is within retention

### Slow Queries
- Avoid regex on pod names
- Use exact label matches when possible
- Limit time range to necessary window