# Horizontal Pod Autoscaler (HPA) Configuration

This document describes the HPA strategy and configuration for the Anton homelab cluster.

## Overview

The cluster uses Horizontal Pod Autoscaler (HPA) to automatically scale stateless workloads based on CPU and memory utilization. All HPAs use the `autoscaling/v2` API with both CPU and memory metrics.

## Current HPA Deployments

### Infrastructure Services

#### Ingress Controllers
- **Internal NGINX**: `network/internal-ingress-nginx` (1-3 replicas, 50% CPU / 70% memory)
- **External NGINX**: `network/external-ingress-nginx` (1-3 replicas, 50% CPU / 70% memory)

**Rationale**: Ingress controllers handle variable traffic loads and benefit from scaling to prevent request queueing during traffic spikes.

### Application Services

#### Web Applications
- **Airflow Webserver**: `airflow/airflow-webserver` (1-3 replicas, 60% CPU / 75% memory)
- **Echo Service**: `default/echo` (1-3 replicas, 60% CPU / 80% memory)
- **Echo-2 Service**: `default/echo-2` (1-3 replicas, 60% CPU / 80% memory)

**Rationale**: Web applications with user-facing interfaces benefit from scaling to maintain response times during peak usage.

#### Data Processing
- **Trino Workers**: `data-platform/trino-worker` (2-5 replicas, 70% CPU / 80% memory)

**Rationale**: Query processing workloads vary significantly in resource requirements. Scaling allows optimal resource utilization during off-peak hours while handling heavy analytical workloads.

## Scaling Behavior Configuration

### Standard Scaling (Web Apps, Ingress)
```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 300  # 5 minutes
    policies:
      - type: Percent
        value: 100
        periodSeconds: 15
  scaleUp:
    stabilizationWindowSeconds: 60   # 1 minute
    policies:
      - type: Percent
        value: 100
        periodSeconds: 15
      - type: Pods
        value: 2
        periodSeconds: 60
    selectPolicy: Max
```

### Conservative Scaling (Data Processing)
```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 600  # 10 minutes
    policies:
      - type: Percent
        value: 50
        periodSeconds: 60
  scaleUp:
    stabilizationWindowSeconds: 180  # 3 minutes
    policies:
      - type: Percent
        value: 100
        periodSeconds: 60
      - type: Pods
        value: 1
        periodSeconds: 60
    selectPolicy: Min
```

## Resource Requirements

For HPA to function properly, target deployments must have:

1. **CPU requests defined** (for CPU-based scaling)
2. **Memory requests defined** (for memory-based scaling)
3. **Sufficient resource limits** to allow scaling

## Monitoring & Metrics

### Current Status
All HPAs are operational with valid metrics from `metrics-server`:

- **Airflow Webserver**: 1% CPU / 69% memory (near memory threshold)
- **Trino Workers**: 2% CPU / 11% memory (maintaining minimum replicas)
- **Echo Services**: 10% CPU / 45-46% memory (stable at minimum)
- **Ingress Controllers**: 1-2% CPU / 17-34% memory (low load)

### Key Metrics to Monitor
- HPA status: `kubectl get hpa -A`
- Scaling events: `kubectl describe hpa <name> -n <namespace>`
- Pod resource usage: Check Grafana dashboards

## Best Practices

### Scaling Thresholds
- **CPU**: 50-70% for web services, 70%+ for compute-intensive workloads
- **Memory**: 70-80% (higher than CPU due to memory allocation patterns)

### Stabilization Windows
- **Scale-up**: 60-180 seconds (faster response to load increases)
- **Scale-down**: 300-600 seconds (prevent thrashing during temporary load drops)

### Replica Ranges
- **Minimum replicas**: 1-2 (maintain availability)
- **Maximum replicas**: 3-5 (prevent resource exhaustion in homelab)

## Workloads NOT Using HPA

### Stateful Services
- **Rook-Ceph** (OSDs, MONs, MDS): Storage orchestration requires manual scaling
- **PostgreSQL databases**: Persistent storage and state considerations
- **Prometheus/Grafana**: Monitoring with persistent storage

### Operators & Infrastructure
- **Flux controllers**: Single replica operators
- **cert-manager**: Certificate management operator
- **external-secrets-operator**: Secret synchronization

### Singleton Services
- **CoreDNS**: Already configured with 2 replicas for HA
- **Cloudflared**: Single tunnel connection required

## Troubleshooting

### Common Issues
1. **Unknown metrics**: Check if metrics-server is running and resource requests are defined
2. **Scaling not occurring**: Verify thresholds and check for resource constraints
3. **Thrashing**: Adjust stabilization windows or thresholds

### Diagnostic Commands
```bash
# Check HPA status
kubectl get hpa -A

# Detailed HPA information
kubectl describe hpa <name> -n <namespace>

# Check target deployment metrics
kubectl top pods -n <namespace>

# View scaling events
kubectl get events -n <namespace> --field-selector involvedObject.kind=HorizontalPodAutoscaler
```

## Expected Benefits

With current HPA configuration:
- **20-30% resource efficiency improvement** during low-traffic periods
- **Improved response times** during peak usage through automatic scaling
- **Enhanced resilience** for user-facing services
- **Cost optimization** by scaling down during off-peak hours

The HPA implementation provides automatic scaling capabilities while maintaining the stability and predictability required for a production homelab environment.