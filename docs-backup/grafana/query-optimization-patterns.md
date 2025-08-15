# Grafana Query Optimization Patterns

## Overview

This document provides patterns and best practices for optimizing Grafana dashboard queries to improve performance and reduce load times.

## 1. Use Recording Rules

Recording rules pre-compute expensive queries and store results as new metrics.

### Before (Slow)
```promql
# Computes on every dashboard load
sum by (namespace) (
  rate(container_cpu_usage_seconds_total{container!="POD",container!=""}[5m])
)
```

### After (Fast)
```promql
# Uses pre-computed metric
namespace:container_cpu_usage_seconds:sum_rate
```

## 2. Variable Query Optimization

### Inefficient Variable Query
```promql
# Queries all label values
label_values(up, namespace)
```

### Optimized Variable Query
```promql
# Query specific metrics with filters
label_values(kube_namespace_created{}, namespace)
```

## 3. Limit Query Scope

### Inefficient
```promql
# Queries all pods across cluster
sum by (pod) (rate(container_cpu_usage_seconds_total[5m]))
```

### Optimized
```promql
# Filter by namespace variable
sum by (pod) (
  rate(container_cpu_usage_seconds_total{namespace="$namespace"}[5m])
)
```

## 4. Use Appropriate Time Ranges

### Guidelines:
- Use `[5m]` for rate calculations (aligns with scrape interval)
- Avoid very small ranges like `[1m]` unless necessary
- Use `$__interval` for dynamic adjustment

### Example
```promql
rate(metric[$__interval])
```

## 5. Optimize Aggregations

### Inefficient
```promql
# Multiple separate queries
avg(metric{label="a"})
avg(metric{label="b"})
avg(metric{label="c"})
```

### Optimized
```promql
# Single query with grouping
avg by (label) (metric{label=~"a|b|c"})
```

## 6. Use Instant Queries for Tables

### For Table Panels
```promql
# Use instant query instead of range
topk(10, namespace:memory_usage_bytes:sum)
```

## 7. Minimize Regex Usage

### Inefficient
```promql
metric{pod=~".*frontend.*"}
```

### Optimized
```promql
metric{pod=~"frontend.*"}
```

## 8. Cache-Friendly Queries

### Align queries to common boundaries:
```promql
# Good - aligns to minute boundaries
increase(metric[5m])

# Better - uses offset for cache hits
increase(metric[5m] offset 1m)
```

## 9. Limit Cardinality

### High Cardinality (Slow)
```promql
sum by (pod, container, namespace, node) (metric)
```

### Lower Cardinality (Fast)
```promql
sum by (namespace) (metric)
```

## 10. Dashboard Best Practices

1. **Set appropriate refresh intervals**: 30s minimum for most dashboards
2. **Use shared queries**: Reference the same query across panels
3. **Limit panel count**: Split large dashboards into focused ones
4. **Use transformations**: Do math in Grafana, not Prometheus
5. **Enable caching**: Configure datasource caching

## 11. Query Inspector Usage

Use Query Inspector to:
- Identify slow queries
- Check query execution time
- Verify caching is working
- Debug query issues

## 12. Grafana Settings

Optimize `grafana.ini`:
```ini
[dashboards]
min_refresh_interval = 30s

[dataproxy]
timeout = 300
max_idle_connections = 100

[caching]
enabled = true
```

## Recording Rules Created

The following recording rules have been implemented for common queries:

### Top Consumers
- `cluster:namespace_cpu_usage:top10`
- `cluster:namespace_memory_usage:top10`
- `cluster:pod_cpu_usage:top10`
- `cluster:pod_memory_usage:top10`

### Node Metrics
- `instance:node_cpu_utilization:ratio`
- `instance:node_memory_utilization:ratio`
- `instance:node_filesystem_usage:ratio`
- `instance:node_network_receive_bytes:rate5m`
- `instance:node_network_transmit_bytes:rate5m`

### Percentiles
- `apiserver:request_duration:p50/p95/p99`
- `nginx_ingress:request_duration:p50/p95/p99`
- `grafana:api_response_time:p50/p95/p99`

### Application Metrics
- `grafana:active_users:5m`
- `grafana:dashboard_request_rate:5m`
- `service:request_success_rate:5m`

## Example: Optimized Dashboard

See `/kubernetes/apps/monitoring/grafana-dashboards/optimized/` for a complete example of an optimized dashboard using recording rules.