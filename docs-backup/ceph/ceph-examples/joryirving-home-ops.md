# Investigation: Rook Ceph Setup in Home-Ops Repository

  Executive Summary

  This repository implements a production-grade Rook Ceph v1.17.4 distributed storage system on a Talos
  Linux Kubernetes cluster. The setup leverages Samsung enterprise NVMe SSDs with 3-way replication,
  providing block, filesystem, and object storage with comprehensive monitoring, automated backups via
  Volsync, and high availability across multiple nodes.

  Current State Analysis

  Existing Implementation

  The Rook Ceph deployment consists of:

  - Dual Helm Release Architecture: Separate operator and cluster deployments for better lifecycle
  management
  - Three Storage Classes: Block (default), filesystem (shared), and object storage (S3-compatible)
  - Enterprise Hardware: Samsung MZQL21T9HCJR NVMe drives specifically selected via device filters
  - Network Isolation: Dedicated public (10.69.1.0/24) and cluster (169.254.255.0/24) networks
  - Control Plane Affinity: MGR and MON components restricted to control plane nodes

  Architecture Highlights

  1. Storage Configuration:
    - Block storage with aggressive zstd compression
    - CephFS for shared filesystem needs
    - S3-compatible object storage with erasure coding (2+1)
    - All pools use 3-replica configuration with host-level failure domain
  2. Performance Optimizations:
    - Asynchronous discard with dedicated thread for SSD optimization
    - CephFS kernel mount with ms_mode=prefer-crc for better performance
    - Advanced RBD features enabled (layering, fast-diff, object-map)
    - Compression enabled on block storage
  3. High Availability:
    - Active-standby MDS configuration for CephFS
    - 2 RGW instances for object storage
    - Topology spread constraints for metadata servers
    - Priority class system-cluster-critical for critical components

  Monitoring & Operations

  Dashboard Access

  - URL: https://rook.jory.dev
  - Authentication: Password stored in 1Password, synced via ExternalSecret
  - Features: No SSL (terminated at gateway), integrated with Prometheus

  Observability Stack

  monitoring:
    enabled: true
    createPrometheusRules: true
    prometheusEndpoint: http://prometheus-operated.observability.svc.cluster.local:9090

  - ServiceMonitors for CSI components
  - Prometheus rules for health monitoring
  - Health states tracked: HEALTH_OK, HEALTH_WARN, HEALTH_ERR
  - Discovery daemon enabled for automatic OSD discovery

  Backup Strategy with Volsync

  Implementation Details

  The backup integration provides:

  1. Snapshot-Based Backups:
    - Uses Ceph CSI snapshots for consistency
    - Default snapshot class: csi-ceph-blockpool
    - Hourly schedule with jitter to prevent thundering herd
  2. Retention Policy:
  retain:
    hourly: 24
    daily: 10
    weekly: 5
    monthly: 3
  3. Dual Destination Support:
    - Local NFS: voyager.internal:/mnt/user/kubernetes/volsync
    - Remote R2: Cloudflare object storage with S3 compatibility
  4. Monitoring:
    - VolSyncComponentAbsent: Component health tracking
    - VolSyncVolumeOutOfSync: Sync status monitoring (5+ minute threshold)

  Resource Management

  Operator Resources

  resources:
    requests:
      memory: 128Mi  # unchangeable
      cpu: 100m      # unchangeable

  Component Resources

  - MDS: 100m CPU, 1Gi memory (4Gi limit)
  - RGW: 100m CPU, 1Gi memory (2Gi limit)

  Advanced Features

  MGR Modules

  - diskprediction_local: Predictive disk failure analysis
  - insights: Ceph insights telemetry
  - pg_autoscaler: Automatic placement group optimization
  - rook: Orchestration module for Rook integration

  Security & Access Control

  - Dashboard password via ExternalSecret from 1Password
  - Proper RBAC through Kubernetes native mechanisms
  - CSI secrets for provisioner and node operations
  - Network isolation with dedicated subnets

  FluxCD GitOps Integration

  spec:
    interval: 1h
    timeout: 15m
    prune: false  # Safety measure
    healthChecks:
      - HelmRelease status
      - CephCluster health

  Key safety features:
  - Prune disabled to prevent accidental deletions
  - Extended timeout for cluster operations
  - Health check expressions for Ceph cluster state
  - Drift detection commented out for stability

  Best Practices Implemented

  1. Production Readiness:
    - Enterprise-grade hardware selection
    - Comprehensive monitoring and alerting
    - Automated backup with retention policies
    - High availability configuration
  2. Operational Excellence:
    - GitOps-driven deployment
    - Component reusability via Kustomize
    - Proper resource limits and requests
    - Network isolation for security
  3. Disaster Recovery:
    - Multi-destination backup strategy
    - Snapshot-based consistent backups
    - Automated retention management
    - Easy restore capabilities

  Conclusion

  This Rook Ceph implementation demonstrates a well-architected storage solution optimized for a home lab
   environment while maintaining enterprise-grade features. The careful balance between performance (NVMe
   SSDs, compression, optimizations), reliability (3-way replication, HA configuration), and operability
  (monitoring, GitOps, automated backups) makes this a robust foundation for stateful workloads in the
  Kubernetes cluster.
  
  ## Rook Ceph - Simple Explanation
  
    What is it?
  
    Rook Ceph is like having your own personal cloud storage built into your Kubernetes cluster. Think of
    it as turning your hard drives into something like Google Drive or Dropbox, but you own and control
    everything.
  
    How it works in your setup
  
    The Hardware
  
    - Uses Samsung NVMe SSDs (the fast storage drives)
    - Spreads data across 3 copies on different computers for safety
    - If one computer dies, your data is still safe on the other two
  
    Three Types of Storage
  
    1. ceph-block (Most common)
      - Like having a virtual hard drive attached to one app at a time
      - Used by: Plex, games, Prometheus monitoring
    2. ceph-filesystem
      - Like a shared folder multiple apps can access
      - Used by: AI models, shared configs
    3. ceph-bucket
      - Like Amazon S3 storage for files/objects
      - Available but less commonly used
  
    What Uses It
  
    Your cluster stores about 400GB of data:
    - Plex: 50GB of cache
    - AI stuff (Ollama): 100GB of models
    - Download apps (*arr stack): 5GB each
    - Game servers: 5-15GB each
    - Monitoring: 75GB of metrics
  
    Backup System
  
    - 34 of your apps automatically backup every hour
    - Keeps: 24 hourly, 10 daily, 5 weekly, 3 monthly backups
    - Stores backups both locally and in cloud (Cloudflare)
  
    Web Interface
  
    - Dashboard at rook.jory.dev shows storage health
    - Password stored securely in 1Password
  
    Why it's good
  
    - Reliable: Data copied 3 times, survives hardware failures
    - Fast: Uses enterprise SSDs with compression
    - Automatic: Manages itself, backs up automatically
    - Flexible: Different storage types for different needs
  
    Bottom Line
  
    You've built enterprise-grade storage that automatically keeps your data safe, fast, and backed up -
    all managed through code instead of clicking around in web interfaces.