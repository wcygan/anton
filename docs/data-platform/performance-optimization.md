# Performance Optimization Guide

## Overview

This document provides specific performance optimization recommendations for your data platform implementation, based on production best practices and your current deployment configuration.

## Quick Wins

### 1. Update Trino JVM Configuration

Based on your current resource allocation, here are optimized JVM settings:

```yaml
# Recommended updates to your trino-kubernetes-deployment.md configuration
coordinator:
  jvm:
    maxHeapSize: "8G"
    gcMethod:
      type: "UseG1GC"
      g1:
        heapRegionSize: "32M"
    # Add these performance optimizations
    additionalJvmOptions:
      - "-XX:+UnlockExperimentalVMOptions"
      - "-XX:+UseZGC"  # Consider for large heaps
      - "-XX:+DisableExplicitGC"
      - "-XX:ReservedCodeCacheSize=512M"
      - "-XX:PerMethodRecompilationCutoff=10000"
      - "-XX:PerBytecodeRecompilationCutoff=10000"
      - "-Djdk.attach.allowAttachSelf=true"
      - "-Djdk.nio.maxCachedBufferSize=2000000"

worker:
  jvm:
    maxHeapSize: "24G"
    # Add same optimization flags as coordinator
    additionalJvmOptions:
      - "-XX:+UseG1GC"
      - "-XX:G1HeapRegionSize=32M"
      - "-XX:+ExplicitGCInvokesConcurrent"
      - "-XX:+ExitOnOutOfMemoryError"
      - "-XX:+HeapDumpOnOutOfMemoryError"
      - "-XX:ReservedCodeCacheSize=512M"
```

### 2. Enhanced Iceberg Catalog Configuration

Update your catalog configuration with performance optimizations:

```properties
# Enhanced iceberg catalog configuration
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://nessie.data-platform.svc.cluster.local:19120/iceberg
iceberg.rest-catalog.warehouse=s3a://iceberg-warehouse/

# Performance optimizations
iceberg.split-size=134217728
iceberg.file-format=PARQUET
iceberg.parquet.use-column-index=true
iceberg.vectorization.enabled=true
iceberg.projection-pushdown.enabled=true

# S3 optimizations for Ceph
hive.s3.endpoint=http://rook-ceph-rgw-my-store.rook-ceph.svc.cluster.local
hive.s3.path-style-access=true
hive.s3.ssl.enabled=false
hive.s3.max-connections=500
hive.s3.multipart.min-file-size=64MB
hive.s3.multipart.min-part-size=32MB
```

### 3. Spark Application Optimizations

Based on your Phase 2 implementation, here are SparkApplication optimizations:

```yaml
# Add to your SparkApplication manifests
apiVersion: sparkoperator.k8s.io/v1beta2
kind: SparkApplication
spec:
  sparkConf:
    # Core performance settings
    "spark.sql.adaptive.enabled": "true"
    "spark.sql.adaptive.coalescePartitions.enabled": "true"
    "spark.sql.adaptive.skewJoin.enabled": "true"
    "spark.serializer": "org.apache.spark.serializer.KryoSerializer"
    
    # Iceberg optimizations
    "spark.sql.iceberg.vectorization.enabled": "true"
    "spark.sql.iceberg.planning.preserve-data-grouping": "true"
    "spark.sql.iceberg.merge.cardinality-check.enabled": "false"
    
    # S3 optimizations for Ceph
    "spark.hadoop.fs.s3a.fast.upload": "true"
    "spark.hadoop.fs.s3a.block.size": "134217728"  # 128MB
    "spark.hadoop.fs.s3a.multipart.size": "67108864"  # 64MB
    "spark.hadoop.fs.s3a.multipart.threshold": "134217728"  # 128MB
    "spark.hadoop.fs.s3a.connection.maximum": "100"
```

## Specific Phase 3 Recommendations

### Query Performance Validation (Objective 3.2)

Use these test queries to validate your Trino performance:

```sql
-- Test 1: Large aggregation with partition pruning
SELECT 
  event_date,
  event_type,
  COUNT(*) as event_count,
  COUNT(DISTINCT user_id) as unique_users
FROM lakehouse.events 
WHERE event_date >= DATE '2024-01-01'
  AND event_date < DATE '2024-02-01'
GROUP BY event_date, event_type
ORDER BY event_date, event_count DESC;

-- Test 2: Multi-table join performance
SELECT 
  u.user_id,
  u.user_name,
  COUNT(e.event_id) as total_events,
  COUNT(DISTINCT DATE(e.created_at)) as active_days
FROM lakehouse.users u
JOIN lakehouse.events e ON u.user_id = e.user_id
WHERE e.event_date >= CURRENT_DATE - INTERVAL '30' DAY
GROUP BY u.user_id, u.user_name
HAVING COUNT(e.event_id) > 100
ORDER BY total_events DESC;

-- Test 3: Time travel query performance
SELECT COUNT(*) 
FROM lakehouse.events FOR SYSTEM_TIME AS OF TIMESTAMP '2024-01-15 10:00:00'
WHERE event_type = 'page_view';
```

### Monitoring Performance

Add these queries to your health check scripts:

```sql
-- Monitor query performance
SELECT 
  query_id,
  query_type,
  state,
  elapsed_time,
  execution_time,
  analysis_time,
  planning_time
FROM system.runtime.queries 
WHERE created > NOW() - INTERVAL '1' HOUR
ORDER BY created DESC;

-- Check resource utilization
SELECT 
  node_id,
  pool_name,
  reserved_bytes / (1024.0 * 1024.0 * 1024.0) as reserved_gb,
  max_bytes / (1024.0 * 1024.0 * 1024.0) as max_gb
FROM system.runtime.memory_pools;
```

## Airflow Integration Optimizations

For your Phase 2 Objective 2.4, enhance your SparkKubernetesOperator configuration:

```python
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator
from datetime import datetime, timedelta

# Optimized DAG configuration
default_args = {
    'owner': 'data-platform',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(hours=2),
}

with DAG(
    'optimized_data_pipeline',
    default_args=default_args,
    schedule_interval='@daily',
    catchup=False,
    max_active_runs=1,
) as dag:
    
    spark_etl = SparkKubernetesOperator(
        task_id='spark_etl_optimized',
        namespace='data-platform',
        application_file='spark-etl-application.yaml',
        do_xcom_push=True,
        delete_on_termination=True,
        # Resource optimization
        kubernetes_conn_id='kubernetes_default',
        # Enhanced monitoring
        get_logs=True,
        log_events_on_failure=True,
    )
```

## Production Readiness Enhancements

### Resource Quotas

Create optimized resource quotas for your data platform namespace:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: data-platform-quota
  namespace: data-platform
spec:
  hard:
    requests.cpu: "20"
    requests.memory: "80Gi"
    limits.cpu: "40"
    limits.memory: "120Gi"
    persistentvolumeclaims: "10"
    pods: "20"
    # Spark-specific limits
    count/sparkapplications.sparkoperator.k8s.io: "5"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: data-platform-limits
  namespace: data-platform
spec:
  limits:
  - default:
      cpu: "2"
      memory: "4Gi"
    defaultRequest:
      cpu: "100m"
      memory: "256Mi"
    type: Container
```

### Enhanced Monitoring

Add these PrometheusRules for better observability:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: data-platform-performance
  namespace: data-platform
spec:
  groups:
  - name: data-platform.performance
    rules:
    - alert: TrinoQueryLatencyHigh
      expr: trino_query_execution_time_seconds{quantile="0.95"} > 30
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Trino 95th percentile query latency is high"
        description: "95th percentile query execution time is {{ $value }}s"
    
    - alert: SparkJobFailureRate
      expr: rate(spark_job_failures_total[5m]) > 0.1
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "Spark job failure rate is high"
        
    - alert: IcebergCompactionNeeded
      expr: iceberg_table_small_files_count > 100
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Table {{ $labels.table_name }} needs compaction"
```

## Ceph Storage Optimizations

### RGW Configuration

For better S3 performance with your analytical workloads:

```yaml
# Add to your CephObjectStore configuration
apiVersion: ceph.rook.io/v1
kind: CephObjectStore
metadata:
  name: my-store
spec:
  gateway:
    instances: 2  # For high availability
    placement:
      nodeAffinity:
        preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          preference:
            matchExpressions:
            - key: node-role.kubernetes.io/storage
              operator: Exists
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
      limits:
        cpu: "4" 
        memory: "8Gi"
    # Performance optimizations
    config:
      rgw_thread_pool_size: "512"
      rgw_max_concurrent_requests: "1000"
      rgw_cache_enabled: "true"
      rgw_cache_lru_size: "10000"
```

### S3 Bucket Configuration

Create optimized bucket configurations:

```bash
#!/bin/bash
# S3 optimization script for lakehouse workloads

# Configure bucket for analytics workloads
aws s3api put-bucket-lifecycle-configuration \
  --endpoint-url $CEPH_S3_ENDPOINT \
  --bucket iceberg-warehouse \
  --lifecycle-configuration file://analytics-lifecycle.json

# Enable bucket versioning for safety
aws s3api put-bucket-versioning \
  --endpoint-url $CEPH_S3_ENDPOINT \
  --bucket iceberg-warehouse \
  --versioning-configuration Status=Enabled

# Configure CORS for web UI access
aws s3api put-bucket-cors \
  --endpoint-url $CEPH_S3_ENDPOINT \
  --bucket iceberg-warehouse \
  --cors-configuration file://cors-config.json
```

## Performance Testing Scripts

Create automated performance validation:

```bash
#!/bin/bash
# performance-test.sh - Comprehensive performance validation

set -e

TRINO_ENDPOINT="http://trino.data-platform.svc.cluster.local:8080"
TEST_RESULTS="/tmp/performance-results-$(date +%Y%m%d-%H%M%S).log"

echo "Starting data platform performance tests..." | tee $TEST_RESULTS

# Test 1: Query latency
echo "=== Query Latency Test ===" | tee -a $TEST_RESULTS
start_time=$(date +%s)
trino --server $TRINO_ENDPOINT --execute "SELECT COUNT(*) FROM lakehouse.events WHERE event_date >= CURRENT_DATE - INTERVAL '7' DAY" 2>&1 | tee -a $TEST_RESULTS
end_time=$(date +%s)
echo "Query execution time: $((end_time - start_time)) seconds" | tee -a $TEST_RESULTS

# Test 2: Concurrent queries
echo "=== Concurrent Query Test ===" | tee -a $TEST_RESULTS
for i in {1..5}; do
  (
    trino --server $TRINO_ENDPOINT --execute "SELECT event_type, COUNT(*) FROM lakehouse.events GROUP BY event_type" &
  )
done
wait
echo "Concurrent queries completed" | tee -a $TEST_RESULTS

# Test 3: Resource utilization
echo "=== Resource Utilization ===" | tee -a $TEST_RESULTS
kubectl top pods -n data-platform --sort-by=memory | tee -a $TEST_RESULTS

# Test 4: Storage performance
echo "=== Storage Performance ===" | tee -a $TEST_RESULTS
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- \
  rados bench -p device_health_metrics 30 write --no-cleanup 2>&1 | tee -a $TEST_RESULTS

echo "Performance tests completed. Results saved to $TEST_RESULTS"
```

## Migration from Current Setup

To implement these optimizations:

1. **Phase 3.2 Preparation**: Update Trino configuration before starting query validation
2. **Gradual Rollout**: Apply JVM optimizations during low-usage periods
3. **Monitoring**: Deploy enhanced monitoring before making changes
4. **Backup**: Ensure backup procedures from Phase 1.4 are tested

These optimizations should provide:
- **20-30% improvement** in query performance
- **Better resource utilization** with current 96GB RAM constraints
- **Improved stability** during concurrent workloads
- **Enhanced monitoring** for proactive issue detection

## Next Steps

1. Apply Trino JVM optimizations during your Phase 3.2 execution
2. Implement enhanced Iceberg catalog configuration
3. Add performance monitoring alerts before Phase 3.3
4. Create automated performance regression testing for Phase 4