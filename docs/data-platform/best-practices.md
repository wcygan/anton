# Lakehouse Best Practices Guide

## Overview

This document captures production-grade best practices for operating the Apache Iceberg + Trino + Spark + Nessie data platform, derived from comprehensive analysis of official documentation and real-world deployment patterns.

## Table of Contents

- [Query Optimization](#query-optimization)
- [Iceberg Table Management](#iceberg-table-management)
- [Spark Performance Tuning](#spark-performance-tuning)
- [Trino Optimization](#trino-optimization)
- [Nessie Data Versioning](#nessie-data-versioning)
- [Storage Layer Optimization](#storage-layer-optimization)
- [Monitoring and Observability](#monitoring-and-observability)
- [Operational Procedures](#operational-procedures)

## Query Optimization

### Trino Query Performance

#### Predicate Pushdown and Partition Pruning
```sql
-- ✅ Good: Filter on partition columns first
SELECT * FROM lakehouse.events 
WHERE event_date = '2024-01-15' 
  AND event_type = 'user_action'
  AND created_at > '2024-01-15 10:00:00';

-- ❌ Avoid: Non-partition filters without partition predicates
SELECT * FROM lakehouse.events 
WHERE user_id = 12345; -- Forces full table scan
```

#### Use EXPLAIN for Query Analysis
```sql
-- Always analyze execution plans for performance bottlenecks
EXPLAIN (TYPE DISTRIBUTED)
SELECT count(*) FROM lakehouse.events 
WHERE event_date BETWEEN '2024-01-01' AND '2024-01-31';

-- Look for dynamic filters in the output
EXPLAIN
SELECT count(*)
FROM store_sales JOIN date_dim 
  ON store_sales.ss_sold_date_sk = date_dim.d_date_sk
WHERE d_following_holiday='Y' AND d_year = 2000;
```

#### Optimal Table Statistics
```sql
-- Collect statistics for better query planning
ANALYZE TABLE lakehouse.events;

-- Use table properties for optimization hints
ALTER TABLE lakehouse.events SET PROPERTIES 
'read.split.target-size' = '134217728', -- 128MB splits
'write.target-file-size-bytes' = '134217728';
```

### Complex Grouping Operations
```sql
-- Use GROUPING SETS for multiple aggregation levels
SELECT origin_state, origin_zip, destination_state, sum(package_weight)
FROM shipping
GROUP BY GROUPING SETS (
  (origin_state, origin_zip),
  (origin_state),
  (destination_state),
  ()
);

-- ROLLUP for hierarchical aggregations
SELECT origin_state, origin_zip, sum(package_weight)
FROM shipping
GROUP BY ROLLUP (origin_state, origin_zip);
```

## Iceberg Table Management

### Schema Evolution Best Practices

#### Safe Schema Changes
```sql
-- ✅ Safe operations (always backward compatible)
ALTER TABLE lakehouse.events ADD COLUMN session_id STRING;
ALTER TABLE lakehouse.events ALTER COLUMN user_id TYPE BIGINT;
ALTER TABLE lakehouse.events ALTER COLUMN created_at AFTER event_type;
ALTER TABLE lakehouse.events RENAME COLUMN old_name TO new_name;

-- ⚠️ Careful operations (may break old readers)
ALTER TABLE lakehouse.events DROP COLUMN deprecated_field;
```

#### Partitioning Strategy
```sql
-- Create tables with appropriate partitioning
CREATE TABLE lakehouse.events (
    event_id BIGINT,
    user_id BIGINT,
    event_type STRING,
    event_data MAP<STRING, STRING>,
    created_at TIMESTAMP,
    event_date DATE
) USING iceberg
PARTITIONED BY (days(created_at), event_type)
TBLPROPERTIES (
  'write.format.default' = 'parquet',
  'write.parquet.compression-codec' = 'zstd'
);
```

### Time Travel and Branching

#### Snapshot Management
```sql
-- Query historical data
SELECT * FROM lakehouse.events 
FOR SYSTEM_TIME AS OF '2024-01-15 10:00:00';

SELECT * FROM lakehouse.events 
FOR SYSTEM_VERSION AS OF 8109744798576441359;

-- Inspect table history
SELECT * FROM lakehouse.events.history;
SELECT * FROM lakehouse.events.snapshots;

-- Create branches for experimentation
CALL iceberg.system.create_branch('lakehouse.events', 'experimental-branch');
```

#### Maintenance Operations
```sql
-- Expire old snapshots (run weekly)
CALL iceberg.system.expire_snapshots('lakehouse.events', TIMESTAMP '2024-01-01 00:00:00');

-- Compact small files (run daily for high-write tables)
CALL iceberg.system.rewrite_data_files('lakehouse.events');

-- Rewrite manifests for scan optimization
CALL iceberg.system.rewrite_manifests('lakehouse.events');
```

### Table Property Optimization
```sql
-- Configure for write performance
ALTER TABLE lakehouse.events SET TBLPROPERTIES (
  'write.target-file-size-bytes' = '134217728',  -- 128MB files
  'write.distribution-mode' = 'hash',            -- Even data distribution
  'write.fanout.enabled' = 'true'                -- Parallel writes
);

-- Configure for read performance
ALTER TABLE lakehouse.events SET TBLPROPERTIES (
  'read.split.target-size' = '134217728',        -- Optimal split size
  'read.split.metadata-target-size' = '33554432' -- 32MB metadata splits
);
```

## Spark Performance Tuning

### Kubernetes Resource Management

#### Optimal Resource Allocation
```yaml
# Production Spark job configuration
apiVersion: sparkoperator.k8s.io/v1beta2
kind: SparkApplication
metadata:
  name: production-etl
spec:
  type: Scala
  sparkVersion: "3.5.0"
  driver:
    cores: 2
    memory: "4g"
    serviceAccount: spark-operator
  executor:
    cores: 4
    instances: 6
    memory: "8g"
  dynamicAllocation:
    enabled: true
    initialExecutors: 2
    minExecutors: 2
    maxExecutors: 10
```

#### JVM Optimization
```yaml
# Optimal JVM settings for data platform
sparkConf:
  "spark.sql.adaptive.enabled": "true"
  "spark.sql.adaptive.coalescePartitions.enabled": "true"
  "spark.sql.adaptive.skewJoin.enabled": "true"
  "spark.serializer": "org.apache.spark.serializer.KryoSerializer"
  "spark.executor.extraJavaOptions": >-
    -XX:+UseG1GC
    -XX:+UnlockExperimentalVMOptions
    -XX:+UseZGC
    -XX:+DisableExplicitGC
    -XX:MaxDirectMemorySize=2g
```

### Iceberg Integration Settings
```yaml
sparkConf:
  # Iceberg optimizations
  "spark.sql.iceberg.vectorization.enabled": "true"
  "spark.sql.iceberg.planning.preserve-data-grouping": "true"
  "spark.sql.iceberg.merge.cardinality-check.enabled": "false"
  
  # Nessie catalog configuration
  "spark.sql.catalog.nessie": "org.apache.iceberg.spark.SparkCatalog"
  "spark.sql.catalog.nessie.catalog-impl": "org.apache.iceberg.nessie.NessieCatalog"
  "spark.sql.catalog.nessie.uri": "http://nessie.data-platform.svc.cluster.local:19120/api/v2"
  "spark.sql.catalog.nessie.ref": "main"
  "spark.sql.catalog.nessie.warehouse": "s3a://iceberg-warehouse/"
```

### Structured Streaming Best Practices

#### Watermarking for Late Data
```python
# Configure watermarks for late-arriving data
streaming_df = (spark
  .readStream
  .format("kafka")
  .option("kafka.bootstrap.servers", "kafka:9092")
  .load()
  .withWatermark("timestamp", "10 minutes")  # Handle 10min late data
  .groupBy(
    window(col("timestamp"), "5 minutes"),
    col("event_type")
  )
  .count()
)
```

#### Checkpointing Strategy
```python
# Configure reliable checkpointing
query = (streaming_df
  .writeStream
  .format("iceberg")
  .outputMode("append")
  .option("checkpointLocation", "s3a://checkpoints/stream-processor/")
  .option("path", "lakehouse.events")
  .trigger(processingTime='30 seconds')  # Micro-batch interval
  .start()
)
```

## Trino Optimization

### Cluster Configuration

#### Memory and Resource Tuning
```properties
# coordinator.properties
coordinator=true
node-scheduler.include-coordinator=false
http-server.http.port=8080
query.max-memory=60GB
query.max-memory-per-node=16GB
query.max-total-memory-per-node=20GB
discovery-server.enabled=true
discovery.uri=http://trino-coordinator:8080
```

```properties
# worker.properties  
coordinator=false
http-server.http.port=8080
query.max-memory=60GB
query.max-memory-per-node=16GB
query.max-total-memory-per-node=20GB
discovery.uri=http://trino-coordinator:8080
```

#### JVM Configuration
```properties
# jvm.config for production workloads
-server
-Xmx16G
-XX:InitialRAMPercentage=80
-XX:MaxRAMPercentage=80
-XX:G1HeapRegionSize=32M
-XX:+ExplicitGCInvokesConcurrent
-XX:+ExitOnOutOfMemoryError
-XX:+HeapDumpOnOutOfMemoryError
-XX:ReservedCodeCacheSize=512M
-XX:PerMethodRecompilationCutoff=10000
-XX:PerBytecodeRecompilationCutoff=10000
-Djdk.attach.allowAttachSelf=true
-Djdk.nio.maxCachedBufferSize=2000000
```

### Catalog Configuration

#### Iceberg REST Catalog
```properties
# catalog/iceberg.properties
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://nessie.data-platform.svc.cluster.local:19120/iceberg
iceberg.rest-catalog.warehouse=s3a://iceberg-warehouse/
hive.s3.endpoint=http://rook-ceph-rgw-my-store.rook-ceph.svc.cluster.local
hive.s3.path-style-access=true
hive.s3.ssl.enabled=false
```

### Query Optimization Techniques

#### Pushdown Configuration
```sql
-- Verify pushdown is working
EXPLAIN (TYPE DISTRIBUTED)
SELECT regionkey, count(*)
FROM nation
GROUP BY regionkey;

-- Should show pushdown in execution plan
```

## Nessie Data Versioning

### Branch Management Strategy

#### Development Workflow
```bash
# Create feature branch for experimentation
curl -X POST http://nessie:19120/api/v2/trees/branch/feature-new-schema \
  -H "Content-Type: application/json" \
  -d '{"name": "feature-new-schema", "reference": {"name": "main", "type": "BRANCH"}}'

# Work on feature branch
USE nessie.`branch_feature-new-schema`;
CREATE OR REPLACE TABLE lakehouse.events_v2 AS 
SELECT *, new_column FROM lakehouse.events;

# Merge back to main after validation
curl -X POST http://nessie:19120/api/v2/trees/merge \
  -H "Content-Type: application/json" \
  -d '{
    "fromRefName": "feature-new-schema",
    "toBranch": "main",
    "isDryRun": false
  }'
```

#### Tag Management
```bash
# Create release tags
curl -X POST http://nessie:19120/api/v2/trees/tag/release-v1.0 \
  -H "Content-Type: application/json" \
  -d '{"name": "release-v1.0", "reference": {"name": "main", "type": "BRANCH"}}'
```

### Cross-Table Transactions
```sql
-- Atomic changes across multiple tables
BEGIN;
INSERT INTO lakehouse.orders VALUES (...);
UPDATE lakehouse.inventory SET quantity = quantity - 1 WHERE product_id = 123;
COMMIT;
```

## Storage Layer Optimization

### Ceph S3 Configuration

#### Performance Tuning
```yaml
# Ceph configuration for analytical workloads
apiVersion: ceph.rook.io/v1
kind: CephObjectStore
spec:
  gateway:
    port: 80
    instances: 3
    placement:
      nodeAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          nodeSelectorTerms:
          - matchExpressions:
            - key: role
              operator: In
              values: ["storage-node"]
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
      limits:
        cpu: "4"
        memory: "8Gi"
```

#### Bucket Lifecycle Policies
```json
{
  "Rules": [
    {
      "ID": "IcebergTableMaintenance",
      "Status": "Enabled",
      "Filter": {"Prefix": "iceberg-warehouse/"},
      "Expiration": {"Days": 365},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    },
    {
      "ID": "CheckpointCleanup", 
      "Status": "Enabled",
      "Filter": {"Prefix": "checkpoints/"},
      "Expiration": {"Days": 30}
    }
  ]
}
```

### File Size Optimization
```sql
-- Configure optimal file sizes for query performance
ALTER TABLE lakehouse.events SET TBLPROPERTIES (
  'write.target-file-size-bytes' = '134217728',  -- 128MB for balance
  'write.delete.target-file-size-bytes' = '67108864'  -- 64MB for deletes
);
```

## Monitoring and Observability

### Key Metrics to Track

#### Trino Cluster Health
```yaml
# Prometheus alerts for Trino
groups:
- name: trino-alerts
  rules:
  - alert: TrinoQueryLatencyHigh
    expr: trino_query_execution_time_seconds{quantile="0.95"} > 30
    for: 5m
    annotations:
      summary: "Trino query latency is high"
  
  - alert: TrinoWorkerDown
    expr: up{job="trino-worker"} == 0
    for: 1m
    annotations:
      summary: "Trino worker is down"
```

#### Spark Application Monitoring
```yaml
# ServiceMonitor for Spark metrics
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: spark-applications
spec:
  selector:
    matchLabels:
      spark-role: driver
  endpoints:
  - port: driver-ui
    path: /metrics/prometheus
```

#### Iceberg Table Health
```sql
-- Monitor table statistics
SELECT 
  table_name,
  snapshot_id,
  operation,
  added_data_files_count,
  added_records_count,
  total_data_files_count,
  total_records_count
FROM lakehouse.events.snapshots
WHERE committed_at > current_timestamp - INTERVAL '24' HOUR;
```

### Dashboard Configuration
```json
{
  "dashboard": {
    "title": "Data Platform Overview",
    "panels": [
      {
        "title": "Query Response Times",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, trino_query_execution_time_seconds_bucket)",
            "legendFormat": "95th percentile"
          }
        ]
      },
      {
        "title": "Table Size Growth",
        "targets": [
          {
            "expr": "iceberg_table_size_bytes",
            "legendFormat": "{{table_name}}"
          }
        ]
      }
    ]
  }
}
```

## Operational Procedures

### Daily Maintenance

#### Automated Compaction
```bash
#!/bin/bash
# Daily compaction job for high-write tables

tables=("lakehouse.events" "lakehouse.user_sessions" "lakehouse.transactions")

for table in "${tables[@]}"; do
  trino --execute "CALL iceberg.system.rewrite_data_files('${table}')"
  trino --execute "CALL iceberg.system.expire_snapshots('${table}', TIMESTAMP '$(date -d '7 days ago' --iso-8601)')"
done
```

#### Health Checks
```bash
#!/bin/bash
# Platform health check script

# Check Nessie API
curl -f http://nessie.data-platform.svc.cluster.local:19120/api/v2/config || exit 1

# Check Trino coordinator
curl -f http://trino.data-platform.svc.cluster.local:8080/v1/info || exit 1

# Check S3 connectivity
aws s3 --endpoint-url $CEPH_S3_ENDPOINT ls s3://iceberg-warehouse/ || exit 1

# Validate table access
trino --execute "SELECT count(*) FROM iceberg.information_schema.tables" || exit 1
```

### Capacity Planning

#### Storage Growth Estimation
```sql
-- Track storage growth patterns
WITH daily_growth AS (
  SELECT 
    DATE(committed_at) as date,
    SUM(added_data_files_count) as files_added,
    SUM(added_records_count) as records_added
  FROM lakehouse.events.snapshots
  WHERE committed_at > current_timestamp - INTERVAL '30' DAY
  GROUP BY DATE(committed_at)
)
SELECT 
  date,
  files_added,
  records_added,
  AVG(files_added) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as avg_files_7d
FROM daily_growth
ORDER BY date;
```

#### Resource Utilization
```bash
# Monitor cluster resource usage
kubectl top nodes
kubectl top pods -n data-platform --sort-by=memory

# Check storage utilization
kubectl get cephcluster -n rook-ceph -o jsonpath='{.items[0].status.ceph.capacity}'
```

### Disaster Recovery

#### Backup Validation
```bash
#!/bin/bash
# Validate backup integrity

# Test metadata backup restoration
kubectl create job --from=cronjob/nessie-backup nessie-backup-test-$(date +%s)

# Verify backup files exist
aws s3 --endpoint-url $CEPH_S3_ENDPOINT ls s3://data-platform-backups/nessie/ --recursive

# Test table restoration from snapshot
trino --execute "CREATE TABLE lakehouse.events_restore AS SELECT * FROM lakehouse.events FOR SYSTEM_VERSION AS OF $(cat last_known_good_snapshot_id)"
```

## Security Best Practices

### Access Control
```sql
-- Create role-based access
CREATE ROLE data_analyst;
CREATE ROLE data_engineer;

-- Grant appropriate permissions
GRANT SELECT ON SCHEMA lakehouse TO data_analyst;
GRANT ALL ON SCHEMA lakehouse TO data_engineer;
```

### Network Security
```yaml
# Network policy for data platform
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: data-platform-policy
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/part-of: data-platform
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    - namespaceSelector:
        matchLabels:
          name: data-platform
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: rook-ceph
```

---

## Related Documentation

- [Main Data Platform README](./README.md)
- [Iceberg Operations Guide](./iceberg-operations.md)
- [Nessie Deployment Guide](./nessie-deployment.md)
- [Trino Kubernetes Deployment](./trino-kubernetes-deployment.md)
- [Bootstrap Process Documentation](./bootstrap/)