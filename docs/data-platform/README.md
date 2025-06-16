# Data Platform Documentation

This directory contains comprehensive documentation for the Apache Iceberg + Spark + Trino data platform deployment on Kubernetes.

## Overview

The data platform provides a modern lakehouse architecture for analytical workloads, combining:
- **Apache Iceberg**: Table format for huge analytic datasets
- **Apache Spark**: Distributed data processing engine
- **Trino**: Fast distributed SQL query engine
- **Nessie**: Git-like catalog for Iceberg tables

## Documentation Structure

### Core Documentation

- [`proposal.md`](./proposal.md) - Strategic overview and business case for the data platform
- [`investigation.md`](./investigation.md) - Technical analysis and architecture decisions
- [`gitops-implementation.md`](./gitops-implementation.md) - GitOps patterns and compliance analysis

### Bootstrap Process

The [`bootstrap/`](./bootstrap/) directory contains the phased deployment plan:

1. [`00-readiness.md`](./bootstrap/00-readiness.md) - Trigger conditions and prerequisites
2. [`01-foundation.md`](./bootstrap/01-foundation.md) - S3 storage and Nessie catalog setup
3. [`02-compute.md`](./bootstrap/02-compute.md) - Spark Operator deployment
4. [`03-analytics.md`](./bootstrap/03-analytics.md) - Trino cluster configuration
5. [`04-production.md`](./bootstrap/04-production.md) - Production readiness procedures
6. [`goals.json`](./bootstrap/goals.json) - Progress tracking and objective management

### Operational Guides

- [`best-practices.md`](./best-practices.md) - Production-grade best practices for lakehouse operations
- [`performance-optimization.md`](./performance-optimization.md) - Specific optimizations for your deployment
- [`backup-procedures.md`](./backup-procedures.md) - Nessie metadata backup and recovery

## Current Status

**Phase 2: Compute Platform** (27% Complete)
- ✅ Phase 1: Foundation (Complete)
  - S3 storage validated
  - Nessie catalog deployed
  - Iceberg operations tested
  - Backup procedures implemented
- 🔄 Phase 2: Compute Platform (In Progress)
  - ✅ Spark Operator installed
  - ⏳ Basic Spark job execution
  - ⏳ Iceberg integration
  - ⏳ Airflow integration
- ⏸️ Phase 3: Analytics Engine (Pending)
- ⏸️ Phase 4: Production Readiness (Pending)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Trino (SQL Engine)                 │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│              Nessie (Catalog Service)                │
├─────────────────────┬───────────────────────────────┤
│                     │                                │
│  ┌─────────────┐   │   ┌────────────────────────┐ │
│  │   Spark     │   │   │   Iceberg Tables       │ │
│  │  Operator   │◄──┴──►│  (Parquet on S3)       │ │
│  └─────────────┘       └────────────────────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│              Ceph S3 Object Storage                  │
└─────────────────────────────────────────────────────┘
```

## GitOps Implementation

The platform follows GitOps principles with some manual prerequisites:

### ✅ Fully Compliant
- Spark Operator deployment
- Nessie backup automation
- All manifests in Git
- Flux-managed deployments

### ⚠️ Manual Prerequisites
- S3 bucket creation
- 1Password secret setup
- Runtime JAR downloads
- Bootstrap coordination

See [`gitops-implementation.md`](./gitops-implementation.md) for detailed analysis and remediation steps.

## Quick Start

### Prerequisites
1. Kubernetes cluster with 96GB+ RAM
2. Ceph S3 storage operational
3. Flux GitOps configured
4. 1Password Connect deployed

### Check Status
```bash
# Review current bootstrap status
/project:data-platform-bootstrap-review

# Check component health
kubectl get all -n data-platform
kubectl get sparkapplication -n data-platform
```

### Execute Next Objective
```bash
# Continue bootstrap process
/project:data-platform-bootstrap-execute

# Execute specific objective
/project:data-platform-bootstrap-execute 2.2
```

## Resource Requirements

### Per Phase
- **Phase 1**: 8GB RAM, 400m CPU, 65GB storage
- **Phase 2**: 42GB RAM, 12 CPU cores, 120GB storage  
- **Phase 3**: 70GB RAM, 12 CPU cores, 250GB storage
- **Phase 4**: Reuses existing resources

### Total Platform
- **Memory**: 70GB (peak during Phase 3)
- **CPU**: 15 cores
- **Storage**: 500GB for data and metadata

## Key Components

### Nessie Catalog
- REST API on port 19120
- PostgreSQL metadata backend (CNPG)
- Git-like branching for data versioning
- Automated daily backups

### Spark Operator
- Kubeflow Spark Operator v2.2.0
- SparkApplication CRD management
- Supports Spark 3.5.5
- Prometheus metrics integration

### Storage Layer
- Ceph RADOS Gateway for S3 API
- Iceberg table format
- Parquet file storage
- Lifecycle policies for data retention

## Operations

### Backup and Recovery
See [`backup-procedures.md`](./backup-procedures.md) for:
- Daily automated backups
- Manual backup procedures
- Disaster recovery steps
- RTO: ~10 minutes, RPO: 24 hours

### Monitoring
- Prometheus metrics from all components
- Grafana dashboards (to be implemented)
- Health check endpoints
- Resource usage tracking

### Security
- RBAC configured per component
- Secrets managed via External Secrets Operator
- Network policies (to be implemented)
- Audit logging enabled

## Troubleshooting

### Common Issues

1. **Nessie Connection Failed**
   ```bash
   kubectl logs -n data-platform deployment/nessie
   kubectl describe pod -n data-platform -l app.kubernetes.io/name=nessie
   ```

2. **Spark Job Stuck**
   ```bash
   kubectl get sparkapplication -n data-platform
   kubectl describe sparkapplication -n data-platform <job-name>
   ```

3. **S3 Access Denied**
   ```bash
   kubectl get secret -n data-platform | grep s3
   kubectl get cephobjectstoreuser -n storage
   ```

## Next Steps

1. Complete Phase 2 objectives:
   - Deploy sample Spark applications
   - Test Iceberg read/write operations
   - Integrate with Airflow

2. Improve GitOps compliance:
   - Add ObjectBucketClaims for S3
   - Automate secret provisioning
   - Build custom Spark images

3. Begin Phase 3 planning:
   - Size Trino cluster appropriately
   - Plan query performance testing
   - Design monitoring dashboards

## Related Documentation

- [Homelab Overview](../../README.md)
- [Storage Documentation](../storage/)
- [Monitoring Stack](../monitoring/)
- [GitOps Patterns](../../kubernetes/)