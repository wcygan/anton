# DragonflyDB Operator Installation Guide

This guide documents the installation and configuration of the DragonflyDB
operator in your Kubernetes cluster using Flux GitOps.

## Overview

DragonflyDB is a modern, high-performance, Redis-compatible in-memory data
store. The operator provides:

- Automated deployment and management of Dragonfly instances
- Scaling and configuration management
- Backup and recovery capabilities
- Custom Resource Definitions (CRDs) for declarative management

## Architecture

The DragonflyDB setup consists of:

1. **DragonflyDB Operator**: Manages Dragonfly instances via CRDs
2. **Dragonfly Instances**: Individual cache/database instances created via
   `Dragonfly` CRD
3. **Storage Integration**: Uses local-path-provisioner for persistent snapshots

## Installation Process

### 1. Namespace Structure

All DragonflyDB components are deployed to the `database` namespace:

```
kubernetes/apps/database/
├── kustomization.yaml              # Namespace-level orchestration
├── dragonfly-operator/             # Operator deployment
│   ├── ks.yaml                     # Flux Kustomization for operator
│   └── app/
│       └── kustomization.yaml     # Operator manifests and patches
├── test-cache/                     # Example Dragonfly instance
│   ├── ks.yaml                     # Flux Kustomization for instance
│   └── app/
│       ├── kustomization.yaml     # Instance orchestration
│       └── dragonfly.yaml         # Dragonfly CRD definition
└── test-db/                        # CloudNativePG database (separate)
    └── ...
```

### 2. Operator Deployment

The operator is deployed via Flux using the official upstream manifests:

**Source**:
`https://raw.githubusercontent.com/dragonflydb/dragonfly-operator/main/manifests/dragonfly-operator.yaml`

**Key Configuration** (`kubernetes/apps/database/dragonfly-operator/ks.yaml`):

- **Interval**: 15m (operator - fairly important)
- **Namespace**: `database` (patched from default `dragonfly-operator-system`)
- **Health Checks**: Monitors the operator deployment
- **Timeout**: 5m for operator readiness

### 3. Namespace Patching

The operator manifests are extensively patched to relocate from the default
`dragonfly-operator-system` namespace to `database`:

```yaml
# Example patches applied:
- Namespace: dragonfly-operator-system → database
- Deployment: dragonfly-operator → database namespace
- ServiceAccount: dragonfly-operator → database namespace
- RBAC: ClusterRoleBinding subjects → database namespace
- Services: webhook and metrics services → database namespace
- ValidatingAdmissionWebhook: service reference → database namespace
```

### 4. Installation Steps

1. **Ensure Prerequisites**:
   ```bash
   # Verify Flux is operational
   flux check

   # Verify storage class is available
   kubectl get storageclass local-path
   ```

2. **Deploy via Flux**: The operator is automatically deployed when the database
   namespace Kustomization is applied:
   ```bash
   # Force reconciliation if needed
   flux reconcile kustomization cluster-apps -n flux-system --with-source

   # Check operator deployment status
   flux get kustomization dragonfly-operator -n flux-system
   flux describe kustomization dragonfly-operator -n flux-system
   ```

3. **Verify Installation**:
   ```bash
   # Check operator pod
   kubectl get pods -n database -l app.kubernetes.io/name=dragonfly-operator

   # Check operator logs
   kubectl logs -n database deployment/dragonfly-operator -f

   # Verify CRDs are installed
   kubectl get crd dragonflydb.io
   ```

### 5. Operator Configuration

**Resource Requirements**:

- Default resource limits as defined in upstream manifests
- Runs as a single replica deployment
- Requires cluster-wide RBAC permissions for CRD management

**Key Components Installed**:

- `Deployment`: dragonfly-operator
- `ServiceAccount`: dragonfly-operator
- `ClusterRole/ClusterRoleBinding`: Cluster-wide permissions
- `Role/RoleBinding`: Namespace-specific permissions
- `ValidatingAdmissionWebhook`: CRD validation
- `Services`: Metrics and webhook endpoints
- `CustomResourceDefinitions`: Dragonfly CRD

## Flux Integration

### Health Checks

The operator Kustomization includes health checks:

```yaml
healthChecks:
  - apiVersion: apps/v1
    kind: Deployment
    name: dragonfly-operator
    namespace: database
```

This ensures Flux waits for the operator to be ready before marking the
Kustomization as successful.

### Dependencies

The operator has no dependencies and can be deployed immediately after namespace
creation.

### Reconciliation

- **Automatic**: Flux checks for upstream changes every 15 minutes
- **Manual**: Force reconciliation with
  `flux reconcile kustomization dragonfly-operator -n flux-system --with-source`

## Troubleshooting

### Common Issues

1. **Operator Pod Stuck in Pending**:
   ```bash
   kubectl describe pod -n database -l app.kubernetes.io/name=dragonfly-operator
   # Check for resource constraints or scheduling issues
   ```

2. **Webhook Validation Errors**:
   ```bash
   kubectl get validatingadmissionwebhook dragonfly-operator-validating-webhook-configuration
   # Ensure webhook service is accessible
   ```

3. **RBAC Permission Issues**:
   ```bash
   kubectl get clusterrolebinding dragonfly-operator
   kubectl describe clusterrolebinding dragonfly-operator
   # Verify service account references correct namespace
   ```

### Debugging Commands

```bash
# Check operator health
kubectl get deployment dragonfly-operator -n database
kubectl describe deployment dragonfly-operator -n database

# View operator logs
kubectl logs -n database deployment/dragonfly-operator --tail=100

# Check CRD installation
kubectl get crd | grep dragonfly
kubectl describe crd dragonflies.dragonflydb.io

# Verify webhook configuration
kubectl get validatingadmissionwebhook dragonfly-operator-validating-webhook-configuration -o yaml

# Check Flux status
flux describe kustomization dragonfly-operator -n flux-system
```

## Next Steps

After successful operator installation:

1. Deploy Dragonfly instances using the `Dragonfly` CRD (see `testing.md`)
2. Configure monitoring and alerting
3. Set up backup and recovery procedures
4. Configure networking and ingress if needed

## References

- [DragonflyDB Operator Documentation](https://github.com/dragonflydb/dragonfly-operator)
- [DragonflyDB Official Documentation](https://www.dragonflydb.io/docs)
- [Kubernetes Operator Pattern](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/)
