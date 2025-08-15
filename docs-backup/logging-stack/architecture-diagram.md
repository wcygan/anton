# Loki + Alloy Architecture Diagram

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                               Kubernetes Cluster (Anton)                             │
│                                                                                       │
│  ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐        │
│  │       Node 1        │   │       Node 2        │   │       Node 3        │        │
│  │    (k8s-1)          │   │    (k8s-2)          │   │    (k8s-3)          │        │
│  │                     │   │                     │   │                     │        │
│  │  ┌─────────────┐    │   │  ┌─────────────┐    │   │  ┌─────────────┐    │        │
│  │  │   Alloy     │────┼───┼──│   Alloy     │────┼───┼──│   Alloy     │    │        │
│  │  │ (DaemonSet) │    │   │  │ (DaemonSet) │    │   │  │ (DaemonSet) │    │        │
│  │  └─────────────┘    │   │  └─────────────┘    │   │  └─────────────┘    │        │
│  │         │           │   │         │           │   │         │           │        │
│  │         │ Collects  │   │         │ Collects  │   │         │ Collects  │        │
│  │         │ Pod Logs  │   │         │ Pod Logs  │   │         │ Pod Logs  │        │
│  │         ▼           │   │         ▼           │   │         ▼           │        │
│  │  ┌─────────────┐    │   │  ┌─────────────┐    │   │  ┌─────────────┐    │        │
│  │  │ Application │    │   │  │ Application │    │   │  │ Application │    │        │
│  │  │    Pods     │    │   │  │    Pods     │    │   │  │    Pods     │    │        │
│  │  └─────────────┘    │   │  └─────────────┘    │   │  └─────────────┘    │        │
│  └─────────────────────┘   └─────────────────────┘   └─────────────────────┘        │
│                                        │                                              │
│                                        │ Push Logs via HTTP                          │
│                                        ▼                                              │
│                            ┌─────────────────────┐                                   │
│                            │    Loki Gateway     │                                   │
│                            │   (Load Balancer)   │                                   │
│                            │                     │                                   │
│                            │ ┌─────────────────┐ │                                   │
│                            │ │ NGINX Ingress   │ │                                   │
│                            │ │ Controller      │ │                                   │
│                            │ └─────────────────┘ │                                   │
│                            └─────────────────────┘                                   │
│                                        │                                              │
│                                        ▼                                              │
│                            ┌─────────────────────┐                                   │
│                            │       Loki          │                                   │
│                            │ (SingleBinary Mode) │                                   │
│                            │                     │                                   │
│                            │ ┌─────────────────┐ │                                   │
│                            │ │   Ingester      │ │                                   │
│                            │ │   Distributor   │ │                                   │
│                            │ │   Querier       │ │                                   │
│                            │ │   Query Frontend│ │                                   │
│                            │ └─────────────────┘ │                                   │
│                            └─────────────────────┘                                   │
│                                        │                                              │
│                                        │ Stores Chunks & Index                       │
│                                        ▼                                              │
│                            ┌─────────────────────┐                                   │
│                            │    Ceph Storage     │                                   │
│                            │  (S3 Compatible)    │                                   │
│                            │                     │                                   │
│                            │ ┌─────────────────┐ │                                   │
│                            │ │ ObjectStore RGW │ │                                   │
│                            │ │   Buckets:      │ │                                   │
│                            │ │ - loki-chunks   │ │                                   │
│                            │ │ - loki-ruler    │ │                                   │
│                            │ └─────────────────┘ │                                   │
│                            └─────────────────────┘                                   │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### Log Collection Layer

#### Alloy DaemonSet
- **Purpose**: Collect logs from all pods on each node
- **Deployment**: 1 pod per node (3 total)
- **Configuration**: 
  - Kubernetes pod discovery
  - JSON log parsing
  - Label extraction and enrichment
  - Rate limiting and batching

```yaml
# Key Configuration Elements
discovery.kubernetes "pods" {
  role = "pod"
}

loki.source.kubernetes "pods" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.write.default.receiver]
}

loki.write "default" {
  endpoint {
    url = "http://loki-gateway.monitoring.svc.cluster.local/loki/api/v1/push"
  }
}
```

### Log Processing Layer

#### Loki Gateway
- **Purpose**: Load balancer and reverse proxy for Loki
- **Technology**: NGINX
- **Features**:
  - Request routing
  - Load balancing 
  - Rate limiting
  - Authentication (when enabled)

#### Loki (SingleBinary Mode)
- **Purpose**: Log aggregation, indexing, and querying
- **Mode**: SingleBinary (all components in one process)
- **Components**:
  - **Distributor**: Receives logs from Alloy
  - **Ingester**: Builds chunks and stores them
  - **Querier**: Handles LogQL queries
  - **Query Frontend**: Query optimization and caching

### Storage Layer

#### Ceph ObjectStore (S3 Compatible)
- **Purpose**: Persistent storage for log chunks and index
- **Technology**: Rook-managed Ceph cluster
- **Configuration**:
  - 3-node cluster with replication
  - S3-compatible API via RGW
  - Automatic compression

```yaml
# Storage Schema
storage_config:
  boltdb_shipper:
    active_index_directory: /loki/boltdb-shipper-active
    cache_location: /loki/boltdb-shipper-cache
    shared_store: s3
  aws:
    s3: s3://loki-chunks/
    endpoint: http://rook-ceph-rgw-storage.storage.svc.cluster.local
    s3forcepathstyle: true
```

## Data Flow

### 1. Log Collection
```
Application Pod → stdout/stderr → Container Runtime → kubelet → Alloy
```

### 2. Log Processing
```
Alloy → JSON Parsing → Label Extraction → Batching → HTTP Push
```

### 3. Log Ingestion
```
Loki Gateway → Distributor → Ingester → Chunk Creation → S3 Storage
```

### 4. Log Querying
```
Grafana → Loki Gateway → Query Frontend → Querier → Index + Chunks → Results
```

## Network Architecture

### Service Discovery
```
┌─────────────────────────────────────────────────────────────┐
│                    Service Mesh                             │
│                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐       │
│  │   Alloy     │   │   Alloy     │   │   Alloy     │       │
│  │  (Node 1)   │   │  (Node 2)   │   │  (Node 3)   │       │
│  └─────────────┘   └─────────────┘   └─────────────┘       │
│         │                   │                   │           │
│         └───────────────────┼───────────────────┘           │
│                             │                               │
│                             ▼                               │
│                  ┌─────────────────────┐                   │
│                  │   loki-gateway      │                   │
│                  │   ClusterIP         │                   │
│                  │   Port: 80          │                   │
│                  └─────────────────────┘                   │
│                             │                               │
│                             ▼                               │
│                  ┌─────────────────────┐                   │
│                  │      loki           │                   │
│                  │   ClusterIP         │                   │
│                  │   Port: 3100        │                   │
│                  └─────────────────────┘                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### External Access
```
┌─────────────────────────────────────────────────────────────┐
│                  External Access                            │
│                                                             │
│  ┌─────────────┐                                           │
│  │   Grafana   │ ──────────────────────────────────────────┼──► Tailscale
│  │   WebUI     │   https://grafana.walleye-monster.ts.net  │
│  └─────────────┘                                           │
│         │                                                   │
│         │ LogQL Queries                                     │
│         ▼                                                   │
│  ┌─────────────┐                                           │
│  │ Loki Gateway│                                           │
│  │   Service   │                                           │
│  └─────────────┘                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Security Architecture

### Authentication & Authorization
- **Alloy**: Uses ServiceAccount with RBAC for pod discovery
- **Loki**: Internal-only access (no external authentication)
- **Grafana**: Authenticated via existing Grafana instance

### Network Security
- **Internal Traffic**: All traffic within cluster network
- **Encryption**: TLS termination at Grafana (external access)
- **Isolation**: Monitoring namespace with NetworkPolicies

### Data Security
- **At Rest**: Ceph storage encryption (configurable)
- **In Transit**: HTTP within cluster (could upgrade to HTTPS)
- **Access Control**: RBAC-based service access

## Monitoring and Observability

### Self-Monitoring
```
┌─────────────────────────────────────────────────────────────┐
│                   Monitoring Stack                          │
│                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐       │
│  │ Loki Canary │   │ ServiceMon  │   │  Grafana    │       │
│  │ (Log Test)  │   │ (Metrics)   │   │ (Dashboard) │       │
│  └─────────────┘   └─────────────┘   └─────────────┘       │
│         │                   │                   ▲           │
│         │ Synthetic Logs    │ Prometheus        │           │
│         ▼                   ▼                   │           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Loki                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                             │                               │
│                             │ Query Results                 │
│                             └───────────────────────────────┘
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Key Metrics Monitored
- **Ingestion Rate**: `rate(loki_ingester_streams_created_total[5m])`
- **Query Latency**: `histogram_quantile(0.95, rate(loki_request_duration_seconds_bucket[5m]))`
- **Error Rate**: `rate(loki_request_total{status_code!~"2.."}[5m])`
- **Storage Usage**: Ceph bucket size and growth rate

## Capacity Planning

### Current Resources (Per Component)

| Component | CPU Request | Memory Request | Replicas | Storage |
|-----------|-------------|----------------|----------|---------|
| Loki | 1000m | 2Gi | 1 | 20Gi (local cache) |
| Gateway | 100m | 128Mi | 1 | - |
| Alloy | 500m | 512Mi | 3 (DaemonSet) | - |
| **Total** | **2100m** | **3.2Gi** | **5 pods** | **20Gi + S3** |

### Storage Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Storage Layout                            │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                Ceph S3 Storage                          │ │
│  │                                                         │ │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │ │
│  │  │    OSD 1    │   │    OSD 2    │   │    OSD 3    │   │ │
│  │  │  (Node 1)   │   │  (Node 2)   │   │  (Node 3)   │   │ │
│  │  │   1TB NVMe  │   │   1TB NVMe  │   │   1TB NVMe  │   │ │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   │ │
│  │                                                         │ │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │ │
│  │  │    OSD 4    │   │    OSD 5    │   │    OSD 6    │   │ │
│  │  │  (Node 1)   │   │  (Node 2)   │   │  (Node 3)   │   │ │
│  │  │   1TB NVMe  │   │   1TB NVMe  │   │   1TB NVMe  │   │ │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   │ │
│  │                                                         │ │
│  │  Total Raw: 6TB                                         │ │
│  │  Usable (3x replication): 2TB                          │ │
│  │  Current Usage: ~50GB (2.5%)                           │ │
│  └─────────────────────────────────────────────────────────┘ │
│                             │                               │
│                             │ S3 API                        │
│                             ▼                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │               RGW Buckets                               │ │
│  │                                                         │ │
│  │  loki-chunks/      (Log data chunks)                   │ │
│  │  loki-ruler/       (Ruler data)                        │ │
│  │  loki-admin/       (Admin API data)                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Retention and Lifecycle

```yaml
# Current Retention Configuration
retention_period: 168h  # 7 days
compactor:
  working_directory: /loki/compactor
  shared_store: s3
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

## Disaster Recovery

### Backup Strategy
- **Configuration**: GitOps in version control
- **Data**: S3 chunks replicated across 3 nodes
- **Secrets**: External Secrets with 1Password backup

### Recovery Procedures
- **Pod failure**: Kubernetes automatic restart
- **Node failure**: DaemonSet reschedules, Loki reschedules
- **Storage failure**: Ceph replication provides redundancy
- **Complete disaster**: Restore from S3 and redeploy

---

**Architecture Version**: 1.0  
**Last Updated**: 2025-06-15  
**Deployment Mode**: SingleBinary with S3 Backend  
**Total Components**: 5 pods across 3 nodes