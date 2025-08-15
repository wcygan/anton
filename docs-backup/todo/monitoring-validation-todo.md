# Monitoring Validation & Completion TODO

This document outlines the remaining monitoring validation and ServiceMonitor completion work identified during the cluster hardening session.

## Current Status

### ✅ Components WITH ServiceMonitors
- cert-manager ✓
- cilium (agent + operator) ✓
- metrics-server ✓ 
- spegel ✓
- flux-operator ✓
- external-dns ✓
- ingress-nginx (internal + external) ✓
- node-problem-detector ✓
- echo apps ✓
- cloudflared ✓
- Prometheus stack components ✓

### ❌ Components MISSING ServiceMonitors

**High Priority (Should have monitoring)**:
1. **cnpg-operator** - ServiceMonitor commented out/disabled in helmrelease
   - Location: `kubernetes/apps/cnpg-system/cnpg-operator/app/helmrelease.yaml`
   - Action: Uncomment and enable metrics + serviceMonitor

2. **k8s-gateway** - No ServiceMonitor despite having service
   - Location: `kubernetes/apps/network/internal/k8s-gateway/helmrelease.yaml`
   - Action: Add serviceMonitor configuration

3. **external-secrets** - Components have no ServiceMonitors
   - Location: `kubernetes/apps/external-secrets/external-secrets/app/helmrelease.yaml`
   - Action: Add serviceMonitor for main controller, cert-controller, webhook

**Medium Priority**:
4. **onepassword-connect** - No ServiceMonitor
   - Location: `kubernetes/apps/external-secrets/onepassword-connect/app/helmrelease.yaml`
   - Action: Check if metrics port exists, add serviceMonitor if available

5. **kubeai operator** - No ServiceMonitor for operator
   - Location: `kubernetes/apps/kubeai/kubeai-operator/app/helmrelease.yaml`
   - Action: Check if operator exposes metrics

**Low Priority**:
6. **reloader** - No service exposed (deployment only)
   - Note: May not expose metrics externally, verify first

## Implementation Tasks

### Phase 1: ServiceMonitor Addition (At Home with Cluster Access)

#### Task 1: Enable cnpg-operator monitoring
```yaml
# Edit kubernetes/apps/cnpg-system/cnpg-operator/app/helmrelease.yaml
# Uncomment these lines:
metrics:
  enabled: true
serviceMonitor:
  enabled: true
```

#### Task 2: Add k8s-gateway monitoring
```yaml
# Add to kubernetes/apps/network/internal/k8s-gateway/helmrelease.yaml
serviceMonitor:
  enabled: true
  interval: 30s
```

#### Task 3: Add external-secrets monitoring
```yaml
# Add to kubernetes/apps/external-secrets/external-secrets/app/helmrelease.yaml
serviceMonitor:
  enabled: true
  interval: 30s
```

#### Task 4: Verify onepassword-connect metrics capability
```bash
# Check if onepassword-connect exposes metrics
kubectl port-forward -n external-secrets deployment/onepassword-connect 8080:8080
curl http://localhost:8080/metrics
```

### Phase 2: Validation (At Home)

#### Task 5: Prometheus Target Validation
```bash
# Port-forward to Prometheus
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090

# Check all targets are up
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health == "down")'

# Verify new ServiceMonitors appear
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job | contains("cnpg"))'
```

#### Task 6: ServiceMonitor Discovery Validation
```bash
# Create monitoring validation script
./scripts/validate-servicemonitors.ts

# Check for missing ServiceMonitors
kubectl get svc -A -o json | jq -r '.items[] | select(.spec.ports[]?.name | test("metrics|prometheus")) | "\(.metadata.namespace)/\(.metadata.name)"' | sort > services-with-metrics.txt

kubectl get servicemonitor -A -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name)"' | sort > existing-servicemonitors.txt

comm -23 services-with-metrics.txt existing-servicemonitors.txt
```

#### Task 7: Grafana Dashboard Verification
```bash
# Verify metrics appear in Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

# Check datasource connectivity
# Verify new metrics appear in explore tab
```

### Phase 3: Documentation & Alerting

#### Task 8: Create monitoring runbook
- Document all ServiceMonitor configurations
- Create troubleshooting guide for monitoring issues
- Add alert rules for critical service monitoring

#### Task 9: Add missing metrics dashboards
- Create dashboards for newly monitored services
- Ensure all critical services have visualization

## Validation Checklist

When implementing, verify each step:

- [ ] cnpg-operator ServiceMonitor enabled and working
- [ ] k8s-gateway metrics being scraped  
- [ ] external-secrets components monitored
- [ ] onepassword-connect metrics available (if applicable)
- [ ] kubeai operator metrics available (if applicable)
- [ ] All Prometheus targets showing as "up"
- [ ] New metrics visible in Grafana
- [ ] No scrape errors in Prometheus logs

## Success Criteria

**Complete when**:
1. All infrastructure components have appropriate ServiceMonitors
2. Prometheus successfully scrapes all expected targets  
3. Key metrics are visible in Grafana dashboards
4. No critical monitoring gaps remain

## Notes

- This work requires stable cluster access and is best done locally
- Current cluster monitoring is already functional - this is gap closure
- Focus on infrastructure components first, application monitoring second
- Test each ServiceMonitor addition individually before proceeding

## Context

This todo was created during a remote cluster hardening session where we successfully completed:
- Fixed all infinite retries in HelmReleases
- Added resource constraints to all critical components
- Implemented health checks for key Kustomizations
- Identified monitoring gaps for completion at home

The cluster is production-ready; this monitoring completion is operational improvement.