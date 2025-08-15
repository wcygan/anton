# VPA + Goldilocks Deployment Guide

## Overview

This guide documents the deployment and usage of Fairwinds VPA (Vertical Pod Autoscaler) and Goldilocks in the homelab cluster. These tools help optimize resource requests and limits for better cluster efficiency and stability.

## Components

### VPA (Vertical Pod Autoscaler)

VPA automatically adjusts resource requests and limits for containers based on actual usage:
- **Recommender**: Monitors resource usage and provides recommendations
- **Updater**: Applies recommendations (can evict pods if needed)
- **Admission Controller**: Modifies resource requests on pod creation

### Goldilocks

Goldilocks provides a dashboard to visualize VPA recommendations and makes it easy to:
- View resource recommendations for all workloads
- Export recommended values for HelmReleases
- Identify over/under-provisioned workloads

## Deployment

The deployment consists of:

1. **HelmRepository**: `fairwinds` in flux-system namespace
2. **VPA**: Deployed to system-health namespace
3. **Goldilocks**: Deployed to system-health namespace with Tailscale ingress

### Files Created

```
kubernetes/
├── flux/
│   └── meta/
│       └── repos/
│           └── fairwinds.yaml              # Fairwinds Helm repository
└── apps/
    └── system-health/
        ├── kustomization.yaml              # Updated to include VPA and Goldilocks
        ├── vpa/
        │   ├── ks.yaml                     # VPA Kustomization
        │   └── app/
        │       ├── kustomization.yaml      # VPA app kustomization
        │       └── helmrelease.yaml        # VPA HelmRelease
        └── goldilocks/
            ├── ks.yaml                     # Goldilocks Kustomization
            └── app/
                ├── kustomization.yaml      # Goldilocks app kustomization
                ├── helmrelease.yaml        # Goldilocks HelmRelease
                └── tailscale-ingress.yaml  # Tailscale ingress for dashboard
```

### Deploy Commands

```bash
# Commit and push changes
git add kubernetes/
git commit -m "feat(system-health): add VPA and Goldilocks for resource optimization"
git push

# Force reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps

# Check deployment status
flux get hr -A | grep -E "vpa|goldilocks"
kubectl get pods -n system-health
```

## Usage

### Enabling VPA for Namespaces

VPA is configured with `on-by-default: false`, so you need to explicitly enable it for namespaces:

```bash
# Enable VPA for a specific namespace
kubectl label namespace <namespace-name> goldilocks.fairwinds.com/enabled=true

# Example: Enable for default namespace
kubectl label namespace default goldilocks.fairwinds.com/enabled=true

# Disable VPA for a namespace
kubectl label namespace <namespace-name> goldilocks.fairwinds.com/enabled-
```

### Accessing Goldilocks Dashboard

The dashboard is accessible via Tailscale:

```bash
# Access via Tailscale (MagicDNS must be enabled)
https://goldilocks

# Or check the Tailscale device name
kubectl get ingress -n system-health goldilocks-tailscale
```

### Dashboard Features

1. **Namespace Overview**: See all namespaces with VPA enabled
2. **Workload Details**: View recommendations for each deployment/statefulset
3. **Export Values**: Copy recommended resource values for HelmReleases
4. **Quality of Service**: Understand QoS class implications

### VPA Modes

VPA can operate in different modes per workload:

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  updatePolicy:
    updateMode: "Auto"  # Options: "Off", "Initial", "Recreate", "Auto"
```

- **Off**: Only provides recommendations, no action taken
- **Initial**: Only sets resources on pod creation
- **Recreate**: Updates pods (may evict if needed)
- **Auto**: Currently same as Recreate, future versions may update in-place

## Configuration Details

### VPA Configuration

Key settings in the HelmRelease:

- **Prometheus Integration**: Configured to use kube-prometheus-stack
- **Memory Saver Mode**: Enabled to reduce memory usage
- **Eviction Tolerance**: 0.5 (50% difference required for eviction)
- **Min Replicas**: 2 (won't evict if it reduces replicas below 2)

### Goldilocks Configuration

Key settings:

- **On by Default**: Disabled (opt-in per namespace)
- **Excluded Containers**: `linkerd-proxy,istio-proxy` (service mesh sidecars)
- **Dashboard**: Enabled with Tailscale ingress

## Best Practices

1. **Start with Off Mode**: Monitor recommendations before enabling automatic updates
2. **Test in Non-Production**: Enable VPA in test namespaces first
3. **Set Resource Policies**: Define min/max boundaries for VPA recommendations
4. **Monitor Evictions**: Watch for excessive pod evictions
5. **Regular Reviews**: Check Goldilocks dashboard weekly for optimization opportunities

## Monitoring

Both VPA and Goldilocks expose Prometheus metrics:

```bash
# Check VPA metrics
kubectl get servicemonitor -n system-health

# Example PromQL queries:
# VPA recommendation changes
rate(vpa_recommender_recommendation_change_total[5m])

# Pod evictions by VPA
increase(vpa_updater_evictions_total[1h])
```

## Troubleshooting

### VPA Not Providing Recommendations

```bash
# Check VPA recommender logs
kubectl logs -n system-health -l app.kubernetes.io/component=recommender

# Verify Prometheus connection
kubectl exec -n system-health deployment/vpa-recommender -- wget -O- http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=up
```

### Goldilocks Dashboard Empty

```bash
# Check if namespace is labeled
kubectl get namespace -L goldilocks.fairwinds.com/enabled

# Check controller logs
kubectl logs -n system-health -l app.kubernetes.io/name=goldilocks-controller
```

### Too Many Evictions

```bash
# Check updater configuration
kubectl get deployment -n system-health vpa-updater -o yaml | grep -A5 "eviction-tolerance"

# Temporarily disable updates
kubectl patch vpa <vpa-name> -n <namespace> --type='json' -p='[{"op": "replace", "path": "/spec/updatePolicy/updateMode", "value":"Off"}]'
```

## Security Considerations

1. **RBAC**: VPA has cluster-wide read permissions and limited write permissions
2. **Admission Webhook**: Uses mutual TLS for secure communication
3. **Pod Eviction**: VPA can evict pods - ensure PodDisruptionBudgets are configured
4. **Resource Limits**: Always set maximum resource boundaries to prevent runaway scaling

## Next Steps

1. Enable VPA for selected namespaces
2. Monitor recommendations for a week
3. Apply recommendations to HelmReleases
4. Consider enabling "Initial" mode for stable workloads
5. Set up alerts for excessive evictions