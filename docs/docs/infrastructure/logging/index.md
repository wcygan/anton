---
sidebar_position: 1
---

# Logging

The Anton cluster implements a comprehensive logging solution using the Loki stack to collect, store, and analyze logs from all cluster components and applications.

## Architecture Overview

```mermaid
flowchart TD
    subgraph sources[Log Sources]
        pods[Application Pods<br/>stdout/stderr]
        nodes[Node Logs<br/>systemd/kernel]
        k8s[Kubernetes Components<br/>API/kubelet/scheduler]
    end
    
    subgraph collection[Log Collection]
        promtail[Promtail<br/>Log Agent]
        vector[Vector<br/>(Alternative Agent)]
    end
    
    subgraph processing[Log Processing]
        gateway[Loki Gateway<br/>Load Balancing]
        distributor[Loki Distributor<br/>Log Ingestion]
        ingester[Loki Ingester<br/>Log Processing]
    end
    
    subgraph storage[Storage Layer]
        s3[S3-Compatible Storage<br/>Log Chunks]
        index[Index Storage<br/>BoltDB/Local]
    end
    
    subgraph query[Query Interface]
        querier[Loki Querier<br/>Log Retrieval]
        frontend[Query Frontend<br/>Caching]
        grafana[Grafana<br/>Visualization]
        logcli[LogCLI<br/>Command Line]
    end
    
    sources --> collection
    collection --> processing
    processing --> storage
    storage --> query
    
    classDef source fill:#3498db,color:white
    classDef collect fill:#e74c3c,color:white
    classDef process fill:#f39c12,color:white
    classDef store fill:#9b59b6,color:white
    classDef query fill:#27ae60,color:white
    
    class pods,nodes,k8s source
    class promtail,vector collect
    class gateway,distributor,ingester process
    class s3,index store
    class querier,frontend,grafana,logcli query
```

## Core Components

### Log Collection
- **Promtail**: Primary log shipping agent running as DaemonSet
- **Automatic Discovery**: Kubernetes service discovery for pod logs
- **Log Parsing**: Structured log extraction and labeling

### Log Processing
- **Loki Gateway**: NGINX-based load balancing and authentication
- **Distributor**: Validates and forwards log streams
- **Ingester**: Builds chunks and flushes to storage

### Storage Backend
- **S3 Storage**: Scalable object storage for log chunks (Ceph RGW)
- **Local Index**: BoltDB for log stream indexes
- **Retention Policy**: Configurable log retention periods

### Query Interface
- **Grafana Integration**: Visual log exploration and dashboards
- **LogCLI**: Command-line log querying tool
- **API**: REST API for programmatic access

## Log Sources

### Application Logs
```yaml
# Automatic collection from pod stdout/stderr
spec:
  containers:
    - name: app
      image: myapp:latest
      # Logs automatically collected
```

### Kubernetes Component Logs
- **API Server**: Audit logs and request logs
- **kubelet**: Node agent logs
- **kube-proxy**: Network proxy logs (if enabled)
- **Controller Manager**: Control loop logs

### System Logs
- **systemd**: System service logs
- **kernel**: Kernel messages and events
- **containerd**: Container runtime logs

## Configuration

### Promtail Configuration
```yaml
# DaemonSet configuration for log collection
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: promtail
spec:
  template:
    spec:
      containers:
        - name: promtail
          image: grafana/promtail:latest
          volumeMounts:
            - name: logs
              mountPath: /var/log
              readOnly: true
            - name: pods
              mountPath: /var/lib/docker/containers
              readOnly: true
```

### Loki Configuration
```yaml
# Loki server configuration
auth_enabled: false
server:
  http_listen_port: 3100

ingester:
  chunk_idle_period: 1h
  max_chunk_age: 1h
  chunk_target_size: 1048576

storage_config:
  boltdb_shipper:
    active_index_directory: /loki/boltdb-shipper-active
    cache_location: /loki/boltdb-shipper-cache
  aws:
    s3: s3://loki-chunks
    region: us-east-1
```

## Log Querying

### LogQL Syntax

LogQL is Loki's query language for log analysis:

```logql
# Basic log stream selection
{namespace="monitoring"}

# Filter by multiple labels
{namespace="monitoring", pod=~"prometheus-.*"}

# Text filtering
{namespace="monitoring"} |= "error"

# Regular expressions
{namespace="monitoring"} |~ "error|ERROR|Error"

# Exclude patterns
{namespace="monitoring"} != "debug"

# Metric queries from logs
rate({namespace="monitoring"}[5m])

# Aggregations
sum by (pod) (rate({namespace="monitoring"}[5m]))
```

### Common Query Examples

```logql
# Show all error logs from last hour
{level="error"} |= "error"

# Count error rate per service
sum by (service) (rate({level="error"}[5m]))

# Find logs containing specific text
{namespace="default"} |= "database connection"

# Top 10 logging pods
topk(10, sum by (pod) (rate({namespace!=""}[1h])))

# Application-specific logs
{namespace="monitoring", app="prometheus"} |= "TSDB"
```

## Access and Management

### LogCLI Commands

```bash
# Install LogCLI (if not available)
# curl -fSL -o logcli.zip "https://github.com/grafana/loki/releases/download/v2.9.0/logcli-linux-amd64.zip"

# Query logs
logcli query '{namespace="monitoring"}'

# Query with time range
logcli query --since=1h '{namespace="monitoring"}'

# Live tail logs
logcli tail '{pod="prometheus-server"}'

# Export logs to file
logcli query '{namespace="monitoring"}' > logs.txt
```

### Grafana Integration

```bash
# Port forward to Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

# Access Loki data source
# URL: http://loki-gateway:80
```

### Direct API Access

```bash
# Port forward to Loki
kubectl port-forward -n monitoring svc/loki-gateway 3100:80

# Query via API
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={namespace="monitoring"}' \
  --data-urlencode 'start=2024-01-01T00:00:00Z' \
  --data-urlencode 'end=2024-01-01T01:00:00Z'

# Get label values
curl "http://localhost:3100/loki/api/v1/labels"
curl "http://localhost:3100/loki/api/v1/label/namespace/values"
```

## Management Commands

### Status Monitoring

```bash
# Check Loki components
kubectl get pods -n monitoring -l app.kubernetes.io/name=loki

# View Loki configuration
kubectl get configmap -n monitoring loki-config -o yaml

# Check Promtail status
kubectl get daemonset -n monitoring promtail

# View Promtail logs
kubectl logs -n monitoring -l app.kubernetes.io/name=promtail
```

### Storage Management

```bash
# Check storage usage
kubectl exec -n storage -c toolbox deployment/rook-ceph-tools -- \
  rbd du pool/loki

# View S3 bucket contents
kubectl exec -n storage -c toolbox deployment/rook-ceph-tools -- \
  s3cmd ls s3://loki-chunks/

# Check retention policies
kubectl get configmap -n monitoring loki-config -o yaml | grep retention
```

### Troubleshooting

```bash
# Check Loki ingester status
kubectl logs -n monitoring -l app.kubernetes.io/component=ingester

# Verify log ingestion
kubectl logs -n monitoring -l app.kubernetes.io/name=promtail | grep "entry pushed"

# Test log query performance
time logcli query '{namespace="monitoring"}' --limit=100

# Check gateway health
curl http://loki-gateway/ready
curl http://loki-gateway/metrics
```

## Performance Optimization

### Resource Configuration

```yaml
# Loki resource limits
resources:
  requests:
    memory: 1Gi
    cpu: 500m
  limits:
    memory: 2Gi
    cpu: 1000m
```

### Query Performance

```yaml
# Query frontend caching
query_range:
  cache_results: true
  max_retries: 5
  
limits_config:
  query_timeout: 1m
  max_query_parallelism: 32
```

The logging infrastructure provides comprehensive log aggregation and analysis capabilities, enabling effective troubleshooting, monitoring, and operational insights across the entire Anton cluster.