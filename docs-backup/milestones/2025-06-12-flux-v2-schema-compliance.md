# Milestone: Flux v2 Schema Compliance

**Date**: 2025-06-12  
**Category**: Infrastructure  
**Status**: Planned

## Summary

Address Flux v2 schema compliance issues by removing deprecated fields and ensuring all GitOps resources follow current API specifications.

## Goals

- [ ] Remove deprecated `retryInterval` fields from all Flux resources
- [ ] Validate all Kustomization and HelmRelease schemas
- [ ] Update dependency configurations to use correct namespaces
- [ ] Ensure health check configurations are properly specified
- [ ] Add missing `wait: true` configurations where needed
- [ ] Standardize interval and timeout configurations

## Implementation Details

### Components to Fix
- kubernetes/flux/cluster/ks.yaml (2 retryInterval instances)
- kubernetes/apps/cert-manager/cert-manager/ks.yaml (2 retryInterval instances)
- kubernetes/apps/network/internal/ks.yaml (retryInterval instance)
- kubernetes/apps/network/external/ks.yaml (retryInterval instance)
- 24 Kustomizations missing health checks
- 5 kubeai model Kustomizations missing `wait: true`

### Configuration Changes
- Remove all `retryInterval` field references
- Add missing `wait: true` for critical dependencies
- Standardize `timeout` configurations (15m for most apps)
- Verify dependency namespace references are correct
- Add health checks for missing Kustomizations

## Validation

### Tests Performed
- Flux schema validation with `flux check`
- Manifest validation with kubectl dry-run
- Dependency resolution verification
- GitOps reconciliation testing

### Metrics
- Schema violations: Fix 9 identified files
- Health check coverage: Add to 24 Kustomizations
- Wait configuration: Add to 5 kubeai models
- Validation success: 100% schema compliance

## Lessons Learned

### What Went Well
- Current validation scripts catch most issues
- GitOps structure supports incremental fixes
- Flux v2 provides clear schema documentation

### Challenges
- Identifying all deprecated field usage
- Understanding correct dependency configurations
- Coordinating changes across multiple files

## Next Steps

- Phase 1: Remove deprecated retryInterval fields (immediate)
- Phase 2: Add missing health checks and wait configurations
- Phase 3: Standardize timeout and interval settings
- Phase 4: Implement automated schema validation in CI

## References

- [Flux v2 API Changes](https://fluxcd.io/flux/migration/flux-v2-data-migration/)
- [Current schema violations](../investigations/2025-06-12-refactoring-analysis.md)
- [Flux schema documentation](https://fluxcd.io/flux/components/)