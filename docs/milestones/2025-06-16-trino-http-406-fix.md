# Milestone: Trino HTTP 406 Fix

**Date**: 2025-06-16  
**Category**: Infrastructure  
**Status**: Completed

## Summary

Successfully resolved HTTP 406 "Server configuration does not allow processing of the X-Forwarded-For header" error in Trino web UI when accessed through Tailscale ingress. Implemented immediate fix via ConfigMap patch and documented comprehensive troubleshooting process for future reference.

## Goals

- [x] Diagnose HTTP 406 error preventing Trino web UI access
- [x] Implement immediate fix to restore web UI functionality
- [x] Document debugging process and solution
- [x] Plan long-term GitOps compliance approach
- [x] Verify Trino functionality and query execution

## Implementation Details

### Components Involved
- Trino v475 (Helm chart v1.39.1)
- Tailscale Kubernetes Operator
- Flux GitOps v2.5.1
- Kubernetes ingress with class `tailscale`

### Configuration Changes
- **Immediate Fix**: Direct ConfigMap patch to add `http-server.process-forwarded=true`
- **Pod Restart**: Coordinator pod restart to load new configuration
- **HelmRelease Suspension**: Suspended failing HelmRelease to prevent interference

### Root Cause Analysis
- **Security Feature**: Trino rejects X-Forwarded-* headers by default (introduced in recent versions)
- **Proxy Headers**: Tailscale ingress automatically injects forwarded headers for client identification
- **Configuration Gap**: Missing `http-server.process-forwarded=true` setting to allow trusted proxy headers

## Validation

### Tests Performed
- **Web UI Access**: ✅ https://trino.walleye-monster.ts.net loads without 406 error
- **Query Execution**: ✅ Basic SQL queries work through CLI (`SELECT 1`, `SHOW CATALOGS`)
- **Catalog Access**: ✅ TPCH benchmark data accessible (`tpch.tiny.*` tables)
- **Pod Health**: ✅ Coordinator pod running stable with new configuration
- **Ingress Status**: ✅ Tailscale ingress operational (`ts-trino-lmf87-0` pod running)

### Metrics
- **Resolution Time**: ~3 hours of debugging + 15 minutes for fix implementation
- **Downtime**: 0 (CLI access remained functional throughout)
- **Configuration Attempts**: 4 failed Helm chart attempts before direct patch solution
- **Documentation**: 306 lines of comprehensive troubleshooting guide created

## Lessons Learned

### What Went Well
- **Systematic Debugging**: Step-by-step analysis of network path, configuration, and deployment pipeline
- **Multiple Approaches**: Tried various configuration methods to understand chart behavior
- **Immediate Recovery**: Direct ConfigMap patch provided instant resolution
- **Documentation**: Created comprehensive guide for future troubleshooting

### Challenges
- **Helm Chart Complexity**: `additionalConfigProperties` parsing issues in Trino chart
- **YAML Syntax Sensitivity**: Even correct YAML was parsed incorrectly due to indentation/type issues
- **GitOps vs. Emergency**: Manual intervention needed outside GitOps workflow for immediate fix
- **Configuration Discovery**: Finding correct property name required deep documentation research

### Technical Insights
- **Security by Default**: Modern applications increasingly reject proxy headers for security
- **Proxy Trust Requirements**: Services behind ingress/load balancers need explicit forwarded header trust
- **Helm Template Behavior**: Chart templates can be sensitive to exact data types (array vs object)
- **Flux YAML Processing**: Complex nested configurations may not parse as expected

## Next Steps

### Phase 2: GitOps Compliance (Planned)
- [ ] Research correct Helm chart configuration syntax for `additionalConfigProperties`
- [ ] Test alternative configuration methods (`coordinator.additionalConfigFiles`)
- [ ] Update HelmRelease with permanent GitOps-compliant solution
- [ ] Resume HelmRelease and validate deployment success

### Operational Improvements
- [ ] Add Kubernetes NetworkPolicies to restrict Trino ingress traffic
- [ ] Monitor Trino logs for suspicious X-Forwarded-For values
- [ ] Document Tailscale ingress patterns for other services
- [ ] Create pre-commit validation for Helm chart configurations

### Iceberg Integration Testing
- [ ] Test Iceberg table creation and querying capabilities
- [ ] Validate S3 connectivity through Rook-Ceph RADOS Gateway
- [ ] Verify Nessie catalog integration for metadata management

## References

- [Comprehensive Troubleshooting Guide](../troubleshooting/trino-http-406-fix.md)
- [Trino HTTP Server Properties Documentation](https://trino.io/docs/current/admin/properties-http-server.html)
- [GitHub Issue #6552: Reject X-Forwarded-* headers by default](https://github.com/trinodb/trino/issues/6552)
- [Tailscale Kubernetes Operator Documentation](https://tailscale.com/kb/1439/kubernetes-operator-cluster-ingress)
- [Trino Helm Chart Repository](https://github.com/trinodb/charts)
- [Commit: f2b2375 - Documentation](https://github.com/wcygan/homelab/commit/f2b2375)
- [Commit: a21fa8f - Final Configuration Fix](https://github.com/wcygan/homelab/commit/a21fa8f)