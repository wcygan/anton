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

## Workflow

### Infrastructure (Done)
1. Deploy registry via GitOps
2. Registry available at `registry.anton.local`
3. Ready for any container images

### Application Deployment (Future)
1. Build: `docker build -t registry.anton.local/nextjs-app:latest .`
2. Push: `docker push registry.anton.local/nextjs-app:latest`
3. Deploy: Standard k8s manifests referencing private image

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