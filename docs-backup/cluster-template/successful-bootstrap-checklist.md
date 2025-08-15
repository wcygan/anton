# Successful Bootstrap Checklist

This document provides a comprehensive checklist for verifying a successful cluster bootstrap, based on the successful deployment of the Anton homelab cluster.

## Pre-Bootstrap Verification

### ✅ Node Readiness
- [ ] All nodes showing `NotReady` status (expected without CNI)
- [ ] Kubernetes control plane pods running:
  - [ ] `kube-apiserver-*` pods in `Running` state
  - [ ] `kube-controller-manager-*` pods in `Running` state  
  - [ ] `kube-scheduler-*` pods in `Running` state
- [ ] Basic kubectl connectivity working

### ✅ Configuration Validation
- [ ] Talos configuration applied successfully
- [ ] kubeconfig generated and accessible
- [ ] Required namespaces exist (or will be created by bootstrap)

## Bootstrap Process Verification

### ✅ Namespace Creation
Verify all required namespaces are created:
```bash
kubectl get namespaces
```

Expected namespaces:
- [ ] `airflow`
- [ ] `cert-manager` 
- [ ] `cnpg-system`
- [ ] `data-platform`
- [ ] `database`
- [ ] `external-secrets`
- [ ] `flux-system`
- [ ] `kubeai`
- [ ] `monitoring`
- [ ] `nessie`
- [ ] `network`
- [ ] `storage`
- [ ] `system-health`

### ✅ SOPS Secrets Applied
- [ ] `sops-age` secret exists in `flux-system` namespace
- [ ] No critical errors for missing optional secrets (warnings are acceptable)

### ✅ CRDs Installation
Verify Custom Resource Definitions are applied:
```bash
kubectl get crd | grep -E "(prometheus|external-dns)"
```

Expected CRDs:
- [ ] Prometheus Operator CRDs (ServiceMonitor, PrometheusRule, etc.)
- [ ] External-DNS CRDs (DNSEndpoint)

### ✅ Helm Releases Deployment
Verify all core Helm releases are deployed:
```bash
helm list -A
```

Expected releases:
- [ ] `cilium` (kube-system namespace)
- [ ] `coredns` (kube-system namespace) 
- [ ] `spegel` (kube-system namespace)
- [ ] `cert-manager` (cert-manager namespace)
- [ ] `flux-operator` (flux-system namespace)
- [ ] `flux-instance` (flux-system namespace)

## Post-Bootstrap Verification

### ✅ Node Status
All nodes should transition to Ready:
```bash
kubectl get nodes
```
- [ ] All nodes show `Ready` status
- [ ] All nodes show correct Kubernetes version
- [ ] All nodes have proper roles assigned

### ✅ Core Infrastructure Pods

#### Cilium CNI
```bash
kubectl get pods -n kube-system -l k8s-app=cilium
```
- [ ] One Cilium agent pod per node (all `Running`)
- [ ] Cilium operator pod `Running`
- [ ] No restart loops or errors

#### CoreDNS
```bash
kubectl get pods -n kube-system -l k8s-app=kube-dns
```
- [ ] At least 2 CoreDNS pods `Running`
- [ ] No DNS resolution issues

#### Cert-Manager
```bash
kubectl get pods -n cert-manager
```
- [ ] `cert-manager` controller pod `Running`
- [ ] `cert-manager-cainjector` pod `Running` 
- [ ] `cert-manager-webhook` pod `Running`

#### Spegel Registry Mirror
```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=spegel
```
- [ ] One Spegel pod per node (all `Running`)
- [ ] Registry mirror functionality active

#### Flux GitOps
```bash
kubectl get pods -n flux-system
```
- [ ] `flux-operator` pod `Running`
- [ ] Flux controllers starting up (may be `Pending` initially)
  - [ ] `helm-controller`
  - [ ] `kustomize-controller` 
  - [ ] `notification-controller`
  - [ ] `source-controller`

### ✅ Networking Verification

#### Pod-to-Pod Communication
```bash
# Test DNS resolution
kubectl run test-pod --image=busybox:1.28 --restart=Never --rm -ti -- nslookup kubernetes.default
```
- [ ] DNS resolution working
- [ ] Pod networking functional

#### CNI Health Check
```bash
cilium status
```
- [ ] Cilium reports healthy status
- [ ] All nodes connected to Cilium mesh
- [ ] No connectivity issues reported

### ✅ GitOps Readiness

#### Flux System Health
```bash
flux check
```
- [ ] All Flux components healthy
- [ ] Git source connectivity working
- [ ] Ready to sync repository state

#### Git Repository Sync
```bash
flux get sources git -A
flux get kustomizations -A
```
- [ ] Git repository source `Ready`
- [ ] Initial kustomizations starting to reconcile

## Success Criteria Summary

The bootstrap is considered successful when:

1. **All nodes are `Ready`** - CNI has enabled pod networking
2. **Core infrastructure pods are `Running`** - Essential services operational  
3. **Flux is operational** - GitOps workflow can begin
4. **Networking is functional** - Pods can communicate and resolve DNS
5. **No critical errors** - All essential components started without failures

## Next Steps After Successful Bootstrap

1. **Monitor Rollout**: 
   ```bash
   kubectl get pods --all-namespaces --watch
   ```

2. **Verify Flux Sync**:
   ```bash
   flux get hr -A
   flux get ks -A
   ```

3. **Force Repository Sync**:
   ```bash
   task reconcile
   ```

4. **Begin Application Deployment**: Flux will start deploying applications from your Git repository

## Troubleshooting Quick Reference

### Common Issues
- **Nodes stuck `NotReady`**: CNI not deployed or failing
- **Pods stuck `Pending`**: Resource constraints or scheduling issues  
- **CRD errors**: Upstream version compatibility issues
- **Flux not syncing**: Git connectivity or authentication problems

### Debug Commands
```bash
# Check events for issues
kubectl get events --sort-by='.lastTimestamp' -A

# Check specific pod logs
kubectl logs -n <namespace> <pod-name>

# Describe resources for detailed status
kubectl describe <resource> <name> -n <namespace>

# Force Flux reconciliation
flux reconcile source git flux-system
task reconcile
```

## Documentation References
- [Bootstrap Troubleshooting](./bootstrap-troubleshooting.md)
- [Talos Linux Operations](../talos-linux/operations-guide.md)
- [Flux GitOps Workflows](../flux/troubleshooting.md)