# Grafana Performance Optimizations

This document details the performance optimizations applied to the Grafana deployment in the homelab cluster.

## Overview

The optimizations focus on improving query performance, reducing dashboard load times, and enhancing overall user experience through caching, pre-computation, and configuration tuning.

## Implemented Optimizations

### 1. Prometheus Recording Rules

Created pre-computed metrics to reduce real-time query overhead:

- **Namespace Metrics**: CPU, memory, pod counts, restart rates
- **Flux Metrics**: Success rates, reconciliation durations, failing resources
- **Cluster Metrics**: Overall utilization, node availability
- **Storage Metrics**: PVC usage, Ceph health status
- **Ingress Metrics**: Request rates, error rates, latency percentiles

These recording rules run at 30-60 second intervals and significantly reduce computation time for common queries.

### 2. Grafana Configuration Enhancements

Enhanced `grafana.ini` settings for better performance:

- **HTTP/2 enabled** with 250 concurrent streams for better multiplexing
- **Query timeouts** increased to 300s for complex queries
- **Database connection pooling** optimized (25 idle, 100 max connections)
- **Response compression** enabled with balanced level 6
- **Query validation** disabled to reduce overhead
- **Concurrent rendering** limited to 10 to prevent resource spikes
- **Metrics collection** reduced to 30s intervals

### 3. Datasource Optimizations

#### Loki Datasource
- Streaming enabled with 1000 chunk size
- Cache-Control headers set to 10 minutes
- Query timeout aligned with Grafana settings
- Max lines limited to 1000 for faster loading

#### Prometheus Datasource  
- POST method for large queries
- Incremental querying enabled with 10m overlap
- Time interval aligned with scrape interval (30s)
- Source resolution limited to 5m for efficiency

### 4. Dashboard Improvements

- Created optimized dashboard using recording rules
- Set minimum refresh intervals (30s) to prevent overload
- Added max data points limits to panels
- Implemented efficient LogQL queries with line formatting
- Used instant queries for tables instead of range queries

### 5. Loki Recording Rules

Created LogQL recording rules for common log metrics:
- Log volume by namespace (1m rate)
- Error/warning rates by namespace (5m rate)
- Flux-specific error tracking
- Ingress access log rates
- Application restart pattern detection

## Performance Gains

Expected improvements from these optimizations:

1. **50-70% reduction** in query execution time through recording rules
2. **30-40% improvement** in dashboard load times with caching
3. **Reduced CPU usage** during peak query periods
4. **Better responsiveness** with optimized refresh rates
5. **Lower backend load** on Prometheus and Loki

## Monitoring Performance

Use the new "Grafana Performance Monitoring" dashboard to track:
- API response times (p95, p99)
- Request rates by method and status
- Datasource query durations
- Active session counts
- CPU and memory usage

## Best Practices

1. **Use recording rules** for any query that runs frequently
2. **Set appropriate refresh intervals** - not everything needs real-time updates
3. **Limit query scope** - use time ranges and label selectors effectively
4. **Cache static content** - enable browser caching for dashboards
5. **Monitor query performance** - identify and optimize slow queries

## Future Optimizations

Consider implementing:
1. External cache backend (DragonflyDB) for query result caching
2. Dashboard provisioning optimization
3. Plugin lazy loading
4. CDN for static assets
5. Query cost estimation and limits