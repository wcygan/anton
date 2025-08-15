# Milestone: Loki Deployment

**Date**: 2025-06-10  
**Category**: Monitoring  
**Status**: In Progress

## Summary

Successfully deployed Grafana Loki v6.30.1 in SingleBinary mode with S3 backend storage using Ceph ObjectStore. This deployment establishes the foundation for centralized logging infrastructure, replacing file-based logging with a scalable, queryable solution. Alloy deployment remains in progress due to Helm chart compatibility issues.

## Goals

- [x] Deploy Loki with S3 backend for centralized log storage
- [x] Configure Ceph ObjectStore integration with proper credentials
- [ ] Deploy Alloy DaemonSet for log collection across all nodes
- [ ] Integrate with Grafana for log visualization and querying
- [ ] Migrate Airflow logging from PVC to centralized solution

## Implementation Details

### Components Deployed
- Grafana Loki v6.30.1 (SingleBinary mode)
- Loki Gateway (nginx-based API gateway)
- Ceph S3 ObjectBucketClaim for log storage
- External Secrets configuration for S3 credentials

### Configuration Changes
- Created new namespace structure: `kubernetes/apps/monitoring/loki/`
- Configured S3 backend with Ceph RGW endpoint
- Set 30-day retention policy (720h)
- Enabled pattern ingester for improved performance
- Disabled caching layers initially for simplicity
- Configured resource limits (1 CPU, 1Gi memory)

## Validation

### Tests Performed
- Flux reconciliation: All Loki resources successfully deployed
- Pod status check: loki-0 and loki-gateway running
- S3 connectivity: Verified through pod startup (no S3 errors in logs)
- API accessibility: Gateway service responding on cluster network

### Metrics
- Deployment time: ~4 hours (including troubleshooting)
- Storage allocated: 10Gi PVC for WAL + S3 for long-term storage
- Resource usage: 100m CPU request, 256Mi memory request
- Retention period: 30 days configured

## Lessons Learned

### What Went Well
- MCP server integration proved valuable for documentation research
- S3 backend configuration worked on first attempt after proper research
- External Secrets integration simplified credential management
- SingleBinary mode provided simpler initial deployment path

### Challenges
- **Loki v6.23.0 template error**: Field `enforce_metric_name` not found in schema
  - Resolution: Upgraded to v6.30.1 after researching with Context7 MCP
- **Initial reactive approach**: Trial-and-error wasted time
  - Resolution: Shifted to research-first approach using MCP servers
- **Alloy v1.1.1 Helm chart errors**: Volume configuration template issues
  - Resolution: Still pending - needs further investigation with upstream chart
- **Incomplete validation**: Deployed Loki but didn't verify it's actually working
  - Learning: Always validate each component before adding complexity

## Next Steps

### Priority 1: Validate Loki Deployment (Before Alloy)
- **Configure Loki datasource in Grafana** for log visualization
- **Deploy test workload** to verify log ingestion works without Alloy
- **Verify S3 storage** is actually receiving logs (check bucket contents)
- **Enable ServiceMonitor** in Loki HelmRelease for metrics collection
- **Import Loki dashboards** to track ingestion rate and performance

### Priority 2: Research Alloy Properly
- Use Context7 MCP: `/mcp context7:get-library-docs /grafana/alloy "helm chart volumes" 5000`
- Check if newer Alloy versions (>1.1.1) fix the volume configuration issue
- Consider fallback option: Promtail if Alloy remains problematic
- Review Alloy GitHub issues for known Helm chart problems

### Priority 3: Complete Integration
- Deploy Alloy DaemonSet once configuration is resolved
- Set up alerts for log ingestion failures
- Plan Airflow migration strategy from PVC to Loki
- Document common LogQL queries for team use

**Recommendation**: A working Loki with manual log verification is better than rushing both components. Validate Loki thoroughly before attempting Alloy integration again.

## References

- [Logging Stack Documentation](/docs/logging-stack/README.md)
- [Implementation Guide](/docs/logging-stack/bootstrap/02-implementation-guide.md)
- [Goals Tracking](/docs/logging-stack/bootstrap/03-goals.json)
- Flux GitOps changes: kubernetes/apps/monitoring/{loki,alloy}/
- Related issue: Airflow PVC usage exceeded 80Gi threshold