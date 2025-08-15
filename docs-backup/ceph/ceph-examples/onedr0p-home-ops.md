# Investigation: Rook Ceph Setup in Home-Ops Repository

  Executive Summary

  This repository implements a production-grade Rook Ceph deployment on a Talos Linux Kubernetes cluster,
   utilizing NVMe storage across all nodes with triple replication. The setup includes comprehensive
  monitoring, automated backups via VolSync, and serves as the default storage class for all stateful
  applications.

  Current State Analysis

  Existing Implementation

  Architecture Overview:
  - Rook Version: v1.17.4 (both operator and cluster)
  - Storage Type: Distributed block storage (CephBlockPool)
  - Replication: 3-way replication across hosts
  - Network: Host networking for optimal performance
  - Storage Devices: Micron 7450 NVMe drives (/dev/disk/by-id/nvme-Micron_7450_MTFDKBA800TFS_.*)

  Key Features:
  - Default storage class (ceph-block) with automatic provisioning
  - Volume snapshots enabled via CSI driver
  - Prometheus monitoring and alerting integration
  - Dashboard accessible at rook.devbu.io (internal gateway)
  - Automated hourly backups using VolSync with Restic
  - Compression enabled (zstd aggressive mode)
  - Disk prediction and auto-scaling modules enabled

  Storage Configuration

  Primary Storage Class (ceph-block):
  - Provisioner: rook-ceph.rbd.csi.ceph.com
  - Reclaim Policy: Delete
  - Volume Expansion: Enabled
  - Mount Options: ["discard"]
  - Compression: zstd (aggressive)
  - Image Format: 2
  - File System: ext4

  Volume Snapshot Class:
  - Name: csi-ceph-blockpool
  - Deletion Policy: Delete
  - Default: false

  Integration Points

  1. VolSync Backup Integration:
    - Schedule: Hourly snapshots
    - Retention: 24 hourly, 7 daily
    - Cache Storage: OpenEBS hostpath
    - Snapshot Class: csi-ceph-blockpool
  2. Application Usage:
    - All stateful applications use ceph-block
    - PVCs automatically provisioned
    - Examples: Home Assistant, Jellyfin, Plex, Sonarr, Radarr
  3. Secondary Storage (OpenEBS):
    - Provides local hostpath storage
    - Used for VolSync cache storage
    - Base path: /var/mnt/extra/openebs/local

  Deployment Strategy

  Bootstrap Process

  1. Disk Preparation:
    - Bootstrap script includes wipe_rook_disks() function
    - Automatically detects and wipes Micron NVMe disks
    - Skips wipe if Rook is already running
    - Uses environment variable ROOK_DISK for disk model matching
  2. Flux Kustomizations:
  - rook-ceph (operator) → deploys first
  - rook-ceph-cluster → depends on operator and volsync
  3. Health Checks:
    - HelmRelease health monitoring
    - CephCluster health states (HEALTH_OK, HEALTH_WARN, HEALTH_ERR)
    - 15-minute timeout for cluster deployment

  Security & Access

  - Dashboard Authentication: Password stored in 1Password via External Secrets
  - Internal Access Only: Dashboard exposed through internal gateway
  - CSI Secrets: Properly namespaced and managed by Rook

  Monitoring & Observability

  - Prometheus Rules: Automatically created for Ceph metrics
  - Service Monitors: Enabled for CSI components
  - Toolbox: Enabled for debugging and maintenance
  - Modules Enabled:
    - diskprediction_local
    - insights
    - pg_autoscaler
    - rook

  Best Practices Implemented

  1. High Availability:
    - 3-way replication across failure domain "host"
    - Host networking for performance
    - All nodes participate in storage cluster
  2. Performance Optimization:
    - Compression with zstd algorithm
    - Discard mount option for SSD optimization
    - Async discard threads enabled
    - Read affinity for CSI enabled
  3. Operational Excellence:
    - Automated disk discovery and configuration
    - Comprehensive monitoring integration
    - Automated backup solution
    - Clean upgrade/rollback strategy via Flux
  4. Storage Efficiency:
    - Single OSD per device
    - Compression enabled
    - Smart disk failure prediction

  Key Considerations

  1. No CephFS: Filesystem driver is disabled, only block storage is used
  2. No Object Storage: CephObjectStores are not configured
  3. Host Networking: Required for optimal performance but limits pod placement
  4. Disk Wipe Required: Fresh disks must be wiped before Rook installation
  5. Resource Requirements: Operator has fixed resource requests (128Mi memory, 100m CPU)

  This Rook Ceph setup represents a well-architected storage solution suitable for a home lab
  environment, with enterprise-grade features like monitoring, automated backups, and high availability
  while maintaining operational simplicity through GitOps management.
  
  Top-Level Structure
  
    /Users/wcygan/Development/talos-clusters/onedr0p/home-ops/
    ├── LICENSE
    ├── README.md
    ├── Taskfile.yaml
    ├── bootstrap/
    ├── kubernetes/
    ├── scripts/
    ├── talos/
    └── wcygan/
  
    Key Directories
  
    kubernetes/apps/ - Application Deployments
  
    Organized by namespace with each app having:
    - app/ - Main Helm releases and configurations
    - ks.yaml - Kustomization file
    - Some apps have tools/ subdirectories
  
    Namespaces include:
    - actions-runner-system/ - GitHub Actions runners
    - cert-manager/ - Certificate management
    - default/ - Media apps (Plex, Jellyfin, Sonarr, etc.)
    - external-secrets/ - Secret management
    - flux-system/ - GitOps tooling
    - kube-system/ - Core Kubernetes components
    - network/ - Networking (Cloudflare, DNS)
    - observability/ - Monitoring (Prometheus, Grafana, Loki)
    - openebs-system/ - Storage provider
    - rook-ceph/ - Primary storage system
    - system-upgrade/ - Cluster upgrade automation
    - volsync-system/ - Backup and sync
  
    kubernetes/components/ - Reusable Components
  
    - common/ - Shared resources (alerts, repos, SOPS)
    - gatus/ - Health check configurations
    - keda/ - Auto-scaling components
    - volsync/ - Backup templates
  
    bootstrap/ - Initial Setup
  
    - helmfile.yaml - Bootstrap Helm deployments
    - resources.yaml.j2 - Jinja2 template for resources
  
    scripts/ - Automation
  
    - bootstrap-cluster.sh - Main cluster setup script
    - render-machine-config.sh - Talos configuration generation
    - lib/common.sh - Shared functions
  
    talos/ - Talos Linux Configuration
  
    - controlplane.yaml.j2 - Control plane template
    - nodes/ - Per-node configurations (192.168.42.10-12)
  
    The structure follows GitOps principles with Flux managing deployments through Kustomizations, making
    it easy to maintain and scale the Kubernetes cluster infrastructure.