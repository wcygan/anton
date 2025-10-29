---
sidebar_position: 1
slug: /
---

# Anton

Kubernetes homelab cluster. I use this for:

- Exposing applications to the public internet
- Hosting applications that I can access remotely over VPN
- Trying new stuff

🔗 **Blog Post**: https://wcygan.net/anton

## Cluster Access

```mermaid
flowchart TD
    subgraph external[Public Access]
        direction TB
        domain1[wcygan.net<br/>Cloudflare]
        domain2[anotherdomain.com<br/>Cloudflare]
    end

    subgraph internal[Internal Access - VPN Only]
        direction TB
        domain3[my.private.ts.net<br/>Tailscale]
    end

    subgraph cluster[Anton Cluster]
        direction TB
        apps[Applications<br/>& Services]
    end

    domain1 --> apps
    domain2 --> apps
    domain3 -.-> apps

    classDef cloudflare fill:#f4811f,color:#fff
    classDef tailscale fill:#242526,color:#fff
    classDef clusterBox fill:#e1f5fe

    class domain1,domain2 cloudflare
    class domain3 tailscale
    class apps clusterBox
```

### Hardware
- **Nodes**: 3x MS-01 mini PCs (Intel N100, 16GB RAM each)
- **Storage**: 6x 1TB NVMe SSDs
- **Network**: Gigabit Ethernet

### Operating System
- **OS**: [Talos Linux](https://www.talos.dev/) - API-driven, immutable Kubernetes OS
- **Management**: Declarative configuration via YAML
- **Security**: No SSH access, minimal attack surface

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