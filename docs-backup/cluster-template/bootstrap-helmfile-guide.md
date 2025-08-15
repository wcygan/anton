# Helmfile Bootstrap Guide

This guide explains the helmfile-based bootstrap process used to deploy critical infrastructure components in the homelab Kubernetes cluster.

## Overview

The homelab uses a two-phase deployment strategy:
1. **Helmfile Bootstrap**: Deploys CNI, DNS, and other critical infrastructure that Flux depends on
2. **Flux GitOps**: Manages all other applications once infrastructure is ready

This approach solves the chicken-and-egg problem where Flux needs networking to deploy the networking components.

## Helmfile Configuration

The bootstrap configuration is located at `/bootstrap/helmfile.yaml`:

```yaml
helmDefaults:
  cleanupOnFail: true
  wait: true
  waitForJobs: true

repositories:
  - name: cilium
    url: https://helm.cilium.io

releases:
  - name: cilium
    namespace: kube-system
    atomic: true
    chart: cilium/cilium
    version: 1.17.4
    values: ['{{ requiredEnv "ROOT_DIR" }}/kubernetes/apps/kube-system/cilium/app/helm/values.yaml']
  
  # ... additional releases ...
```

## Components and Dependencies

### Bootstrap Order

The components must be deployed in a specific order due to dependencies:

```
1. Cilium (CNI)
   └── 2. CoreDNS
       └── 3. Spegel (Registry Mirror)
           └── 4. Cert-Manager
               └── 5. Flux Operator
                   └── 6. Flux Instance
```

### Component Details

#### 1. Cilium (Container Network Interface)
- **Purpose**: Provides pod networking and replaces kube-proxy
- **Namespace**: `kube-system`
- **Dependencies**: None (first component)
- **Values**: `/kubernetes/apps/kube-system/cilium/app/helm/values.yaml`

#### 2. CoreDNS
- **Purpose**: Cluster DNS resolution
- **Namespace**: `kube-system`
- **Dependencies**: Cilium (needs pod networking)
- **Values**: `/kubernetes/apps/kube-system/coredns/app/helm/values.yaml`

#### 3. Spegel
- **Purpose**: In-cluster container image registry mirror
- **Namespace**: `kube-system`
- **Dependencies**: CoreDNS (needs DNS resolution)
- **Values**: `/kubernetes/apps/kube-system/spegel/app/helm/values.yaml`

#### 4. Cert-Manager
- **Purpose**: Automated TLS certificate management
- **Namespace**: `cert-manager`
- **Dependencies**: DNS and networking
- **Values**: `/kubernetes/apps/cert-manager/cert-manager/app/helm/values.yaml`

#### 5. Flux Operator
- **Purpose**: Manages Flux lifecycle
- **Namespace**: `flux-system`
- **Dependencies**: Cert-Manager (for webhook certificates)
- **Values**: `/kubernetes/apps/flux-system/flux-operator/app/helm/values.yaml`

#### 6. Flux Instance
- **Purpose**: Deploys Flux controllers
- **Namespace**: `flux-system`
- **Dependencies**: Flux Operator
- **Values**: `/kubernetes/apps/flux-system/flux-instance/app/helm/values.yaml`

## Usage

### Prerequisites

1. Install required tools:
   ```bash
   # macOS
   brew install helmfile helm kubectl
   
   # Or use the version manager
   asdf install helmfile latest
   asdf install helm latest
   ```

2. Set environment variables:
   ```bash
   export ROOT_DIR=/path/to/homelab
   export KUBECONFIG=$ROOT_DIR/kubeconfig
   ```

### Running Bootstrap

#### Full Bootstrap

Deploy all components in order:

```bash
cd $ROOT_DIR
helmfile --file bootstrap/helmfile.yaml sync
```

#### Selective Deployment

Deploy specific components using labels:

```bash
# Deploy only Cilium
helmfile --file bootstrap/helmfile.yaml -l name=cilium sync

# Deploy only networking components
helmfile --file bootstrap/helmfile.yaml -l name=cilium sync
helmfile --file bootstrap/helmfile.yaml -l name=coredns sync
```

#### Dry Run

Preview what would be deployed:

```bash
helmfile --file bootstrap/helmfile.yaml diff
```

### Verification

After deployment, verify each component:

```bash
# Check release status
helmfile --file bootstrap/helmfile.yaml list

# Verify Cilium
kubectl get pods -n kube-system -l app.kubernetes.io/name=cilium
kubectl exec -n kube-system ds/cilium -- cilium status

# Verify CoreDNS
kubectl get deploy -n kube-system coredns
kubectl run test-dns --image=busybox --rm -it --restart=Never -- nslookup kubernetes

# Verify Cert-Manager
kubectl get pods -n cert-manager
kubectl get crd | grep cert-manager

# Verify Flux
kubectl get pods -n flux-system
flux check
```

## Troubleshooting

### Common Issues

#### 1. Helmfile "Release already exists"

If helmfile shows a release as installed but it's not running:

```bash
# Check actual helm releases
helm list -A | grep <release-name>

# Force reinstall
helmfile --file bootstrap/helmfile.yaml -l name=<release> sync --force
```

#### 2. Dependencies Not Met

If a component fails due to missing dependencies:

```bash
# Deploy dependencies first
helmfile --file bootstrap/helmfile.yaml -l name=cilium sync
helmfile --file bootstrap/helmfile.yaml -l name=coredns sync
# Then retry the failing component
```

#### 3. Values File Not Found

Ensure ROOT_DIR is set correctly:

```bash
export ROOT_DIR=$(git rev-parse --show-toplevel)
```

#### 4. Network Timeouts

If deployments timeout:

```bash
# Increase timeout in helmfile.yaml
helmDefaults:
  timeout: 600  # 10 minutes
```

### Debug Mode

Enable verbose output:

```bash
helmfile --file bootstrap/helmfile.yaml --debug sync
```

## Integration with Task

The bootstrap process is integrated with Taskfile:

```bash
# Run full bootstrap
task bootstrap:apps

# This runs the script at:
# scripts/bootstrap-apps.sh
```

The script performs additional steps:
1. Waits for nodes to be ready
2. Creates namespaces
3. Applies SOPS secrets
4. Installs CRDs
5. Runs helmfile

## Recovery Scenarios

### Scenario 1: Complete Cluster Failure

```bash
# Ensure nodes are ready
kubectl get nodes

# Run full bootstrap
cd $ROOT_DIR
task bootstrap:apps
```

### Scenario 2: Only Networking Failed

```bash
# Deploy just CNI and DNS
export ROOT_DIR=$(pwd)
helmfile --file bootstrap/helmfile.yaml -l name=cilium sync
helmfile --file bootstrap/helmfile.yaml -l name=coredns sync
```

### Scenario 3: Flux Not Working

```bash
# Redeploy Flux components
helmfile --file bootstrap/helmfile.yaml -l name=flux-operator sync
helmfile --file bootstrap/helmfile.yaml -l name=flux-instance sync

# If FluxInstance was deleted
helm get manifest flux-instance -n flux-system | kubectl apply -f -
```

## Best Practices

1. **Always Set ROOT_DIR**: Export the environment variable before running helmfile
2. **Check Node Health First**: Ensure all nodes are Ready before bootstrap
3. **Monitor Logs**: Watch pod logs during deployment for issues
4. **Verify Each Step**: Don't proceed if a component fails
5. **Keep Values in Sync**: The helmfile uses the same values files as Flux

## Helm Values Locations

Each component's Helm values are stored alongside their Flux definitions:

```
kubernetes/apps/
├── kube-system/
│   ├── cilium/app/helm/values.yaml
│   ├── coredns/app/helm/values.yaml
│   └── spegel/app/helm/values.yaml
├── cert-manager/
│   └── cert-manager/app/helm/values.yaml
└── flux-system/
    ├── flux-operator/app/helm/values.yaml
    └── flux-instance/app/helm/values.yaml
```

This ensures consistency between bootstrap and GitOps deployments.

## Maintenance

### Updating Component Versions

1. Update version in `/bootstrap/helmfile.yaml`
2. Update version in corresponding HelmRelease
3. Test in dev environment
4. Deploy using helmfile first
5. Commit changes for Flux to track

### Adding New Bootstrap Components

1. Add repository to helmfile.yaml if needed
2. Add release configuration with proper dependencies
3. Create values file in appropriate location
4. Test deployment order
5. Update this documentation

## Conclusion

The helmfile bootstrap provides a reliable way to deploy critical infrastructure that Flux depends on. By understanding the component dependencies and following the correct order, you can recover from even complete cluster failures. Always remember: CNI first, then DNS, then everything else.