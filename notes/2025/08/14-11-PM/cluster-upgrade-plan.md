# Anton Homelab Cluster Upgrade Plan
**Date**: August 14, 2025 - 11 PM
**Cluster**: Anton (3-node Talos Linux + Flux GitOps)

## 🎯 Overview
Comprehensive upgrade plan for 26 components in the homelab cluster. Each upgrade follows a strict **one-at-a-time** approach with Git commit → Flux sync → verify → continue workflow.

## 📋 Upgrade Workflow Template
For each component, follow this exact process:

```bash
# 1. Edit HelmRelease file
# 2. Commit to Git
git add kubernetes/apps/{namespace}/{app}/app/helmrelease.yaml
git commit -m "feat({component}): upgrade to v{version}"
git push

# 3. Force Flux reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps

# 4. Monitor deployment
flux get hr {name} -n {namespace} --watch

# 5. Verify health
./scripts/k8s-health-check.ts
kubectl get pods -n {namespace}

# 6. WAIT FOR HEALTHY before proceeding to next component
```

---

## 🚨 PHASE 1: Critical Infrastructure (Execute First)

### 1.1 Flux CLI Upgrade
**Current**: v2.6.1 → **Target**: v2.6.4

```bash
# Client-side upgrade (no Git changes needed)
# macOS: brew upgrade fluxcd/tap/flux
# Linux: curl -s https://fluxcd.io/install.sh | sudo bash

# Verify
flux version --client
# Expected: flux: v2.6.4
```

**Verification**: `flux check` should show no CLI version warning

---

### 1.2 kubectl Version Skew Fix
**Current**: v1.30.7 → **Target**: v1.33.4

```bash
# Fix version skew (kubectl too old)
# macOS: brew upgrade kubernetes-cli
# Linux: Download from https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/

# Verify
kubectl version --client
# Expected: Client Version: v1.33.4
```

**Verification**: No version skew warnings in `kubectl version`

---

### 1.3 Kubernetes Cluster Upgrade
**Current**: v1.33.1 → **Target**: v1.33.4

```bash
# Apply patch upgrade via Talos
task talos:upgrade-k8s

# Monitor upgrade progress
watch kubectl get nodes

# Verify
kubectl version
# Expected: Server Version: v1.33.4
```

**Verification**: All nodes Ready, pods stable, `./scripts/k8s-health-check.ts` passes

---

### 1.4 Talos Linux Upgrade (Per Node)
**Current**: v1.10.4 → **Target**: v1.10.6

```bash
# Upgrade each node individually, wait for Ready before next
task talos:upgrade-node IP=192.168.1.98
# WAIT: kubectl get nodes shows k8s-1 Ready

task talos:upgrade-node IP=192.168.1.99
# WAIT: kubectl get nodes shows k8s-2 Ready

task talos:upgrade-node IP=192.168.1.100
# WAIT: kubectl get nodes shows k8s-3 Ready
```

**Verification**: All nodes running v1.10.6, cluster stable

---

## 🔒 PHASE 2: Security & Secrets (Week 1)

### 2.1 cert-manager Upgrade
**Current**: v1.17.2 → **Target**: v1.18.2

**File**: `kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml`

```yaml
# Change:
spec:
  chart:
    spec:
      version: 1.18.2  # was 1.17.2
```

**Commands**:
```bash
git add kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml
git commit -m "feat(cert-manager): upgrade to v1.18.2"
git push

flux reconcile source git flux-system
flux reconcile kustomization cluster-apps
flux get hr cert-manager -n cert-manager --watch

# Verify certificates still valid
kubectl get certificates -A
kubectl get clusterissuers
```

**Success Criteria**: All certificates Ready, no issuer errors

---

### 2.2 external-secrets Upgrade
**Current**: v0.17.0 → **Target**: v0.19.2

**File**: `kubernetes/apps/external-secrets/external-secrets/app/helmrelease.yaml`

```yaml
# Change:
spec:
  chart:
    spec:
      version: 0.19.2  # was 0.17.0
```

**Commands**:
```bash
git add kubernetes/apps/external-secrets/external-secrets/app/helmrelease.yaml
git commit -m "feat(external-secrets): upgrade to v0.19.2"
git push

flux reconcile source git flux-system
flux reconcile kustomization cluster-apps
flux get hr external-secrets -n external-secrets --watch

# Verify secret sync still working
kubectl get externalsecrets -A
kubectl get clustersecretstores
```

**Success Criteria**: All ExternalSecrets Ready, secrets syncing

---

### 2.3 Rook-Ceph Operator Upgrade
**Current**: v1.17.4 → **Target**: v1.17.7

**Files**: 
- `kubernetes/apps/storage/rook-ceph-operator/app/helmrelease.yaml`
- `kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml`

```yaml
# Change in BOTH files:
spec:
  chart:
    spec:
      version: v1.17.7  # was v1.17.4
```

**Commands**:
```bash
# Update operator first
git add kubernetes/apps/storage/rook-ceph-operator/app/helmrelease.yaml
git commit -m "feat(rook-ceph-operator): upgrade to v1.17.7"
git push

flux reconcile source git flux-system
flux reconcile kustomization cluster-apps
flux get hr rook-ceph-operator -n storage --watch

# WAIT for operator Ready, then update cluster
git add kubernetes/apps/storage/rook-ceph-cluster/app/helmrelease.yaml
git commit -m "feat(rook-ceph-cluster): upgrade to v1.17.7"
git push

flux reconcile kustomization cluster-apps
flux get hr rook-ceph-cluster -n storage --watch

# Verify Ceph health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
./scripts/storage-health-check.ts
```

**Success Criteria**: Ceph HEALTH_OK, all OSDs up, PVCs accessible

---

## 🌐 PHASE 3: Networking & Core Services (Week 2)

### 3.1 Cilium CNI Upgrade (Conservative)
**Current**: v1.17.4 → **Target**: v1.17.6

**File**: `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`

```yaml
# Change:
spec:
  chart:
    spec:
      version: 1.17.6  # was 1.17.4
```

**Commands**:
```bash
git add kubernetes/apps/kube-system/cilium/app/helmrelease.yaml
git commit -m "feat(cilium): upgrade to v1.17.6"
git push

flux reconcile source git flux-system
flux reconcile kustomization cluster-apps
flux get hr cilium -n kube-system --watch

# Critical: Monitor pod networking during rollout
watch kubectl get pods -A
./scripts/network-monitor.ts --json

# Test connectivity
kubectl run test-pod --image=nicolaka/netshoot --rm -it -- ping 8.8.8.8
```

**Success Criteria**: All pods communicating, ingress working, no NetworkPolicy violations

---

### 3.2 ingress-nginx Upgrade
**Current**: v4.12.2 → **Target**: v4.13.1

**Files**:
- `kubernetes/apps/network/external-ingress-nginx/app/helmrelease.yaml`
- `kubernetes/apps/network/internal-ingress-nginx/app/helmrelease.yaml`

```yaml
# Change in BOTH files:
spec:
  chart:
    spec:
      version: 4.13.1  # was 4.12.2
```

**Commands**:
```bash
# Update external ingress first
git add kubernetes/apps/network/external-ingress-nginx/app/helmrelease.yaml
git commit -m "feat(external-ingress-nginx): upgrade to v4.13.1"
git push

flux reconcile kustomization cluster-apps
flux get hr external-ingress-nginx -n network --watch

# Test external ingress
curl -I https://your-external-service.domain.com

# Update internal ingress
git add kubernetes/apps/network/internal-ingress-nginx/app/helmrelease.yaml
git commit -m "feat(internal-ingress-nginx): upgrade to v4.13.1"
git push

flux reconcile kustomization cluster-apps
flux get hr internal-ingress-nginx -n network --watch

# Test internal ingress
./scripts/network-monitor.ts
```

**Success Criteria**: Both ingress controllers Ready, all ingress routes accessible

---

### 3.3 external-dns Upgrade
**Current**: v1.16.1 → **Target**: v1.18.0

**File**: `kubernetes/apps/network/external-dns/app/helmrelease.yaml`

```yaml
# Change:
spec:
  chart:
    spec:
      version: 1.18.0  # was 1.16.1
```

**Commands**:
```bash
git add kubernetes/apps/network/external-dns/app/helmrelease.yaml
git commit -m "feat(external-dns): upgrade to v1.18.0"
git push

flux reconcile kustomization cluster-apps
flux get hr external-dns -n network --watch

# Verify DNS records still managed
kubectl logs -n network deployment/external-dns -f
```

**Success Criteria**: DNS records updating correctly, no resolution issues

---

## 📈 PHASE 4: Monitoring Stack (Week 3)

### 4.1 Loki Upgrade (Safe Patch)
**Current**: v6.30.1 → **Target**: v6.36.0

**File**: `kubernetes/apps/monitoring/loki/app/helmrelease.yaml`

```yaml
# Change:
spec:
  chart:
    spec:
      version: 6.36.0  # was 6.30.1
```

**Commands**:
```bash
git add kubernetes/apps/monitoring/loki/app/helmrelease.yaml
git commit -m "feat(loki): upgrade to v6.36.0"
git push

flux reconcile kustomization cluster-apps
flux get hr loki -n monitoring --watch

# Verify log ingestion
./scripts/test-loki-logcli.ts
./scripts/logcli-wrapper.ts query '{namespace="flux-system"}' --limit=5
```

**Success Criteria**: Log ingestion working, Grafana dashboards functional

---

### 4.2 kube-prometheus-stack Upgrade
**Current**: v72.9.1 → **Target**: v76.3.0

**File**: `kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml`

```yaml
# Change:
spec:
  chart:
    spec:
      version: 76.3.0  # was 72.9.1
```

**Commands**:
```bash
git add kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml
git commit -m "feat(kube-prometheus-stack): upgrade to v76.3.0"
git push

flux reconcile kustomization cluster-apps
flux get hr kube-prometheus-stack -n monitoring --watch

# Monitor for CRD updates (may require manual intervention)
kubectl get prometheuses -A
kubectl get servicemonitors -A
kubectl get alertmanagers -A

# Verify Grafana accessible
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
# Test: http://localhost:3000
```

**Success Criteria**: Prometheus/Grafana/AlertManager functional, all dashboards loading

---

### 4.3 Alloy Investigation & Upgrade
**Current**: v1.1.1 → **Target**: TBD (investigate version)

```bash
# First, investigate the version discrepancy
helm search repo grafana/alloy --versions
kubectl get hr alloy -n monitoring -o yaml | grep version

# If upgrade needed, follow standard process
git add kubernetes/apps/monitoring/alloy/app/helmrelease.yaml
git commit -m "feat(alloy): upgrade to v{determined_version}"
git push

flux reconcile kustomization cluster-apps
flux get hr alloy -n monitoring --watch
```

**Success Criteria**: Alloy collecting metrics correctly, dashboards functional

---

## 🔨 PHASE 5: System Utilities (Week 4)

### 5.1 metrics-server Upgrade
**Current**: v3.12.2 → **Target**: v3.13.0

**File**: `kubernetes/apps/kube-system/metrics-server/app/helmrelease.yaml`

```yaml
spec:
  chart:
    spec:
      version: 3.13.0  # was 3.12.2
```

**Commands**:
```bash
git add kubernetes/apps/kube-system/metrics-server/app/helmrelease.yaml
git commit -m "feat(metrics-server): upgrade to v3.13.0"
git push

flux reconcile kustomization cluster-apps
flux get hr metrics-server -n kube-system --watch

# Verify metrics collection
kubectl top nodes
kubectl top pods -A
```

**Success Criteria**: `kubectl top` commands working, HPA functional

---

### 5.2 reloader Upgrade
**Current**: v2.1.3 → **Target**: v2.2.0

**File**: `kubernetes/apps/kube-system/reloader/app/helmrelease.yaml`

```yaml
spec:
  chart:
    spec:
      version: 2.2.0  # was 2.1.3
```

**Commands**:
```bash
git add kubernetes/apps/kube-system/reloader/app/helmrelease.yaml
git commit -m "feat(reloader): upgrade to v2.2.0"
git push

flux reconcile kustomization cluster-apps
flux get hr reloader -n kube-system --watch

# Test reloader functionality
kubectl logs -n kube-system deployment/reloader -f
```

**Success Criteria**: Reloader detecting config/secret changes

---

### 5.3 node-problem-detector Upgrade
**Current**: v2.3.14 → **Target**: v2.3.22

**File**: `kubernetes/apps/system-health/node-problem-detector/app/helmrelease.yaml`

```yaml
spec:
  chart:
    spec:
      version: 2.3.22  # was 2.3.14
```

**Commands**:
```bash
git add kubernetes/apps/system-health/node-problem-detector/app/helmrelease.yaml
git commit -m "feat(node-problem-detector): upgrade to v2.3.22"
git push

flux reconcile kustomization cluster-apps
flux get hr node-problem-detector -n system-health --watch

# Verify node problem detection
kubectl get events -A --field-selector reason=NodeProblemDetector
```

**Success Criteria**: NPD running on all nodes, detecting issues correctly

---

### 5.4 CNPG Operator Upgrade
**Current**: v0.24.0 → **Target**: v0.26.0

**File**: `kubernetes/apps/cnpg-system/cnpg-operator/app/helmrelease.yaml`

```yaml
spec:
  chart:
    spec:
      version: 0.26.0  # was 0.24.0
```

**Commands**:
```bash
git add kubernetes/apps/cnpg-system/cnpg-operator/app/helmrelease.yaml
git commit -m "feat(cnpg-operator): upgrade to v0.26.0"
git push

flux reconcile kustomization cluster-apps
flux get hr cnpg-operator -n cnpg-system --watch

# Verify PostgreSQL clusters unaffected
kubectl get clusters -A
kubectl get poolers -A
```

**Success Criteria**: PostgreSQL clusters remain healthy, operator functional

---

### 5.5 VPA Upgrade
**Current**: v4.6.0 → **Target**: v4.8.0

**File**: `kubernetes/apps/system-health/vpa/app/helmrelease.yaml`

```yaml
spec:
  chart:
    spec:
      version: 4.8.0  # was 4.6.0
```

**Commands**:
```bash
git add kubernetes/apps/system-health/vpa/app/helmrelease.yaml
git commit -m "feat(vpa): upgrade to v4.8.0"
git push

flux reconcile kustomization cluster-apps
flux get hr vpa -n system-health --watch

# Verify VPA recommendations
kubectl get vpa -A
kubectl describe vpa -A
```

**Success Criteria**: VPA providing resource recommendations

---

### 5.6 spegel Upgrade
**Current**: v0.2.0 → **Target**: v0.3.0

**File**: `kubernetes/apps/kube-system/spegel/app/helmrelease.yaml`

```yaml
spec:
  chart:
    spec:
      version: 0.3.0  # was 0.2.0
```

**Commands**:
```bash
git add kubernetes/apps/kube-system/spegel/app/helmrelease.yaml
git commit -m "feat(spegel): upgrade to v0.3.0"
git push

flux reconcile kustomization cluster-apps
flux get hr spegel -n kube-system --watch

# Verify image caching
kubectl logs -n kube-system daemonset/spegel -f
```

**Success Criteria**: Container image caching functional

---

## 🔍 PHASE 6: Investigation & Cleanup

### 6.1 app-template Version Investigation

```bash
# Check actual version from OCI registry
helm show chart oci://ghcr.io/bjw-s/helm-charts/app-template --version 4.0.1

# Verify current deployments using app-template
grep -r "app-template" kubernetes/apps/
# Found: echo, echo-2, cloudflared

# If update needed, update all simultaneously:
# kubernetes/apps/default/echo/app/helmrelease.yaml
# kubernetes/apps/default/echo-2/app/helmrelease.yaml
# kubernetes/apps/network/cloudflared/app/helmrelease.yaml
```

### 6.2 goldilocks Debugging

```bash
# Fix the failing HelmChart reconciliation
flux get sources helm -A | grep goldilocks
kubectl describe helmchart -n flux-system system-health-goldilocks

# Likely fix: force source refresh
flux reconcile source helm <repo-name> -n flux-system
```

---

## ✅ Post-Upgrade Verification Checklist

After completing all upgrades, run comprehensive health checks:

```bash
# 1. Cluster health
./scripts/k8s-health-check.ts --json

# 2. Network connectivity
./scripts/network-monitor.ts --json

# 3. Storage functionality
./scripts/storage-health-check.ts --json

# 4. Monitoring stack
./scripts/test-logging-stack.ts --json

# 5. Flux GitOps health
flux check
flux get all -A

# 6. Application functionality
./scripts/test-all.ts --json

# 7. Resource utilization
kubectl top nodes
kubectl top pods -A

# 8. Final validation
deno task test:all:json
```

## 📝 Rollback Procedures

If any upgrade fails:

```bash
# 1. Immediate rollback via Git
git revert <commit-hash>
git push

# 2. Force Flux sync
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps

# 3. Monitor recovery
flux get hr -A
./scripts/k8s-health-check.ts

# 4. If still broken, manual intervention
kubectl delete hr <name> -n <namespace>
flux reconcile kustomization cluster-apps
```

## 🎯 Success Metrics

**Completion Criteria**:
- ✅ All 26 components upgraded to target versions
- ✅ Zero failing HelmReleases
- ✅ All health checks passing
- ✅ No degraded services
- ✅ Monitoring/logging functional
- ✅ GitOps pipeline healthy

**Timeline**: 4 weeks total (1 week per phase)
**Risk Level**: Low (patch/minor updates, comprehensive testing)
**Rollback Time**: < 5 minutes per component via Git revert