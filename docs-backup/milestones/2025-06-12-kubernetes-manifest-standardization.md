# Milestone: Kubernetes Manifest Standardization

**Date**: 2025-06-12  
**Category**: Infrastructure  
**Status**: Planned

## Summary

Standardize Kubernetes manifests across 212 YAML files to improve consistency, eliminate deprecated configurations, and create reusable component templates for common patterns.

## Goals

- [ ] Remove deprecated `retryInterval` fields from Flux v2 resources
- [ ] Standardize HelmRelease configurations (retries, timeouts, cleanup)
- [ ] Create resource tier templates for consistent limits/requests
- [ ] Establish security context standards across all workloads
- [ ] Build reusable Kustomize components for common patterns
- [ ] Standardize health check configurations

## Implementation Details

### Components to Standardize
- HelmRelease patterns (29+ releases with varied configurations)
- Kustomization configurations (inconsistent intervals and health checks)
- Resource limits/requests (2 missing, 4 incomplete configurations)
- Security contexts (pod security standards adoption)
- Monitoring integration (ServiceMonitor patterns)

### Configuration Changes
- Fix Flux v2 schema violations in 9 files
- Create kubernetes/components/ structure for networking, storage, monitoring
- Implement resource tier system (small/medium/large)
- Standardize ingress class usage (internal vs external)
- Centralize storage class configurations

## Validation

### Tests Performed
- Manifest validation with kubectl dry-run
- Flux schema validation
- Resource limit analysis
- Security policy compliance checks

### Metrics
- Deprecated field removal: 9 files to fix
- Resource standardization: 29+ HelmReleases to update
- Component creation: Target 6-8 reusable components
- Security context coverage: Target 100% of workloads

## Lessons Learned

### What Went Well
- Current GitOps structure provides excellent foundation
- Validation scripts catch schema issues effectively
- Namespace organization follows good practices

### Challenges
- Balancing standardization with app-specific requirements
- Managing dependencies during component migration
- Ensuring backward compatibility with existing deployments

## Next Steps

- Phase 1: Fix Flux v2 schema violations immediately
- Phase 2: Create resource tier templates and security standards
- Phase 3: Build reusable Kustomize components
- Phase 4: Migrate applications to standardized patterns

## References

- [Flux v2 API Reference](https://fluxcd.io/flux/components/)
- [Kustomize Components Guide](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/#components)
- [Current manifest analysis](../investigations/2025-06-12-refactoring-analysis.md)