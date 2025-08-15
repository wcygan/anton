# Kubernetes Resource Allocation Strategy

This document outlines the resource allocation strategy for the Anton homelab cluster, ensuring efficient resource utilization and preventing resource exhaustion.

## Overview

All workloads in the cluster are assigned resource requests and limits based on their criticality and resource consumption patterns. This ensures:

- **Predictable scheduling**: Kubernetes can make informed decisions about pod placement
- **Resource protection**: Prevents any single workload from consuming all available resources
- **Quality of Service**: Critical services get guaranteed resources
- **Cost efficiency**: Right-sizing prevents over-provisioning

## Resource Profiles

### Minimal Profile
**For**: Test applications, simple utilities
- **CPU**: 10m request, 50m limit
- **Memory**: 16Mi request, 64Mi limit
- **Examples**: echo servers, test deployments

### Lightweight Profile  
**For**: System utilities, small operators
- **CPU**: 50m request, 100m limit
- **Memory**: 64Mi request, 128Mi limit
- **Examples**: reloader, VPA admission controller

### Standard Profile
**For**: Regular services, ingress controllers
- **CPU**: 100m request, 200m limit
- **Memory**: 128Mi request, 256Mi limit
- **Examples**: cloudflared, spegel, ingress-nginx

### GitOps Profile
**For**: Flux controllers, GitOps tooling
- **CPU**: 100m request, 500m limit
- **Memory**: 256Mi request, 512Mi limit
- **Examples**: source-controller, kustomize-controller

### Storage Profile
**For**: Storage-intensive workloads
- **CPU**: 500m request, 1000m limit
- **Memory**: 1Gi request, 2Gi limit
- **Examples**: Ceph OSDs, storage operators

### Heavy Profile
**For**: Data-intensive applications
- **CPU**: 200m-500m request, 1000m-2000m limit
- **Memory**: 512Mi-2Gi request, 1Gi-4Gi limit
- **Examples**: Prometheus, Grafana, Airflow, databases

## Service Categories

### Critical Infrastructure (5m reconciliation)
These services are essential for cluster operation:
- **Networking**: Cilium, CoreDNS
- **Certificate Management**: cert-manager
- **Metrics**: metrics-server
- **GitOps**: Flux controllers
- **Secret Management**: external-secrets

### Core Services (15m reconciliation)
Important services that other workloads depend on:
- **Storage**: Rook-Ceph, local-path-provisioner
- **Monitoring**: Prometheus, Grafana, Loki
- **Databases**: CloudNative-PG, Dragonfly
- **Backup**: Velero, Volsync

### Standard Applications (30m reconciliation)
User-facing applications and non-critical services:
- **AI/ML**: KubeAI models
- **Data Platform**: Airflow, Hive Metastore
- **Testing**: Echo servers, demo apps

## Implementation Guidelines

### 1. Always Set Both Requests and Limits
```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi
```

### 2. Component-Specific Resources
For multi-component applications (e.g., Rook-Ceph), set resources per component:
```yaml
cephClusterSpec:
  resources:
    mgr:
      requests:
        cpu: 100m
        memory: 128Mi
    osd:
      requests:
        cpu: 500m
        memory: 1Gi
```

### 3. Memory-Intensive Applications
Applications known to be memory-intensive should have higher limits:
- **Prometheus**: 2Gi request, 4Gi limit
- **Grafana**: 256Mi request, 1Gi limit
- **Loki**: 256Mi request, 1Gi limit

### 4. CPU Bursting
CPU limits are set 2x the request to allow for bursting during peak loads while preventing runaway consumption.

### 5. Quality of Service Classes
Based on our allocation:
- **Guaranteed**: When requests = limits (not used to allow bursting)
- **Burstable**: When requests < limits (our standard approach)
- **BestEffort**: No resources set (avoided in production)

## Monitoring Resource Usage

### Check Current Usage
```bash
# Node resource usage
kubectl top nodes

# Pod resource usage by namespace
kubectl top pods -A --sort-by=memory

# Detailed pod metrics
kubectl top pod -n monitoring prometheus-0 --containers
```

### Prometheus Queries
```promql
# Memory usage percentage
container_memory_usage_bytes / container_spec_memory_limit_bytes

# CPU throttling
rate(container_cpu_cfs_throttled_periods_total[5m])

# OOM kills
increase(container_oom_events_total[1h])
```

## Adjustment Process

1. **Monitor actual usage** for at least 7 days
2. **Identify patterns** using Prometheus/Grafana
3. **Adjust requests** to 80% of P95 usage
4. **Set limits** to 2x requests for CPU, 1.5-2x for memory
5. **Test thoroughly** before applying to production

## Tools and Automation

### Resource Limit Script
Use `scripts/add-resource-limits.ts` to:
- Audit services without limits
- Apply standard profiles automatically
- Maintain consistency across deployments

### Validation
All changes are validated through:
- `deno task validate` - Manifest validation
- Flux dry-run before deployment
- Prometheus alerts for resource exhaustion

## Best Practices

1. **Start conservative**: Better to increase limits than deal with OOM kills
2. **Use VPA recommendations**: Let Vertical Pod Autoscaler suggest optimal values
3. **Consider node capacity**: Ensure total requests don't exceed node capacity
4. **Plan for failures**: Account for node failures in capacity planning
5. **Review quarterly**: Resource needs change as usage patterns evolve

## Current Status

As of the latest update:
- ✅ 100% of critical infrastructure has resource limits
- ✅ 100% of core services has resource limits  
- ✅ 100% of standard applications has resource limits
- 📊 Total cluster resource allocation allows for ~20% overhead

## References

- [Kubernetes Resource Management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- [Quality of Service Classes](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
- [Vertical Pod Autoscaler](https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler)