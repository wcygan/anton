# Horizontal Pod Autoscaler (HPA) Configuration

This document describes the HPA configurations implemented in the homelab cluster to automatically scale workloads based on resource utilization.

## Overview

The cluster now includes HPA configurations for several workloads to improve resource efficiency and performance during varying load conditions. All HPAs use metrics-server for CPU and memory-based scaling decisions.

## Configured HPAs

### 1. Ingress Controllers (High Priority)

#### Internal Ingress NGINX Controller
- **Location**: `kubernetes/apps/network/internal/ingress-nginx/hpa.yaml`
- **Target**: `internal-ingress-nginx-controller` deployment
- **Scaling**: 1-3 replicas
- **Metrics**: 
  - CPU: 50% utilization target
  - Memory: 70% utilization target
- **Rationale**: Handles internal traffic with variable load patterns

#### External Ingress NGINX Controller
- **Location**: `kubernetes/apps/network/external/ingress-nginx/hpa.yaml`
- **Target**: `external-ingress-nginx-controller` deployment
- **Scaling**: 1-3 replicas
- **Metrics**: 
  - CPU: 50% utilization target
  - Memory: 70% utilization target
- **Rationale**: Handles external traffic via Cloudflare tunnel

### 2. Web Applications (High Priority)

#### Echo Test Applications
- **Location**: 
  - `kubernetes/apps/default/echo/app/hpa.yaml`
  - `kubernetes/apps/default/echo-2/app/hpa.yaml`
- **Target**: `echo` and `echo-2` deployments
- **Scaling**: 1-3 replicas
- **Metrics**: 
  - CPU: 60% utilization target
  - Memory: 80% utilization target
- **Rationale**: Test applications demonstrating HPA functionality

#### Airflow Webserver
- **Location**: `kubernetes/apps/airflow/airflow/app/hpa.yaml`
- **Target**: `airflow-webserver` deployment
- **Scaling**: 1-3 replicas
- **Metrics**: 
  - CPU: 60% utilization target
  - Memory: 75% utilization target
- **Rationale**: Web UI for Airflow with variable user access patterns

### 3. Data Platform Workers (Medium Priority)

#### Trino Workers
- **Location**: `kubernetes/apps/data-platform/trino/app/hpa.yaml`
- **Target**: `trino-worker` deployment
- **Scaling**: 2-5 replicas
- **Metrics**: 
  - CPU: 70% utilization target
  - Memory: 80% utilization target
- **Behavior**: Conservative scaling with longer stabilization windows
- **Rationale**: Query processing workers that benefit from horizontal scaling

## HPA Behavior Configuration

### Scaling Policies

All HPAs include custom behavior configurations:

#### Scale Up
- **Stabilization Window**: 60 seconds (180s for Trino)
- **Policies**: 
  - 100% increase allowed per 15-60 seconds
  - Maximum 2 pods added per minute
- **Policy Selection**: Max (Min for Trino - conservative)

#### Scale Down
- **Stabilization Window**: 300 seconds (600s for Trino)
- **Policies**: 
  - 100% decrease allowed per 15 seconds (50% for Trino)
- **Rationale**: Prevents thrashing during load fluctuations

### Homelab-Specific Considerations

1. **Conservative Targets**: Higher CPU/memory thresholds than production to account for homelab resource constraints
2. **Limited Replicas**: Maximum 3-5 replicas to fit within cluster capacity
3. **Longer Stabilization**: Prevents aggressive scaling in homelab environment
4. **Resource Requests**: All target deployments have appropriate resource requests/limits

## Monitoring HPA Status

### Check HPA Status
```bash
# View all HPAs
kubectl get hpa -A

# Detailed HPA information
kubectl describe hpa <name> -n <namespace>

# Watch HPA behavior
kubectl get hpa -A --watch
```

### Common Commands
```bash
# Check metrics availability
kubectl top nodes
kubectl top pods -A

# View HPA events
kubectl get events -A --field-selector reason=SuccessfulRescale

# Force immediate metrics collection
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
```

## Workloads NOT Configured for HPA

### Stateful Workloads
- **Rook-Ceph components**: Storage systems requiring careful orchestration
- **PostgreSQL**: Database with persistent storage requirements
- **Prometheus/AlertManager**: Monitoring with persistent storage

### Singleton Services
- **Operators**: Flux, cert-manager, rook-ceph-operator
- **CoreDNS**: Already configured with 2 replicas for HA

### Services with Different Scaling Patterns
- **Open-WebUI**: Single-user interface in homelab context
- **Loki/Grafana**: Monitoring tools with different scaling requirements

## Troubleshooting

### HPA Not Scaling
1. **Check metrics-server**: `kubectl get deployment metrics-server -n kube-system`
2. **Verify resource requests**: HPAs require CPU/memory requests on target pods
3. **Check HPA conditions**: `kubectl describe hpa <name> -n <namespace>`

### Common Issues
- **"unknown" metrics**: Resource requests not configured
- **Scaling delays**: Normal behavior due to stabilization windows
- **Metrics unavailable**: metrics-server connectivity issues

## Future Enhancements

### Custom Metrics
Consider implementing custom metrics for more sophisticated scaling:
- **Request rate**: For web applications
- **Queue depth**: For job processing systems
- **Connection count**: For database proxies

### VPA Integration
The cluster already has VPA (Vertical Pod Autoscaler) deployed. Consider VPA for workloads that don't scale horizontally well but could benefit from right-sized resource requests.

## Validation

After deployment, validate HPA functionality:
1. Monitor HPA status: `kubectl get hpa -A`
2. Generate load on test applications to observe scaling
3. Check Grafana dashboards for scaling events
4. Review resource utilization patterns