# Milestone: Renovate Pipeline Health & Flux API Migration

**Date**: 2025-06-11  
**Status**: In Progress  
**Lead**: wcygan  
**Priority**: High  

## Overview

This milestone addresses critical issues in the Renovate automated dependency update pipeline caused by Flux API version incompatibilities. The work involves coordinating updates to the Flux ecosystem components to enable modern API versions while maintaining cluster stability.

## Background

The homelab cluster's Renovate bot has been creating dependency update PRs, but 9 out of 18 PRs are failing due to API version compatibility issues:

- **Current State**: Flux 2.5.1 with operator 0.20.0 (supports only `source.toolkit.fluxcd.io/v1beta2`)
- **Target State**: Flux 2.6.1 with operator 0.22.0 (supports both `v1beta2` and `v1` APIs)
- **Root Cause**: PR #34 attempts to migrate OCIRepository resources to `v1` API before cluster supports it

## Objectives

### Primary Goals

1. **Restore Renovate Pipeline Health**
   - Fix all 9 failing Renovate PRs
   - Enable automated dependency updates to flow through CI/CD
   - Prevent future API compatibility issues

2. **Complete Flux API Migration**
   - Update Flux distribution from 2.5.1 → 2.6.1
   - Update Flux operator from 0.20.0 → 0.22.0
   - Migrate OCIRepository resources from `v1beta2` → `v1` API
   - Update yaml-language-server schema references

3. **Maintain Zero Downtime**
   - Coordinate updates to avoid service disruption
   - Validate each step before proceeding
   - Have rollback plan ready

### Secondary Goals

1. **Process Improvement**
   - Document migration patterns for future API changes
   - Improve CI checks to catch API compatibility issues earlier
   - Establish coordination protocols for breaking changes

## Implementation Strategy

### Phase 1: Assessment & Preparation ✅

- [x] Analyzed all 18 Renovate PRs and identified status
- [x] Successfully merged 8 safe PRs (tooling updates)
- [x] Identified root cause: API version incompatibility
- [x] Documented interdependencies between failing PRs

### Phase 2: Critical Flux Updates 🔄

**Coordinated Update Sequence:**

1. **PR #30**: Update Flux distribution (2.5.1 → 2.6.1)
   - Adds support for `source.toolkit.fluxcd.io/v1` API
   - Maintains backward compatibility with `v1beta2`

2. **PR #22**: Update Flux operator (0.20.0 → 0.22.0)
   - Must be coordinated with distribution update
   - Ensures operator and distribution versions are compatible

3. **PR #34**: Migrate OCIRepository API (v1beta2 → v1)
   - Can only proceed after cluster supports v1 API
   - Updates yaml-language-server schema references

**Risk Mitigation:**
- Test each update in isolation where possible
- Monitor cluster health between updates
- Have `flux suspend` commands ready for rollback

### Phase 3: Downstream Updates

**Once Flux ecosystem is updated:**

4. **Infrastructure PRs** (should auto-pass after rebase):
   - PR #38: node-problem-detector (v0.8.19 → v0.8.21)
   - PR #36: spegel (0.2.0 → 0.3.0)  
   - PR #35: ingress-nginx (4.12.2 → 4.12.3)
   - PR #17: coredns (1.42.1 → 1.42.3)

5. **Major Version Updates** (require careful review):
   - PR #37: kube-prometheus-stack (72.9.1 → 73.2.0) ⚠️ MAJOR
   - PR #15: http-https-echo (36 → 37) ⚠️ MAJOR

6. **Remaining Conflict Resolution**:
   - PR #27: helm CLI (3.17.3 → 3.18.2) - needs rebase

## Technical Details

### Current Cluster State

```yaml
# Flux Distribution: 2.5.1
# Flux Operator: 0.20.0
# Supported APIs:
- source.toolkit.fluxcd.io/v1beta2 ✅
- source.toolkit.fluxcd.io/v1 ❌
```

### Target State

```yaml
# Flux Distribution: 2.6.1
# Flux Operator: 0.22.0
# Supported APIs:
- source.toolkit.fluxcd.io/v1beta2 ✅ (deprecated)
- source.toolkit.fluxcd.io/v1 ✅ (preferred)
```

### API Migration Pattern

```yaml
# BEFORE (v1beta2)
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: example

# AFTER (v1)
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: example
```

## Validation Criteria

### Phase 2 Success Criteria

- [ ] Flux distribution updated to 2.6.1
- [ ] Flux operator updated to 0.22.0
- [ ] All Flux controllers healthy and ready
- [ ] GitOps reconciliation functioning normally
- [ ] `kubectl api-resources | grep source.toolkit.fluxcd.io/v1` shows both APIs

### Phase 3 Success Criteria

- [ ] All OCIRepository resources using `v1` API
- [ ] All failing PRs pass CI checks after rebase
- [ ] No breaking changes in major version updates
- [ ] Cluster maintains full functionality

### Overall Success Criteria

- [ ] All 18 Renovate PRs resolved (merged or closed)
- [ ] Renovate creating new PRs without CI failures
- [ ] Zero service downtime during migration
- [ ] Documentation updated with lessons learned

## Monitoring & Observability

### Key Metrics

- **Flux Controller Health**: All controllers Ready and not restarting
- **GitOps Sync Status**: All Kustomizations and HelmReleases reconciled
- **API Availability**: Both v1beta2 and v1 APIs responding
- **Service Availability**: All critical services remain accessible

### Monitoring Commands

```bash
# Flux health check
flux check
flux get all -A

# API availability
kubectl api-resources | grep source.toolkit.fluxcd.io

# Controller status
kubectl get pods -n flux-system

# Reconciliation status
kubectl get kustomization -A
kubectl get helmrelease -A
```

## Risk Assessment

### High Risk Items

1. **Flux Controller Disruption**
   - Risk: Controllers fail to start with new versions
   - Mitigation: Stage updates, monitor between phases
   - Rollback: Revert to previous Flux versions

2. **API Incompatibility**
   - Risk: Resources fail to reconcile with new APIs
   - Mitigation: Test v1 API before migrating all resources
   - Rollback: Revert OCIRepository resources to v1beta2

3. **Major Version Breaking Changes**
   - Risk: kube-prometheus-stack 73.x introduces breaking changes
   - Mitigation: Review changelog before merging PR #37
   - Rollback: Pin to previous version if issues arise

### Medium Risk Items

1. **Renovate PR Conflicts**
   - Multiple PRs may need rebasing after Flux updates
   - May require manual intervention for complex conflicts

2. **Timing Dependencies**
   - Updates must be applied in specific order
   - Parallel updates could cause race conditions

## Lessons Learned (Post-Implementation)

_To be filled after completion_

### What Went Well

### Challenges Encountered

### Process Improvements

### Technical Insights

## Dependencies

### Internal Dependencies

- Cluster must be healthy before starting
- All critical workloads should be stable
- Backup/disaster recovery procedures verified

### External Dependencies

- GitHub API (for PR management)
- Flux release artifacts availability
- OCI registry accessibility for chart fetching

## Communication Plan

### Stakeholders

- **Primary**: wcygan (cluster operator)
- **Secondary**: Renovate bot (automated dependency updates)

### Status Updates

- Document progress in this milestone
- Update CLAUDE.md with any new patterns discovered
- Create follow-up tasks for process improvements

## Next Steps (Post-Milestone)

1. **Process Documentation**
   - Document API migration patterns in `/docs`
   - Update CI/CD workflows to catch similar issues
   - Create runbook for Flux ecosystem updates

2. **Automation Improvements**
   - Investigate Renovate grouping for coordinated updates
   - Add pre-merge checks for API compatibility
   - Consider staging environment for major updates

3. **Monitoring Enhancements**
   - Add alerts for Flux controller health
   - Monitor Renovate PR success rates
   - Dashboard for GitOps reconciliation status

---

**Last Updated**: 2025-06-11  
**Next Review**: 2025-06-12 (daily until completion)