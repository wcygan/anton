# KubeProxyDown Alert with Cilium CNI

## Overview

The `KubeProxyDown` alert is a **critical** severity alert that fires when Prometheus cannot detect kube-proxy metrics. In clusters using Cilium CNI in kube-proxy replacement mode, this alert is **expected behavior** and does not indicate a problem.

## Alert Details

- **Alert Name**: `KubeProxyDown`
- **Severity**: Critical
- **Expression**: `absent(up{job="kube-proxy"} == 1)`
- **Duration**: 15 minutes
- **Source**: `kube-prometheus-stack-kubernetes-system-kube-proxy` PrometheusRule

## Why This Alert Fires with Cilium

### Cilium Kube-Proxy Replacement Mode

When Cilium is configured in kube-proxy replacement mode:

1. **No kube-proxy pods are deployed** - Cilium handles all proxy functionality
2. **No kube-proxy metrics are exposed** - Prometheus cannot find the `kube-proxy` job
3. **Alert triggers as designed** - The absence detection works correctly

### Verification Commands

Check if Cilium is running in kube-proxy replacement mode:

```bash
# Check Cilium configuration
kubectl get configmap cilium-config -n kube-system -o jsonpath='{.data.kube-proxy-replacement}'
# Should return: true

# Verify no kube-proxy pods exist
kubectl get pods -n kube-system -l k8s-app=kube-proxy
# Should return: No resources found

# Check Cilium pods are healthy
kubectl get pods -n kube-system -l k8s-app=cilium
# Should show running Cilium pods on each node
```

## Cluster Configuration

### Cilium Configuration

The Anton homelab cluster uses Cilium v1.17.4 with these key settings:

```yaml
# From cilium-config ConfigMap
kube-proxy-replacement: "true"
routing-mode: "native"
datapath-mode: "veth"
enable-ipv4-masquerade: "true"
enable-bpf-masquerade: "true"
tunnel-protocol: "vxlan"
```

### Network Architecture

- **CNI**: Cilium v1.17.4 in kube-proxy replacement mode
- **Routing**: Native routing with VXLAN tunneling
- **Load Balancing**: eBPF-based load balancing (DSR mode)
- **Node Count**: 3 nodes (all control-plane)

## Resolution Options

### Option 1: Accept the Alert (Recommended)

**Status**: No action required - this is expected behavior.

The alert indicates the monitoring system is working correctly by detecting the intentional absence of kube-proxy.

### Option 2: Suppress the Alert

If you want to eliminate the noise, you can suppress this specific alert:

```yaml
# Add to kube-prometheus-stack values
prometheus:
  prometheusSpec:
    rules:
      spec:
        groups:
        - name: kubernetes-system-kube-proxy.custom
          rules:
          - alert: KubeProxyDown
            expr: 'absent(up{job="kube-proxy"} == 1) and absent(kube_pod_info{pod=~"cilium-.*"})'
            for: 15m
            labels:
              severity: critical
            annotations:
              description: "KubeProxy has disappeared AND Cilium is not running"
              summary: "Critical: No proxy functionality available"
```

### Option 3: Disable Kube-Proxy Monitoring

Disable kube-proxy monitoring entirely in the Helm values:

```yaml
# In kube-prometheus-stack helmrelease.yaml
values:
  kubeProxy:
    enabled: false
```

## Monitoring Cilium Instead

### Cilium Metrics

Cilium exposes metrics on port 9962. Key metrics to monitor:

- `cilium_agent_up` - Agent health
- `cilium_datapath_errors_total` - Datapath errors
- `cilium_endpoint_state` - Endpoint states
- `cilium_policy_enforcement_status` - Policy enforcement

### ServiceMonitor Configuration

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cilium-agent
  namespace: monitoring
spec:
  selector:
    matchLabels:
      k8s-app: cilium
  endpoints:
  - port: prometheus
    interval: 30s
    path: /metrics
```

## Troubleshooting

### Verify Cilium is Providing Proxy Services

```bash
# Check service endpoints are populated
kubectl get endpoints -A

# Verify pod-to-service connectivity
kubectl run test-pod --image=curlimages/curl --rm -it -- curl http://kubernetes.default.svc.cluster.local

# Check Cilium agent status
kubectl exec -n kube-system ds/cilium -- cilium status
```

### Common Issues

1. **Alert fires but Cilium is unhealthy**:
   - Check Cilium DaemonSet status
   - Review Cilium agent logs
   - Verify CNI configuration

2. **Network connectivity problems**:
   - Check eBPF program loading
   - Verify kernel compatibility
   - Review Cilium networking configuration

## Best Practices

### Monitoring Strategy

1. **Monitor Cilium health** instead of kube-proxy
2. **Alert on Cilium agent failures** 
3. **Track datapath error rates**
4. **Monitor endpoint connectivity**

### Documentation

- Keep this alert documentation updated when changing CNI configuration
- Document any custom alert rules or suppressions
- Include troubleshooting steps for team members

## References

- [Cilium Kube-Proxy Replacement Documentation](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/)
- [Prometheus Alert Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Anton Cluster Cilium Configuration](../../kubernetes/apps/kube-system/cilium/app/helmrelease.yaml)

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2025-06-11 | Initial documentation | System |
| | Added troubleshooting steps | |
| | Documented resolution options | |