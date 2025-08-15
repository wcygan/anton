# Private Docker Registry Deployment

**Date:** 2025-08-15  
**Context:** Setting up private container registry for NextJS app deployment

## Problem Statement

Need to deploy a NextJS application to Kubernetes cluster while:
- Keeping container images private (no public registry)
- Not exposing private GitHub repository URL
- Maintaining GitOps workflow with Flux
- Avoiding manual deployment scripts

## Solution: Simple Docker Registry

Chose lightweight Docker Registry over Harbor due to:
- **Scale**: Single NextJS app vs enterprise needs
- **Resources**: 512MB vs 4GB+ for Harbor
- **Complexity**: Single pod vs 15+ microservices
- **Integration**: Works with existing Ceph storage

## Deployment Structure

```
kubernetes/apps/registry/
├── namespace.yaml
├── kustomization.yaml
└── docker-registry/
    ├── ks.yaml
    └── app/
        ├── kustomization.yaml
        ├── helmrepository.yaml
        └── helmrelease.yaml
```

## Key Configuration

- **Chart**: `twuni/docker-registry` v2.2.3
- **Storage**: 50GB on Ceph (`ceph-block`)
- **Access**: Internal ingress at `registry.anton.local`
- **Auth**: Basic auth (admin:admin123)
- **TLS**: Auto-generated via cert-manager

## Deployment Results

### ✅ Infrastructure Deployed Successfully
1. **Service**: Running on `docker-registry.registry.svc.cluster.local:5000`
2. **Authentication**: Working (returns 401 without credentials)
3. **Ingress**: Available at `registry.anton.local`
4. **Storage**: 50GB Ceph PVC allocated and mounted
5. **TLS**: Certificate auto-provisioned via cert-manager

### Deployment Fixes Applied
- Fixed HelmRepository namespace reference (registry namespace)
- Corrected ingress hosts format for chart compatibility
- Verified GitOps reconciliation through Flux

### Usage Instructions
```bash
# From local machine (via Tailscale):
docker build -t registry.anton.local/nextjs-app:latest .
docker login registry.anton.local  # admin:admin123
docker push registry.anton.local/nextjs-app:latest

# In Kubernetes manifests:
spec:
  containers:
  - name: nextjs-app
    image: registry.anton.local/nextjs-app:latest
```

## Benefits

- ✅ **Private**: Images never leave homelab network
- ✅ **GitOps**: Integrates with existing Flux workflow
- ✅ **Simple**: Single component, minimal overhead
- ✅ **Automated**: No manual scripts required
- ✅ **Scalable**: Can handle multiple applications

## Security Considerations

- Registry accessible only via Tailscale/internal network
- Basic auth prevents unauthorized access
- TLS encryption for image transfers
- No external dependencies or exposure

## Future Enhancements

If needed later:
- GitHub Actions with Tailscale for automated builds
- Image scanning integration
- Multi-registry replication
- Advanced RBAC

## Repository Impact

- Added registry to `kubernetes/apps/kustomization.yaml`
- Zero changes required to application repositories
- Maintains separation of concerns (infra vs app code)

## Final Status

**✅ DEPLOYMENT COMPLETE**
- Registry is fully operational and accessible
- Ready for NextJS application image hosting
- All GitOps workflows functioning correctly
- Verified through cluster testing and ingress connectivity

**Commits Applied:**
- `e37f6fc`: Initial registry deployment
- `753db73`: Fix helm repository namespace
- `2b7cb6a`: Update namespace reference
- `a2dfa61`: Correct ingress hosts format