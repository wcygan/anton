# Anton Homelab Capacity Review Report
Date: June 27, 2025

## Executive Summary

The Anton homelab cluster shows healthy utilization levels with significant room for growth. Current resource usage is well within safe operating limits, but several areas require attention for optimal performance and future scalability.

### Key Findings
- **CPU**: Low utilization (2-11%) with ample headroom
- **Memory**: Low-moderate utilization (9-11%) across nodes
- **Storage**: Minimal usage (0.54% of 5.5TB raw capacity) 
- **Active Issues**: Several failing deployments affecting monitoring and data platform

## Current Capacity Status

### Compute Resources
| Node   | CPU Cores | CPU Used | CPU % | Memory Total | Memory Used | Memory % |
|--------|-----------|----------|-------|--------------|-------------|----------|
| k8s-1  | 20        | 2.3      | 11%   | 96.1 GB      | 11.1 GB     | 11%      |
| k8s-2  | 20        | 1.1      | 5%    | 96.1 GB      | 10.4 GB     | 11%      |
| k8s-3  | 20        | 0.5      | 2%    | 96.1 GB      | 9.1 GB      | 9%       |
| **Total** | **60** | **3.9**  | **6.5%** | **288.3 GB** | **30.6 GB** | **10.6%** |

### Storage Capacity (Ceph)
- **Raw Capacity**: 5.5 TiB
- **Usable Capacity**: ~1.8 TiB (with 3x replication)
- **Current Usage**: 30 GB (0.54%)
- **Available**: 5.4 TiB raw / 1.7 TiB usable
- **Primary Pool**: replicapool - 29 GB used

### Resource Allocation vs Actual Usage

#### Node k8s-1 (Most Loaded)
- **CPU**: 13.9 cores requested (69%) vs 2.3 cores actual (11%)
- **Memory**: 54.9 GB requested (57%) vs 11.1 GB actual (11%)
- **Pod Count**: 41 of 110 capacity

This shows significant over-provisioning of resources, which is good for burst capacity but may lead to resource waste.

## Workload Analysis

### Top Resource Consumers
1. **Trino Worker** (data-platform)
   - CPU: 4 cores requested, 6 core limit
   - Memory: 24GB requested, 28GB limit
   
2. **Trino Coordinator** (data-platform)
   - CPU: 2 cores requested, 4 core limit
   - Memory: 8GB requested, 10GB limit

3. **Prometheus** (monitoring)
   - CPU: 0.5 cores requested, 2 core limit
   - Memory: 2GB requested, 4GB limit

### Namespace Resource Distribution
- **data-platform**: Highest resource allocation (Trino, Nessie)
- **storage**: Ceph components distributed across all nodes
- **monitoring**: Moderate usage (Prometheus, Grafana)
- **airflow**: Light usage (webserver only)

## Current Issues Affecting Capacity

### Critical Issues
1. **Multiple HelmRelease Failures**
   - Loki deployment failing (GrafanaAgent CRD missing)
   - Nessie deployment issues
   - Airflow health check failures

2. **External Secrets Timeout**
   - Multiple ExternalSecret resources stuck in 'InProgress'
   - Affecting: rook-ceph-dashboard-password, test-postgres-cluster-app

3. **Data Platform Instability**
   - Trino pods experiencing restart loops
   - HPA metrics collection failing
   - Spark history server deployment invalid

### Warning Events
- IP address reference cleanup warnings (benign)
- Pod restart loops in data-platform namespace
- Grafana container restarts

## Growth Projections & Recommendations

### Short-term (0-6 months)
1. **Current Capacity is Sufficient**
   - CPU and memory usage very low
   - Storage at minimal utilization
   - No immediate expansion needed

2. **Optimization Opportunities**
   - Review resource requests vs actual usage
   - Consider reducing over-provisioned resources
   - Fix failing deployments to reduce resource churn

### Medium-term (6-12 months)
1. **Storage Growth Planning**
   - Current: 30GB of 1.8TB usable (1.7%)
   - Projected: ~400GB usage (assuming 50GB/month growth)
   - Action: Monitor growth rate quarterly

2. **Memory Considerations**
   - Current spare capacity: ~250GB across cluster
   - Sufficient for significant workload expansion
   - Consider memory upgrade only if AI workloads increase

### Long-term (12-24 months)
1. **Hardware Refresh Planning**
   - Current hardware: MS-01 with 12th gen Intel
   - Expected lifecycle: 3-4 years (until 2028-2029)
   - Plan for incremental upgrades vs full refresh

2. **Scaling Strategy**
   - Horizontal: Add 4th node if CPU consistently >70%
   - Vertical: Memory upgrade to 128GB/node for AI workloads
   - Storage: Add NVMe drives when approaching 70% utilization

## Immediate Action Items

### Priority 1: Fix Failing Deployments
1. Resolve Loki GrafanaAgent CRD issue
2. Fix External Secrets connectivity/authentication
3. Stabilize Trino deployment configuration

### Priority 2: Optimize Resource Allocation
1. Adjust resource requests to match actual usage
2. Implement proper HPA configurations
3. Review and optimize Ceph pool configuration

### Priority 3: Establish Monitoring
1. Deploy capacity monitoring alerts
2. Create Grafana dashboards for capacity planning
3. Implement storage growth tracking

## Cost-Benefit Analysis

### Current Investment Efficiency
- **Utilization Rate**: ~10% average
- **Cost per Used Core**: High due to low utilization
- **Recommendation**: Focus on workload growth before hardware expansion

### Future Expansion Options (When Needed)
1. **Storage Only**: $400/node for 2TB NVMe addition
2. **Memory Upgrade**: $800/node for 64GB → 128GB
3. **Additional Node**: $1,500 for 4th MS-01
4. **Network Upgrade**: $800 for 2.5GbE infrastructure

## Conclusion

The Anton homelab has excellent capacity headroom for growth. The immediate focus should be on:
1. Resolving deployment failures to ensure stable operations
2. Optimizing resource allocations to improve efficiency
3. Establishing proper capacity monitoring and alerting

No hardware expansion is needed in the next 6-12 months based on current utilization trends. The cluster can easily support 5-10x current workload with existing hardware.