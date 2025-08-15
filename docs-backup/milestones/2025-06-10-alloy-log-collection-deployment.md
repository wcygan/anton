# Milestone: Alloy Log Collection Deployment

**Date**: 2025-06-10  
**Category**: Monitoring  
**Status**: Completed

## Summary

Successfully deployed Grafana Alloy v1.9.1 as a DaemonSet to collect logs from all Kubernetes pods and forward them to Loki. This completes the core logging stack implementation, enabling centralized log collection across the entire cluster. After resolving multiple configuration issues, all three Alloy pods are now running successfully and actively collecting logs.

## Goals

- [x] Debug and fix Alloy CrashLoopBackOff errors
- [x] Deploy Alloy DaemonSet on all nodes
- [x] Configure log collection from Kubernetes pods
- [x] Establish connection to Loki for log forwarding
- [x] Implement label filtering to stay within Loki's limits
- [x] Validate end-to-end log flow

## Implementation Details

### Components Deployed
- Grafana Alloy v1.9.1 (DaemonSet mode)
- Alloy configuration for Kubernetes log discovery
- Log processing pipeline with JSON parsing
- Label filtering to reduce cardinality

### Configuration Changes
- Fixed component name from `loki.source.kubernetes_logs` to `loki.source.kubernetes`
- Removed unsupported `tail_from_end` attribute
- Removed Docker volume mounts (Talos uses containerd)
- Added `stage.label_drop` to remove excessive Kubernetes labels
- Fixed Kustomization dependency to reference correct namespace
- Configured Loki endpoint: `http://loki-gateway.monitoring.svc.cluster.local/loki/api/v1/push`

## Validation

### Tests Performed
- Integration test suite: All 4 tests passed
- Pod status check: All 3 Alloy pods running (2/2 containers ready)
- Log collection verification: Confirmed logs being collected from multiple namespaces
- Loki connectivity test: Verified logs being sent to Loki gateway
- Label count check: Loki now has 54 labels available (up from 3)

### Metrics
- Alloy pods: 3/3 running
- Container readiness: 6/6 ready
- Log streams opened: 50+ active streams
- Label limit errors: Resolved (was hitting 15-label limit)
- Integration test success rate: 100%

## Lessons Learned

### What Went Well
- Integration test suite provided immediate validation of fixes
- MCP server helped quickly identify component name changes in Alloy v1.9.1
- Incremental debugging approach (fix one issue at a time) was effective
- Git-based deployment via Flux allowed easy rollback and iteration

### Challenges
- **Component name change**: Alloy v1.9.1 uses `loki.source.kubernetes` instead of `loki.source.kubernetes_logs`
  - Resolution: Updated configuration after checking error logs
- **Label limit errors**: Loki's 15-label limit was exceeded by Kubernetes metadata
  - Resolution: Added `stage.label_drop` to remove non-essential labels
- **Helm chart stale state**: ConfigMap wasn't updating with new values
  - Resolution: Uninstalled and reinstalled Helm release completely
- **Volume mount issues**: Docker-specific mounts failed on Talos
  - Resolution: Removed `/var/lib/docker/containers` mount

## Next Steps

- Configure namespace filtering to reduce log volume (objective 3.2)
- Set up Grafana datasource for Loki to enable log queries
- Implement retention policies and log rotation
- Add ServiceMonitor for Alloy metrics collection
- Create dashboards for log ingestion monitoring
- Document common LogQL queries for team use

## References

- [Logging Stack Goals](/docs/logging-stack/bootstrap/03-goals.json)
- [Integration Test Suite](/tests/integration/logging-stack.test.ts)
- [Alloy HelmRelease](/kubernetes/apps/monitoring/alloy/app/helmrelease.yaml)
- Commits: 4ad247a, d029638, ec1ff52, 31f4715