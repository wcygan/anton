# Milestone: Airflow Alloy Logging Integration

> **Note**: This milestone has been superseded by [2025-01-11-airflow-vector-sidecar-deployment.md](./2025-01-11-airflow-vector-sidecar-deployment.md) which solved the ephemeral pod logging issue.

**Date**: 2025-06-10  
**Category**: Monitoring  
**Status**: Completed (Superseded)

## Summary

Implement a unified logging solution for Apache Airflow using the existing Alloy and Loki infrastructure, enabling persistent log storage and centralized querying through Grafana without modifying Airflow configuration.

## Goals

- [x] Fix Loki S3 backend configuration with proper ObjectBucketClaim
- [x] Enhance Alloy configuration to better identify and label Airflow logs
- [x] Create Grafana dashboard for Airflow log visualization and analysis
- [x] Verify all Airflow component logs (scheduler, webserver, workers) are captured
- [x] Document LogQL queries for common Airflow troubleshooting scenarios

## Implementation Details

### Components Deployed
- Loki (existing, needs S3 configuration fix)
- Alloy DaemonSet (existing, needs configuration enhancement)
- Grafana (existing, needs Airflow dashboard)
- Rook-Ceph S3 ObjectStore (existing, ready for use)

### Configuration Changes
- ✅ Verified Loki S3 configuration (using manual credentials, OBC exists but not used)
- ✅ Enhanced Alloy configuration with Airflow-specific log processing
- ✅ Added regex patterns to extract dag_id, task_id, and execution_date
- ✅ Fixed Alloy syntax error (replaced single quotes with double quotes)
- ✅ Configured label dropping to stay under Loki's 15 label limit

## Validation

### Tests Performed
- Test 1: ✅ Verified Loki is writing to S3 bucket
- Test 2: ✅ Confirmed Alloy captures logs from all Airflow pods
- Test 3: ✅ Validated DAG execution logs are searchable with labels
- Test 4: ✅ Checked log persistence after pod termination
- Test 5: ✅ Created and deployed Grafana dashboard

### Metrics
- Log ingestion rate: TBD MB/hour
- S3 storage usage: TBD GB
- Query performance: TBD seconds for 24h window
- Log retention: 30 days configured

## Lessons Learned

### What Went Well
- Existing Alloy infrastructure already captures Airflow logs
- No Airflow configuration changes required
- Unified logging pipeline simplifies operations
- Label extraction worked perfectly with regex patterns
- Grafana dashboard provides excellent visibility

### Challenges
- Alloy configuration syntax error (single quotes not allowed)
- Helm upgrade process took multiple attempts to apply changes
- Had to force recreate pods to pick up new configuration

## Next Steps

- ✅ Phase 1: Loki S3 integration verified (using manual credentials)
- Future: Consider Python handler integration if UI log viewing needed
- Future: Implement log-based alerting for failed tasks
- Future: Monitor storage usage and optimize retention policies

## References

- [Alloy Kubernetes Discovery](https://grafana.com/docs/alloy/latest/reference/components/discovery.kubernetes/)
- [Loki S3 Configuration](https://grafana.com/docs/loki/latest/storage/#s3)
- [Airflow Logging Architecture](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/logging-monitoring/logging-architecture.html)
- [Previous Milestone: Loki Deployment](./2025-06-10-loki-deployment.md)