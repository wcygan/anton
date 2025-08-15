# Milestone: Cluster Recovery to Operational Excellence

**Date**: 2025-06-12  
**Category**: Infrastructure  
**Status**: In Progress

## Summary

Recovery from catastrophic cluster-apps kustomization deletion that terminated ~80 pods. This milestone tracks the complete restoration of the Anton Kubernetes cluster from 23 pods back to full operational capacity (~100+ pods), including all critical services, monitoring, and data platform components.

## Goals

- [x] Execute emergency bootstrap recovery via `task bootstrap:apps`
- [ ] Restore all Flux-managed applications to healthy state
- [ ] Verify all storage (Rook-Ceph) resources are operational
- [ ] Restore complete monitoring stack (Prometheus, Grafana, Loki)
- [ ] Restore data platform services (Airflow, Nessie, Hive Metastore)
- [ ] Validate all ingress routes and external access
- [ ] Document recovery procedures and lessons learned
- [ ] Implement safeguards to prevent future incidents

## Recovery Options

### Option 1: Continue Current Bootstrap Recovery (CHOSEN)
- **Status**: In progress - pod count increased from 23 to 33
- **Approach**: Let `task bootstrap:apps` complete, then monitor cluster-apps reconciliation
- **Pros**: Follows established recovery procedures, maintains GitOps state
- **Cons**: Slower recovery time, requires patience

### Option 2: Manual Resource Recreation
- **Approach**: Manually apply critical resources outside of Flux
- **Pros**: Faster initial recovery
- **Cons**: Breaks GitOps model, requires manual sync later

### Option 3: Restore from Backup
- **Approach**: Restore etcd snapshot or use Velero backups
- **Pros**: Point-in-time recovery
- **Cons**: May lose recent changes, requires backup availability

## Implementation Details

### Phase 1: Emergency Bootstrap (COMPLETED)
- Executed `task bootstrap:apps` at 2025-06-12
- Applied critical namespaces
- Created SOPS age secret for secret decryption
- Deployed core infrastructure via helmfile:
  - Cilium CNI
  - CoreDNS
  - Cert-Manager
  - Flux controllers

### Phase 2: Flux Reconciliation (IN PROGRESS)
- cluster-apps kustomization recreated and syncing
- Monitoring reconciliation of all app kustomizations
- Current status: 33/100+ pods recovered

### Phase 3: Service Verification (PENDING)
- Storage cluster health check
- Monitoring stack validation
- Data platform services restoration
- Ingress and DNS verification

## Validation

### Tests to Perform
- [ ] Flux health check: `flux check`
- [ ] All kustomizations ready: `flux get ks -A | grep -v True`
- [ ] All HelmReleases deployed: `flux get hr -A | grep -v True`
- [ ] Storage health: `./scripts/storage-health-check.ts`
- [ ] Network connectivity: `./scripts/network-monitor.ts`
- [ ] Monitoring operational: `./scripts/test-all.ts`

### Recovery Metrics
- Initial pod count: 100+
- Post-incident pod count: 23
- Current pod count: 33
- Target pod count: 100+
- Recovery time estimate: 2-4 hours

## Incident Analysis

### Root Cause
Attempted to fix duplicate `targetNamespace` field in airflow/ks.yaml by using kubectl delete on cluster-apps kustomization, triggering cascade deletion of all Flux-managed resources.

### Contributing Factors
1. Insufficient understanding of Flux resource ownership chains
2. Using delete instead of suspend/resume for debugging
3. Not checking dependencies before deletion
4. Lack of confirmation prompt for critical operations

## Lessons Learned

### What Went Well
- Bootstrap recovery procedure worked as designed
- SOPS secrets remained intact
- Core cluster functionality (nodes, etcd) unaffected
- Git repository preserved complete desired state

### Challenges
- Recovery slower than expected due to dependency chains
- Some resources stuck in terminating state
- Reconciliation order causing temporary failures

## Safeguards Implemented

1. **Golden Rules Documentation**: Created `/docs/golden-rules/` with critical safety rules
2. **CLAUDE.md Updates**: Added prominent warnings about deletion operations
3. **Local Settings**: Added deny rule for `kubectl delete kustomization cluster-apps`
4. **Recovery Procedures**: Documented in golden rules for future incidents

## Next Steps

1. **Immediate**:
   - Monitor cluster-apps reconciliation completion
   - Verify each namespace recovers its resources
   - Check for any stuck/failing resources

2. **Short-term**:
   - Run comprehensive health checks once recovery completes
   - Validate all data persistence (databases, storage)
   - Test all user-facing services

3. **Long-term**:
   - Implement Velero for cluster backups
   - Add pre-deletion webhooks for critical resources
   - Create automated recovery testing procedures
   - Regular disaster recovery drills

## Recovery Commands Reference

```bash
# Monitor recovery progress
watch kubectl get pods -A | wc -l
flux get ks -A
flux get hr -A

# Check specific namespaces
kubectl get all -n storage
kubectl get all -n monitoring
kubectl get all -n data-platform

# Force reconciliation if needed
flux reconcile kustomization cluster-apps --with-source

# Check for stuck resources
kubectl get pods -A | grep -E 'Terminating|Error|CrashLoop'
```

## Success Criteria

The cluster will be considered fully recovered when:
1. Pod count returns to 100+ stable pods
2. All Flux resources show Ready=True
3. Storage cluster reports HEALTH_OK
4. All ingress routes accessible
5. Monitoring dashboards operational
6. No pods in error states
7. All tests in `./scripts/test-all.ts` pass

## References

- [Flux Disaster Recovery Docs](https://fluxcd.io/flux/guides/disaster-recovery/)
- [Task Bootstrap Implementation](../../Taskfile.yaml#L140-L160)
- [Golden Rules Documentation](../golden-rules/README.md)
- [Original Incident PR](https://github.com/wcygan/homelab/pull/XXX)