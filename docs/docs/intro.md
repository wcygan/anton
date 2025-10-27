---
sidebar_position: 1
slug: /
---

# Anton

Kubernetes homelab cluster for learning & experimentation.

🔗 **Blog Post**: https://wcygan.net/anton

### Hardware
- **Nodes**: 3x MS-01 mini PCs (Intel N100, 16GB RAM each)
- **Storage**: 6x 1TB NVMe SSDs
- **Network**: Gigabit Ethernet

### Operating System
- **OS**: [Talos Linux](https://www.talos.dev/) - API-driven, immutable Kubernetes OS
- **Management**: Declarative configuration via YAML
- **Security**: No SSH access, minimal attack surface
- **Updates**: Dual disk image approach with rollback capability

## Cluster Topology

```mermaid
flowchart TD
    internet[Internet] --> cloudflare[Cloudflare Tunnel]
    cloudflare --> external[Envoy External<br/>Gateway]

    subgraph cluster[Anton Kubernetes Cluster]
        external
        internal[Envoy Internal<br/>Gateway]

        subgraph nodes[Control Plane Nodes]
            direction LR
            k8s1[k8s-1<br/>192.168.1.98]
            k8s2[k8s-2<br/>192.168.1.99]
            k8s3[k8s-3<br/>192.168.1.100]
        end

        subgraph apps[Applications]
            direction LR
            cloudflared[Cloudflare<br/>Tunnel]
            metrics[Metrics<br/>Server]
            echo[Echo<br/>Service]
        end
    end

    external --> apps
    internal -.-> apps
    nodes -.-> apps

    classDef node fill:#e1f5fe
    classDef gateway fill:#fff3e0
    classDef app fill:#f3e5f5

    class k8s1,k8s2,k8s3 node
    class external,internal,cloudflare gateway
    class cloudflared,metrics,echo app
```
