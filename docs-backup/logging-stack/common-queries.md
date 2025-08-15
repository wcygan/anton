# LogQL Common Queries Reference

## Overview

This document provides a comprehensive collection of LogQL queries for common debugging, monitoring, and operational tasks in the Loki logging system.

## Basic Query Patterns

### Stream Selectors

```logql
# All logs from a specific namespace
{namespace="monitoring"}

# All logs from specific pods
{namespace="monitoring", pod=~"loki-.*"}

# All logs from a specific container
{namespace="monitoring", container="loki"}

# Multiple namespaces
{namespace=~"monitoring|storage"}

# Exclude specific namespaces
{namespace!~"kube-.*"}
```

### Time Range Queries

```logql
# Logs from the last hour
{namespace="monitoring"}[1h]

# Logs from a specific time range
{namespace="monitoring"}[2025-06-15T10:00:00Z:2025-06-15T11:00:00Z]

# Rate of logs in last 5 minutes
rate({namespace="monitoring"}[5m])
```

## Application-Specific Queries

### Airflow Logs

```logql
# All Airflow task logs
{namespace="airflow"}

# Failed task logs only
{namespace="airflow"} |~ "(?i)(error|fail|exception)"

# Specific DAG execution
{namespace="airflow"} |~ "dag_id.*my-dag"

# Scheduler logs
{namespace="airflow", pod=~"airflow-scheduler-.*"}

# Worker logs with errors
{namespace="airflow", pod=~"airflow-worker-.*"} |= "ERROR"

# Task completion status
{namespace="airflow"} |~ "Task.*state.*success|failed"
```

### Kubernetes System Logs

```logql
# Kubelet logs
{namespace="kube-system", pod=~".*kubelet.*"}

# CoreDNS query logs
{namespace="kube-system", pod=~"coredns-.*"} |= "query"

# CNI (Cilium) logs
{namespace="kube-system", pod=~"cilium-.*"}

# Control plane logs
{namespace="kube-system"} |~ "(?i)(apiserver|controller|scheduler)"
```

### Flux GitOps Logs

```logql
# All Flux operations
{namespace="flux-system"}

# Failed reconciliations
{namespace="flux-system"} |~ "(?i)(fail|error)" |~ "reconcil"

# Successful deployments
{namespace="flux-system"} |= "success" |~ "reconcil"

# Specific controller logs
{namespace="flux-system", pod=~".*controller.*"}

# Chart download issues
{namespace="flux-system"} |~ "chart.*download|fetch"
```

### Storage and Ceph Logs

```logql
# All storage-related logs
{namespace="storage"}

# Ceph OSD logs
{namespace="storage", pod=~"rook-ceph-osd.*"}

# Ceph monitor logs
{namespace="storage", pod=~"rook-ceph-mon.*"}

# RGW (S3) gateway logs
{namespace="storage", pod=~"rook-ceph-rgw.*"}

# Storage failures
{namespace="storage"} |~ "(?i)(fail|error|down)"
```

### Monitoring Stack Logs

```logql
# Prometheus logs
{namespace="monitoring", pod=~"prometheus-.*"}

# Grafana authentication logs
{namespace="monitoring", pod=~".*grafana.*"} |~ "login|auth"

# Alert manager notifications
{namespace="monitoring", pod=~"alertmanager-.*"} |= "notification"

# Loki self-monitoring
{namespace="monitoring", pod=~"loki-.*"} |= "level=error"
```

## Error and Alert Queries

### General Error Detection

```logql
# All error logs across cluster
{namespace!=""} |~ "(?i)(error|err|fail|exception|panic|fatal)"

# Critical errors only
{namespace!=""} |~ "(?i)(critical|fatal|panic)"

# Application startup failures
{namespace!=""} |~ "(?i)(start.*fail|init.*error|boot.*fail)"

# Memory and resource errors
{namespace!=""} |~ "(?i)(oom|out of memory|memory.*exceeded)"

# Network connectivity errors
{namespace!=""} |~ "(?i)(connection.*refused|timeout|network.*error)"
```

### HTTP Error Patterns

```logql
# HTTP 5xx errors
{namespace!=""} |~ "5[0-9][0-9]"

# HTTP 4xx errors
{namespace!=""} |~ "4[0-9][0-9]"

# API gateway errors
{namespace="network"} |~ "(?i)(502|503|504)"

# Authentication failures
{namespace!=""} |~ "(?i)(auth.*fail|unauthorized|forbidden)"
```

### Performance and Resource Issues

```logql
# High CPU usage warnings
{namespace!=""} |~ "(?i)(cpu.*high|throttl)"

# Memory pressure indicators
{namespace!=""} |~ "(?i)(memory.*pressure|low.*memory)"

# Disk space warnings
{namespace!=""} |~ "(?i)(disk.*full|space.*low|no.*space)"

# Pod evictions
{namespace!=""} |~ "(?i)(evict|preempt)"
```

## Structured Log Parsing

### JSON Log Parsing

```logql
# Parse JSON logs and filter by level
{namespace="app"} | json | level="error"

# Extract specific JSON fields
{namespace="app"} | json | line_format "{{.timestamp}} {{.level}} {{.message}}"

# Filter by JSON field values
{namespace="app"} | json | user_id="12345"

# Multi-level JSON parsing
{namespace="app"} | json | metadata_user_id="admin"
```

### Regex Extraction

```logql
# Extract IP addresses
{namespace="network"} | regexp `(?P<ip>\d+\.\d+\.\d+\.\d+)`

# Extract request IDs
{namespace="app"} | regexp `request_id=(?P<req_id>[a-f0-9-]+)`

# Extract response times
{namespace="app"} | regexp `duration=(?P<duration>\d+)ms`

# Extract error codes
{namespace="app"} | regexp `error_code=(?P<code>\d+)`
```

## Metric Queries

### Log Rate Calculations

```logql
# Logs per second by namespace
sum by (namespace) (rate({namespace!=""}[1m]))

# Error rate by application
sum by (namespace) (rate({namespace!=""} |~ "(?i)error"[5m]))

# Log volume trends
sum(rate({namespace!=""}[1h]))

# Top chatty applications
topk(5, sum by (namespace) (rate({namespace!=""}[5m])))
```

### Performance Metrics

```logql
# Query response time percentiles
histogram_quantile(0.95, 
  sum by (le) (
    rate({namespace="app"} | regexp `duration=(?P<duration>\d+)` | unwrap duration[5m])
  )
)

# Request volume by endpoint
sum by (endpoint) (
  rate({namespace="api"} | json | endpoint!=""[5m])
)

# Error rate by service
sum by (service) (
  rate({namespace!=""} |~ "(?i)error" | json | service!=""[5m])
) / sum by (service) (
  rate({namespace!=""} | json | service!=""[5m])
)
```

## Troubleshooting Queries

### Pod Lifecycle Events

```logql
# Pod startup sequences
{namespace!=""} |~ "(?i)(start|init|boot|ready)"

# Pod termination events
{namespace!=""} |~ "(?i)(stop|shutdown|term|exit)"

# Container restart reasons
{namespace!=""} |~ "(?i)(restart|crash|oom.*kill)"

# Health check failures
{namespace!=""} |~ "(?i)(health.*check|readiness|liveness).*fail"
```

### Network Debugging

```logql
# DNS resolution issues
{namespace!=""} |~ "(?i)(dns.*fail|resolve.*error|nxdomain)"

# Service discovery problems
{namespace!=""} |~ "(?i)(service.*not.*found|endpoint.*not.*ready)"

# Load balancer issues
{namespace="network"} |~ "(?i)(upstream.*error|backend.*fail)"

# Certificate problems
{namespace!=""} |~ "(?i)(cert.*error|tls.*fail|x509)"
```

### Storage Debugging

```logql
# PVC mounting issues
{namespace!=""} |~ "(?i)(mount.*fail|volume.*error)"

# Ceph storage errors
{namespace="storage"} |~ "(?i)(placement.*group|pg.*error|osd.*down)"

# S3 connectivity problems
{namespace!=""} |~ "(?i)(s3.*error|bucket.*not.*found)"
```

## Security and Audit Queries

### Authentication Events

```logql
# Login attempts
{namespace!=""} |~ "(?i)(login|signin|authenticate)"

# Failed authentication
{namespace!=""} |~ "(?i)(auth.*fail|login.*fail|invalid.*credential)"

# Privilege escalation attempts
{namespace!=""} |~ "(?i)(sudo|privilege|escalat|unauthorized)"

# Service account token usage
{namespace!=""} |~ "serviceaccount.*token"
```

### Suspicious Activity

```logql
# Unusual command execution
{namespace!=""} |~ "(?i)(exec|shell|command)" |~ "(?i)(curl|wget|nc|netcat)"

# File system access patterns
{namespace!=""} |~ "(?i)(/etc/passwd|/etc/shadow|\.ssh|\.kube)"

# Network scanning indicators
{namespace!=""} |~ "(?i)(port.*scan|nmap|connect.*refused)" 

# Crypto mining indicators
{namespace!=""} |~ "(?i)(mining|miner|crypto|bitcoin|monero)"
```

## Performance Optimization Tips

### Query Optimization

1. **Always use label filters first**: `{namespace="app"}` before log line filters
2. **Limit time ranges**: Use shortest time range needed
3. **Avoid regex when possible**: Use `|=` instead of `|~` for exact matches
4. **Use structured logging**: JSON parsing is more efficient than regex
5. **Aggregate when possible**: Use `sum by()` instead of individual series

### Example Optimized vs Unoptimized

```logql
# ❌ Unoptimized - searches all logs
{namespace!=""} |~ "error.*database"

# ✅ Optimized - filters by namespace first
{namespace="app"} |= "error" |= "database"

# ❌ Unoptimized - complex regex
{namespace="app"} |~ "user_id.*([0-9]+).*action.*login"

# ✅ Optimized - structured parsing
{namespace="app"} | json | action="login" | user_id!=""
```

## Dashboard Query Examples

### For Grafana Dashboards

```logql
# Error rate panel
sum by (namespace) (
  rate({namespace!=""} |~ "(?i)error"[5m])
) / sum by (namespace) (
  rate({namespace!=""}[5m])
) * 100

# Log volume heatmap
sum by (namespace) (
  rate({namespace!=""}[1m])
)

# Top error messages table
topk(10, 
  sum by (extracted_message) (
    rate({namespace!=""} |~ "(?i)error" | regexp `(?P<extracted_message>error.*)`[5m])
  )
)
```

---

**Usage Notes:**
- Test queries on small time ranges first
- Use Grafana's Explore feature for query development
- Save frequently used queries as Grafana shortcuts
- Monitor query performance in Loki metrics

**Last Updated**: 2025-06-15  
**Version**: 1.0