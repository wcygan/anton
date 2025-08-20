---
sidebar_position: 2
---

# Infrastructure

The Anton cluster is built on modern infrastructure principles with a focus on automation, reliability, and observability. This section covers the core technologies that power the cluster.

## Architecture Overview

```mermaid
flowchart TD
    subgraph hardware[Hardware Layer]
        direction LR
        nodes[3x MS-01 Nodes<br/>Intel N100, 16GB RAM]
        storage[6x 1TB NVMe SSDs<br/>Distributed Storage]
    end
    
    subgraph os[Operating System]
        talos[Talos Linux<br/>Immutable OS]
    end
    
    subgraph k8s[Kubernetes Platform]
        direction LR
        cluster[K8s v1.33.1<br/>3-Node Control Plane]
        cni[Cilium CNI<br/>eBPF Networking]
    end
    
    subgraph apps[Application Layer]
        direction LR
        gitops[Flux GitOps<br/>Continuous Deployment]
        monitoring[Prometheus Stack<br/>Observability]
        logging[Loki Stack<br/>Log Aggregation]
        storage_sys[Rook-Ceph<br/>Distributed Storage]
    end
    
    hardware --> os
    os --> k8s
    k8s --> apps
    
    classDef hw fill:#e1f5fe
    classDef sys fill:#fff3e0
    classDef app fill:#f3e5f5
    
    class nodes,storage hw
    class talos,cluster,cni sys
    class gitops,monitoring,logging,storage_sys app
```

## Core Components

### Infrastructure Layer
- **[Hardware](./hardware)** - MS-01 nodes with NVMe storage
- **[Storage](./storage/)** - Rook-Ceph distributed storage system
- **[Networking](./networking/)** - Cilium, NGINX, and Cloudflare integration
- **[Secrets](./secrets)** - External Secrets with 1Password integration

### Platform Services
- **[GitOps](./gitops/)** - Flux-based continuous deployment
- **[Monitoring](./monitoring/)** - Prometheus, Grafana, and AlertManager
- **[Logging](./logging/)** - Loki stack with S3 backend

## Key Features

- **Immutable Infrastructure**: Talos Linux with API-driven management
- **GitOps-First**: All deployments managed through Git
- **High Availability**: 3-node control plane with distributed storage
- **Observability**: Comprehensive monitoring and logging
- **Secure by Default**: eBPF networking and encrypted storage

## Quick Status Commands

```bash
# Cluster health
kubectl get nodes -o wide

# Core namespaces
kubectl get pods -A | grep -E "(flux-system|storage|monitoring|network)"

# Storage status
kubectl get pvc -A

# Ingress controllers
kubectl get ingressclass
```