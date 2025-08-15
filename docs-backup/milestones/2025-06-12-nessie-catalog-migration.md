# Milestone: Project Nessie Catalog Migration

**Date**: June 13, 2025  
**Status**: In Progress  
**Duration**: 2 hours (estimated)  
**Impact**: Major - Replacing Apache Polaris with Project Nessie for Iceberg catalog

## Overview

Following the discovery that Apache Polaris does not provide pre-built Docker images, the decision was made to migrate to Project Nessie as the catalog implementation for Apache Iceberg tables. Nessie provides immediate availability with production-ready images and adds Git-like versioning capabilities for data management.

## Motivation

The migration from Polaris to Nessie was triggered by:
1. **Image Availability**: Apache Polaris requires building from source; Nessie provides official Docker images
2. **Production Maturity**: Nessie is used in production by companies like Dremio
3. **Enhanced Features**: Git-like branching, tagging, and commits for data versioning
4. **Active Development**: Regular releases with comprehensive Kubernetes support

## Migration Decision

### Why Nessie Over Polaris

| Aspect | Apache Polaris | Project Nessie |
|--------|---------------|----------------|
| Docker Images | None (build from source) | Official images available |
| Maturity | Incubating (0.9.0) | Production-ready (0.104.1) |
| Versioning | Basic catalog | Git-like branches/tags |
| Kubernetes | Helm chart (no images) | Full Helm deployment |
| Backend | PostgreSQL | PostgreSQL + others |

### Key Advantages

1. **Immediate Deployment**: No build pipeline required
2. **Data Versioning**: Branch and merge data changes like code
3. **Time Travel**: Query data at any point in history
4. **Multi-table Transactions**: Atomic commits across tables
5. **Conflict Resolution**: Git-style merge capabilities

## Implementation Progress

### Phase 1: Cleanup (Completed)
- ✅ Removed all Polaris deployment files
- ✅ Removed Apache Polaris Helm repository
- ✅ Updated kustomizations to remove Polaris references
- ✅ Cleaned up documentation

### Phase 2: Nessie Deployment (In Progress)
- [ ] Create Nessie Helm repository configuration
- [ ] Configure PostgreSQL backend for Nessie
- [ ] Deploy Nessie HelmRelease
- [ ] Validate deployment

### Phase 3: Integration (Pending)
- [ ] Configure Spark/Flink connectors
- [ ] Create validation scripts
- [ ] Update documentation
- [ ] Test Git-like operations

## Technical Details

### Nessie Configuration
- **Version**: 0.104.1 (latest stable)
- **Backend**: PostgreSQL via CloudNativePG
- **Namespace**: data-platform
- **Port**: 19120 (REST API)
- **Authentication**: Disabled initially

### Resource Allocation
- Memory: 1Gi (request) / 2Gi (limit)
- CPU: 500m (request) / 1000m (limit)
- PostgreSQL: 3 instances for HA

## Lessons Learned

1. **Pre-built Images Matter**: Always verify image availability before selecting technology
2. **Feature Comparison**: Nessie's Git-like features provide significant value over basic catalogs
3. **Production Usage**: Prioritize solutions with proven production deployments
4. **Migration Simplicity**: Both Polaris and Nessie use similar REST APIs, easing future migrations

## Next Steps

1. Complete Nessie deployment configuration
2. Validate with test Iceberg tables
3. Document branching strategies for data management
4. Plan training on Git-like operations for data

## References

- [Project Nessie Documentation](https://projectnessie.org/)
- [Nessie Kubernetes Guide](https://projectnessie.org/guides/kubernetes/)
- [Original Polaris Decision](/docs/milestones/2025-06-12-polaris-catalog-decision.md)