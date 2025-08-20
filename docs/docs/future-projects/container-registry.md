# Container Registry with Harbor

## Overview

Deploy [Harbor](https://goharbor.io/docs/2.0.0/install-config/harbor-ha-helm/) as an enterprise-grade container registry to replace the basic Docker registry, leveraging existing CloudNative PostgreSQL and Dragonfly operators.

## Architecture

### Components
- **Harbor Core**: Registry services with RBAC, vulnerability scanning, and replication
- **Database**: CloudNative PostgreSQL cluster with 4 databases (core, clair, notary-server, notary-signer)
- **Cache**: Dragonfly instance (Redis-compatible, 25x better performance)
- **Storage**: Ceph S3 (RGW) for artifact storage
- **Ingress**: Internal NGINX with TLS certificates

### Resource Requirements
- **CPU**: 2-4 cores total across components
- **Memory**: 2-4GB RAM
- **Storage**: 100GB+ for artifacts (5.4TB available in Ceph)

## Benefits

### Enterprise Features
- **Security**: Vulnerability scanning with Trivy/Clair
- **Trust**: Image signing and content trust
- **Replication**: Multi-registry synchronization
- **RBAC**: Project-based access control
- **Retention**: Automated cleanup policies
- **Helm Charts**: Built-in chart repository

### Operational Advantages
- GitOps deployment via Flux
- External Secrets integration with 1Password
- High availability support
- Production-grade monitoring
- Replaces problematic docker-registry deployment

## Implementation Plan

### Phase 1: Infrastructure Preparation
```yaml
# Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: harbor
```

### Phase 2: Database Setup
Deploy CloudNative PostgreSQL cluster:
- 4 separate databases required
- Use existing CNPG operator in `cnpg-system`
- Configure with Ceph block storage
- Enable backups to S3

### Phase 3: Cache Layer
Deploy Dragonfly instance:
- Single replica for "single entry point" requirement
- 512Mi memory allocation
- Persistent volume for snapshots

### Phase 4: Harbor Deployment
```bash
# Bitnami Harbor Chart
helm repo add bitnami https://charts.bitnami.com/bitnami
helm search repo bitnami/harbor --versions

# Latest: v27.0.3 (Harbor 2.13.2)
```

Key configuration:
- External PostgreSQL and Redis
- Ceph S3 for storage backend
- Internal ingress with TLS
- 1Password for secrets

### Phase 5: Migration
1. Export images from existing registry
2. Import to Harbor with proper projects
3. Update all deployments to use Harbor
4. Decommission old docker-registry

## Configuration Highlights

### Storage Backend
```yaml
persistence:
  persistentVolumeClaim:
    registry:
      storageClass: ceph-block
  imageChartStorage:
    type: s3
    s3:
      region: us-east-1
      bucket: harbor-registry
      encrypt: true
```

### High Availability
```yaml
replicas:
  portal: 2
  core: 2
  jobservice: 2
  registry: 2
```

### External Services
```yaml
database:
  type: external
  external:
    host: harbor-postgres-rw.harbor.svc
    port: 5432
redis:
  type: external
  external:
    addr: harbor-dragonfly.harbor.svc:6379
```

## Monitoring & Maintenance

### Metrics
- Prometheus ServiceMonitor for all components
- Custom Grafana dashboard for registry metrics
- Alert rules for:
  - Storage capacity
  - Replication failures
  - Vulnerability scan backlogs
  - Authentication failures

### Backup Strategy
- PostgreSQL: Daily backups via CNPG to Ceph S3
- Configuration: GitOps versioned in Git
- Artifacts: Ceph replication (3-way)

## Security Considerations

- Enable vulnerability scanning by default
- Configure image signing policies
- Implement quota limits per project
- Enable audit logging
- Regular security updates via Flux

## Cost-Benefit Analysis

### Pros
- Enterprise features justify complexity
- Leverages existing operators (no new dependencies)
- Excellent Ceph storage integration
- Production-ready with HA support

### Cons
- Higher resource consumption than basic registry
- More complex backup requirements
- Additional monitoring overhead
- Potential Dragonfly compatibility risks (mitigated by Redis compatibility)

## Decision

**Recommended**: Harbor provides significant value over basic Docker registry, especially for security scanning, RBAC, and Helm chart hosting. The existing infrastructure (CNPG, Dragonfly, Ceph) makes deployment straightforward.

## References

- [Harbor HA Helm Deployment](https://goharbor.io/docs/2.0.0/install-config/harbor-ha-helm/)
- [CloudNative PG Documentation](https://cloudnative-pg.io/)
- [Dragonfly Database](https://www.dragonflydb.io/)
- [Bitnami Harbor Chart](https://github.com/bitnami/charts/tree/main/bitnami/harbor)