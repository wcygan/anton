# Trino on Kubernetes with Nessie Integration

## Overview

This document provides comprehensive guidance for deploying Trino on Kubernetes with Nessie catalog integration, covering deployment patterns, configuration details, and operational best practices. Trino is a distributed SQL query engine designed for fast analytic queries against data of any size, while Nessie provides Git-like data versioning capabilities for Apache Iceberg tables.

## Architecture Overview

### Component Integration

```
┌─────────────────────────────────────────────────────┐
│             Trino Web UI (Port 8080)                 │
│                                                      │
│  ┌─────────────┐      ┌─────────────────────────┐  │
│  │ Coordinator │◄────►│      Worker Nodes        │  │
│  │   (Master)  │      │   (Query Execution)      │  │
│  └──────┬──────┘      └─────────────────────────┘  │
│         │                                            │
└─────────┼────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│       Nessie Catalog Service (Port 19120)           │
│                                                      │
│  • REST API for catalog operations                   │
│  • Git-like branching & versioning                   │
│  • Iceberg table metadata management                 │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│          Apache Iceberg Table Format                 │
│                                                      │
│  • Table metadata in Nessie                          │
│  • Data files in S3 (Parquet/ORC/Avro)             │
│  • Schema evolution & time travel                    │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│           S3 Object Storage (Ceph)                   │
└─────────────────────────────────────────────────────┘
```

### Key Components

1. **Trino Coordinator**: Manages query planning, optimization, and coordination
2. **Trino Workers**: Execute query fragments in parallel across the cluster
3. **Nessie Catalog**: Provides versioned metadata management for Iceberg tables
4. **Iceberg Tables**: Column-oriented table format with ACID transactions
5. **S3 Storage**: Stores actual data files in Parquet/ORC/Avro formats

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster with minimum 3 nodes
- 70GB+ available RAM across cluster
- Helm 3.x installed
- Nessie catalog service deployed
- S3-compatible object storage (Ceph, MinIO, AWS S3)
- External Secrets Operator for credential management

### Helm Deployment

1. **Add Trino Helm Repository**

```bash
helm repo add trino https://trinodb.github.io/charts
helm repo update
```

2. **Create Namespace and Secrets**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: data-platform
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: trino-s3-credentials
  namespace: data-platform
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword-connect
    kind: ClusterSecretStore
  target:
    name: trino-s3-credentials
    creationPolicy: Owner
  data:
    - secretKey: access-key
      remoteRef:
        key: ceph-s3-credentials
        property: access_key
    - secretKey: secret-key
      remoteRef:
        key: ceph-s3-credentials
        property: secret_key
```

3. **Deploy Trino via GitOps**

```yaml
# kubernetes/apps/data-platform/trino/ks.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app trino
  namespace: flux-system
spec:
  targetNamespace: data-platform
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 15m
  timeout: 10m
  prune: true
  wait: true
  path: ./kubernetes/apps/data-platform/trino/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  dependsOn:
    - name: nessie
      namespace: data-platform
    - name: external-secrets
      namespace: external-secrets
```

4. **HelmRelease Configuration**

```yaml
# kubernetes/apps/data-platform/trino/app/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: trino
  namespace: data-platform
spec:
  interval: 15m
  chart:
    spec:
      chart: trino
      version: "0.18.0"
      sourceRef:
        kind: HelmRepository
        name: trino
        namespace: flux-system
  values:
    image:
      repository: trinodb/trino
      tag: "435"
      pullPolicy: IfNotPresent
    
    server:
      workers: 2
      
      config:
        # Core configuration
        path: /etc/trino
        http:
          port: 8080
        
        # Query limits
        query:
          maxMemory: "50GB"
          maxMemoryPerNode: "20GB"
          maxTotalMemory: "100GB"
          maxTotalMemoryPerNode: "40GB"
        
        # Memory management
        memory:
          heapHeadroomPerNode: "2GB"
        
        # Discovery
        discovery:
          uri: "http://trino:8080"
    
    # Coordinator configuration
    coordinator:
      jvm:
        maxHeapSize: "8G"
        gcMethod:
          type: "UseG1GC"
          g1:
            heapRegionSize: "32M"
      
      config:
        # Coordinator-specific settings
        query.max-queued-queries: 1000
        query.max-concurrent-queries: 100
        
        # Session properties
        query.max-run-time: "24h"
        query.max-execution-time: "12h"
      
      resources:
        requests:
          memory: "8Gi"
          cpu: "2"
        limits:
          memory: "10Gi"
          cpu: "4"
    
    # Worker configuration  
    worker:
      jvm:
        maxHeapSize: "24G"
        gcMethod:
          type: "UseG1GC"
          g1:
            heapRegionSize: "32M"
      
      config:
        # Worker-specific settings
        task.max-worker-threads: 64
        task.min-drivers: 8
        
        # Spilling configuration
        spill-enabled: true
        spiller-spill-path: "/tmp/spill"
        spill-compression-enabled: true
        
        # Exchange configuration  
        exchange.max-buffer-size: "64MB"
        exchange.concurrent-request-multiplier: 3
      
      resources:
        requests:
          memory: "24Gi"
          cpu: "4"
        limits:
          memory: "26Gi"
          cpu: "8"
    
    # Catalog configuration for Nessie
    additionalCatalogs:
      iceberg: |
        connector.name=iceberg
        iceberg.catalog.type=rest
        iceberg.rest-catalog.uri=http://nessie:19120/api/v2
        iceberg.rest-catalog.prefix=iceberg
        iceberg.rest-catalog.warehouse=s3a://iceberg-data
        
        # S3 configuration
        fs.native-s3.enabled=true
        s3.endpoint=http://rook-ceph-rgw-storage.storage.svc.cluster.local
        s3.access-key=${ENV:S3_ACCESS_KEY}
        s3.secret-key=${ENV:S3_SECRET_KEY}
        s3.path-style-access=true
        s3.region=us-east-1
        
        # Performance optimizations
        s3.max-connections=500
        s3.max-error-retries=10
        s3.connect-timeout=5s
        s3.socket-timeout=5s
        
        # Enable S3 Select pushdown
        s3select-pushdown.enabled=true
        s3select-pushdown.max-connections=20
        
        # Iceberg-specific optimizations
        iceberg.compression-codec=ZSTD
        iceberg.use-file-size-from-metadata=true
        iceberg.split-size=64MB
        iceberg.max-splits-per-file=20
    
    # Mount S3 credentials as environment variables
    envFrom:
      - secretRef:
          name: trino-s3-credentials
    
    # Service configuration
    service:
      type: ClusterIP
      port: 8080
    
    # ServiceMonitor for Prometheus
    serviceMonitor:
      enabled: true
      labels:
        prometheus.io/operator: kube-prometheus
    
    # Additional volumes for spilling
    additionalVolumes:
      - name: spill-volume
        emptyDir:
          sizeLimit: 100Gi
    
    additionalVolumeMounts:
      - name: spill-volume
        mountPath: /tmp/spill
```

## Nessie Integration Configuration

### Nessie REST Catalog Setup

The Nessie catalog provides Git-like versioning for Iceberg tables:

```properties
# iceberg.properties
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://nessie:19120/api/v2
iceberg.rest-catalog.prefix=iceberg
iceberg.rest-catalog.warehouse=s3a://iceberg-data

# Authentication (if enabled)
iceberg.rest-catalog.authentication.type=BEARER
iceberg.rest-catalog.authentication.token=${ENV:NESSIE_TOKEN}

# Default branch
iceberg.rest-catalog.ref=main

# Table defaults
iceberg.table-default-file-format=PARQUET
iceberg.compression-codec=ZSTD
```

### Working with Nessie Branches

```sql
-- List available branches
SELECT * FROM system.metadata.catalogs;

-- Create a new branch
CALL iceberg.system.create_branch('main', 'feature-branch');

-- Switch to a different branch
USE iceberg."feature-branch";

-- Create table on feature branch
CREATE TABLE iceberg."feature-branch".sales (
    id BIGINT,
    product_id BIGINT,
    quantity INTEGER,
    price DECIMAL(10,2),
    sale_date DATE
) WITH (
    format = 'PARQUET',
    partitioning = ARRAY['month(sale_date)']
);

-- Merge changes back to main
CALL iceberg.system.merge_branch('feature-branch', 'main');
```

## Web Interface Access

### Trino Web UI

The Trino Web UI provides real-time query monitoring and cluster status:

1. **Port Forward for Local Access**

```bash
kubectl port-forward -n data-platform svc/trino 8080:8080
```

2. **Ingress Configuration (Tailscale)**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: trino-ui
  namespace: data-platform
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
spec:
  ingressClassName: tailscale
  rules:
    - host: trino.${SECRET_DOMAIN}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: trino
                port:
                  number: 8080
```

### Web UI Features

- **Query Overview**: List of running, queued, and finished queries
- **Query Details**: Execution plan, stage information, and performance metrics
- **Cluster Overview**: Worker status, memory usage, and CPU utilization
- **Stage Performance**: Visual representation of query execution stages
- **Live Plan**: Interactive query execution plan visualization

## Query Examples with Iceberg

### Basic Table Operations

```sql
-- Show all tables in Nessie catalog
SHOW TABLES FROM iceberg.lakehouse;

-- Create an Iceberg table
CREATE TABLE iceberg.lakehouse.events (
    event_id BIGINT,
    user_id BIGINT,
    event_type VARCHAR,
    event_time TIMESTAMP(6) WITH TIME ZONE,
    properties MAP(VARCHAR, VARCHAR)
) WITH (
    format = 'PARQUET',
    partitioning = ARRAY['day(event_time)', 'event_type'],
    sorted_by = ARRAY['event_time']
);

-- Insert data
INSERT INTO iceberg.lakehouse.events
VALUES 
    (1, 100, 'click', TIMESTAMP '2025-01-15 10:00:00 UTC', MAP(ARRAY['page'], ARRAY['home'])),
    (2, 101, 'view', TIMESTAMP '2025-01-15 10:05:00 UTC', MAP(ARRAY['page'], ARRAY['products']));

-- Query with time travel
SELECT * FROM iceberg.lakehouse.events FOR TIMESTAMP AS OF TIMESTAMP '2025-01-15 09:00:00 UTC';

-- Show table history
SELECT * FROM iceberg.lakehouse."events$history";

-- Show table snapshots
SELECT * FROM iceberg.lakehouse."events$snapshots";
```

### Advanced Analytics Queries

```sql
-- Window functions with Iceberg tables
WITH user_sessions AS (
    SELECT 
        user_id,
        event_time,
        event_type,
        LAG(event_time) OVER (PARTITION BY user_id ORDER BY event_time) as prev_event_time,
        CASE 
            WHEN event_time - LAG(event_time) OVER (PARTITION BY user_id ORDER BY event_time) > INTERVAL '30' MINUTE 
            THEN 1 
            ELSE 0 
        END as new_session
    FROM iceberg.lakehouse.events
),
session_ids AS (
    SELECT 
        *,
        SUM(new_session) OVER (PARTITION BY user_id ORDER BY event_time) as session_id
    FROM user_sessions
)
SELECT 
    user_id,
    session_id,
    MIN(event_time) as session_start,
    MAX(event_time) as session_end,
    COUNT(*) as event_count,
    ARRAY_AGG(DISTINCT event_type) as event_types
FROM session_ids
GROUP BY user_id, session_id;

-- Optimize table (compaction)
ALTER TABLE iceberg.lakehouse.events EXECUTE optimize(file_size_threshold => '128MB');

-- Expire old snapshots
ALTER TABLE iceberg.lakehouse.events EXECUTE expire_snapshots(retention_threshold => '7d');
```

## Performance Optimization

### Query Performance Tuning

1. **Session Properties for Large Queries**

```sql
-- Set session properties
SET SESSION query_max_memory = '40GB';
SET SESSION query_max_memory_per_node = '15GB';
SET SESSION task_concurrency = 32;
SET SESSION join_distribution_type = 'AUTOMATIC';

-- Enable dynamic filtering
SET SESSION enable_dynamic_filtering = true;
SET SESSION dynamic_filtering_wait_timeout = '1s';
```

2. **Table Statistics**

```sql
-- Analyze table to update statistics
ANALYZE iceberg.lakehouse.events;

-- Show table statistics
SHOW STATS FOR iceberg.lakehouse.events;
```

3. **Partitioning Best Practices**

```sql
-- Create well-partitioned table
CREATE TABLE iceberg.lakehouse.sales_optimized (
    sale_id BIGINT,
    product_id BIGINT,
    store_id INTEGER,
    sale_date DATE,
    amount DECIMAL(10,2)
) WITH (
    format = 'PARQUET',
    partitioning = ARRAY['year(sale_date)', 'month(sale_date)', 'bucket(store_id, 50)'],
    sorted_by = ARRAY['sale_date', 'product_id']
);
```

### Memory Management

1. **Spilling Configuration**

```yaml
worker:
  config:
    # Enable spilling for large queries
    spill-enabled: true
    spiller-spill-path: "/tmp/spill"
    spill-compression-enabled: true
    spill-encryption-enabled: false
    
    # Spill space limits
    spiller-max-used-space-threshold: 0.9
    spiller-threads: 4
```

2. **Memory Pools**

```sql
-- Check memory pools
SELECT * FROM system.runtime.nodes;

-- Monitor memory usage
SELECT 
    node_id,
    heap_used / 1e9 as heap_used_gb,
    heap_available / 1e9 as heap_available_gb,
    CAST(heap_used AS DOUBLE) / heap_available as heap_utilization
FROM system.runtime.nodes;
```

### S3 Select Optimization

Enable S3 Select pushdown for improved query performance:

```properties
# In catalog properties
s3select-pushdown.enabled=true
s3select-pushdown.max-connections=20
s3select-pushdown.experimental-textfile-pushdown-enabled=true

# Filter and projection pushdown
projection-pushdown-enabled=true
filter-pushdown-enabled=true
```

## Monitoring and Observability

### Prometheus Metrics

Key metrics to monitor:

```yaml
# PrometheusRule for Trino
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: trino-alerts
  namespace: monitoring
spec:
  groups:
    - name: trino.rules
      rules:
        - alert: TrinoHighQueryFailureRate
          expr: |
            rate(trino_queries_failed_total[5m]) > 0.1
          labels:
            severity: warning
          annotations:
            summary: "High query failure rate in Trino"
            
        - alert: TrinoWorkerDown
          expr: |
            up{job="trino-worker"} == 0
          for: 2m
          labels:
            severity: critical
            
        - alert: TrinoMemoryPressure
          expr: |
            (trino_memory_pool_reserved_bytes / trino_memory_pool_total_bytes) > 0.9
          for: 5m
          labels:
            severity: warning
```

### Grafana Dashboard

Essential panels for Trino monitoring:

1. **Query Metrics**
   - Queries per second
   - Query duration percentiles (p50, p95, p99)
   - Failed queries rate
   - Queue depth

2. **Resource Usage**
   - Memory utilization per node
   - CPU usage per worker
   - Network I/O
   - Disk spill usage

3. **Catalog Operations**
   - Table scan rate
   - Partition pruning effectiveness
   - S3 request rate
   - Cache hit ratio

## Troubleshooting

### Common Issues and Solutions

1. **Query Timeout**

```sql
-- Check long-running queries
SELECT 
    query_id,
    state,
    queued_time,
    analysis_time,
    execution_time,
    query
FROM system.runtime.queries
WHERE state = 'RUNNING'
ORDER BY execution_time DESC;

-- Kill specific query
CALL system.runtime.kill_query('query_id_here');
```

2. **Memory Issues**

```bash
# Check memory allocation
kubectl exec -n data-platform deploy/trino-coordinator -- \
  curl -s http://localhost:8080/v1/cluster | jq '.memoryInfo'

# Identify memory-intensive queries
kubectl exec -n data-platform deploy/trino-coordinator -- \
  curl -s http://localhost:8080/v1/query | \
  jq '.[] | select(.memoryReservation > 10000000000) | {queryId, memoryReservation, state}'
```

3. **Worker Communication Issues**

```bash
# Check worker discovery
kubectl exec -n data-platform deploy/trino-coordinator -- \
  curl -s http://localhost:8080/v1/node | jq '.'

# Verify worker logs
kubectl logs -n data-platform -l app.kubernetes.io/component=worker --tail=100
```

4. **Nessie Connection Problems**

```bash
# Test Nessie connectivity
kubectl exec -n data-platform deploy/trino-coordinator -- \
  curl -s http://nessie:19120/api/v2/config

# Check catalog configuration
kubectl exec -n data-platform deploy/trino-coordinator -- \
  cat /etc/trino/catalog/iceberg.properties
```

## Security Considerations

### Authentication and Authorization

1. **Enable Authentication**

```yaml
coordinator:
  config:
    http-server.authentication.type: PASSWORD
    http-server.authentication.password.file: /etc/trino/password.db
```

2. **Configure Authorization**

```yaml
coordinator:
  config:
    access-control.config-files: /etc/trino/access-control.json
```

3. **Secure S3 Access**

```properties
# Use IAM roles or secure credential management
s3.use-instance-credentials=true
# Or use External Secrets
s3.access-key=${ENV:S3_ACCESS_KEY}
s3.secret-key=${ENV:S3_SECRET_KEY}
```

### Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: trino-network-policy
  namespace: data-platform
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: trino
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: data-platform
      ports:
        - protocol: TCP
          port: 8080
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: data-platform
    - to:
        - namespaceSelector:
            matchLabels:
              name: storage
      ports:
        - protocol: TCP
          port: 80  # S3 API
```

## Best Practices

### Deployment Recommendations

1. **Resource Allocation**
   - Coordinator: 8-16GB RAM, 2-4 CPU cores
   - Workers: 24-48GB RAM per worker, 4-8 CPU cores
   - Reserve 20% memory headroom for JVM overhead

2. **Scaling Strategy**
   - Scale workers horizontally for query concurrency
   - Use node affinity to distribute workers across nodes
   - Consider dedicated nodes for Trino workloads

3. **Storage Configuration**
   - Use local SSDs for spill storage
   - Configure adequate tmp space (100GB+ per worker)
   - Enable compression for spilled data

### Query Optimization Tips

1. **Use Appropriate File Formats**
   - Parquet for analytics (best compression, columnar)
   - ORC for mixed workloads
   - Avro for streaming ingestion

2. **Optimize Table Design**
   - Partition by low-cardinality columns (date, region)
   - Sort by high-cardinality filter columns
   - Use bucketing for join optimization

3. **Query Best Practices**
   - Filter early in the query
   - Use approximate functions when possible
   - Avoid SELECT * on wide tables
   - Leverage partition pruning

## Integration with Data Platform

### Spark Integration

```scala
// Read Iceberg table from Spark
val df = spark.read
  .format("iceberg")
  .option("catalog", "nessie")
  .option("namespace", "lakehouse")
  .load("events")

// Write to Iceberg table
df.write
  .format("iceberg")
  .mode("append")
  .save("nessie.lakehouse.events")
```

### Airflow Integration

```python
from airflow.providers.trino.operators.trino import TrinoOperator

analyze_data = TrinoOperator(
    task_id='analyze_sales',
    trino_conn_id='trino_default',
    sql="""
        INSERT INTO iceberg.lakehouse.sales_summary
        SELECT 
            date_trunc('day', sale_date) as summary_date,
            COUNT(*) as total_sales,
            SUM(amount) as total_revenue
        FROM iceberg.lakehouse.sales
        WHERE sale_date = {{ ds }}
        GROUP BY date_trunc('day', sale_date)
    """,
    dag=dag
)
```

## References

- [Trino Documentation](https://trino.io/docs/current/)
- [Trino on Kubernetes Guide](https://trino.io/docs/current/installation/kubernetes.html)
- [Trino Web UI Guide](https://trino.io/docs/current/admin/web-interface.html)
- [Nessie Documentation](https://projectnessie.org/)
- [Iceberg-Nessie-Trino Integration](https://projectnessie.org/guides/trino/)
- [Trino Helm Chart](https://github.com/trinodb/charts)