<!--
name: resource-allocation-review
owner: homelab-admin
tags: kubernetes, monitoring, optimization, resources
description: Analyzes Kubernetes cluster resource allocation and provides optimization recommendations
-->

Perform a comprehensive resource allocation review of the Kubernetes cluster and provide optimization recommendations:

## Analysis Steps

1. **Current Resource Usage Assessment**
   - Use MCP Kubernetes server to inspect all pod resource requests and limits across namespaces
   - Analyze actual resource consumption vs requested/limited resources
   - Identify over-provisioned and under-provisioned workloads

2. **Node Capacity Analysis**
   - Review node resource capacity and current allocation
   - Calculate resource fragmentation and utilization efficiency
   - Identify scheduling bottlenecks and resource pressure points

3. **Application-Specific Optimization**
   - Focus on $ARGUMENTS namespace/application if specified, otherwise analyze all critical namespaces
   - Review resource patterns for core services (Flux, monitoring, storage, ingress)
   - Identify workloads that could benefit from vertical or horizontal scaling

4. **Recommendations Generation**
   - Provide specific YAML diffs for resource request/limit adjustments
   - Suggest consolidation opportunities for low-utilization workloads
   - Identify candidates for resource sharing or co-location
   - Recommend monitoring alerts for resource pressure

5. **Small Cluster Specific Optimizations**
   - Apply homelab-specific best practices for 3-node cluster efficiency
   - Consider Talos Linux memory management and resource reserved by kubelet
   - Optimize for the MS-01 hardware profile (limited compute, emphasis on efficiency)

## Output Format

Provide findings as:
- **Executive Summary**: Overall cluster resource health and top 3 optimization priorities
- **Detailed Analysis**: Per-namespace resource utilization with specific recommendations
- **Action Items**: Prioritized list of configuration changes with expected impact
- **Monitoring Recommendations**: Alerts and dashboards to track resource optimization success

Focus on practical, immediately actionable recommendations that improve resource efficiency without compromising workload reliability in this production homelab environment.