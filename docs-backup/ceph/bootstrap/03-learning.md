# Ceph Learning Plan for Anton Homelab

**Purpose**: Structured learning path to master Ceph concepts before production deployment  
**Timeline**: 4-6 weeks self-paced study  
**Prerequisites**: Basic Kubernetes storage knowledge (PV, PVC, StorageClass)

## Learning Objectives

By completing this learning plan, you will:
- Understand Ceph's distributed storage architecture
- Master the three storage types (block, file, object)
- Learn Rook's operator-based deployment model
- Gain operational knowledge for maintaining Ceph clusters
- Prepare for production deployment decisions

## Module 1: Foundations (Week 1)

### 1.1 Core Concepts
**Goal**: Understand what Ceph is and why it exists

#### Study Topics:
- **Distributed Storage Fundamentals**
  - CAP theorem and consistency models
  - Replication vs erasure coding
  - Data locality and network considerations

- **Ceph Architecture Overview**
  - RADOS (Reliable Autonomic Distributed Object Store)
  - Object storage as foundation for block/file
  - Scale-out vs scale-up storage

#### Key Terms to Master:
- **Object**: Base storage unit in Ceph
- **Pool**: Logical partition for storing objects
- **Placement Group (PG)**: Subset of objects for distribution
- **CRUSH Map**: Algorithm for data placement

#### Hands-On Exercise:
```bash
# Conceptual exercise - draw a diagram showing:
# 1. How a 1GB file gets split into objects
# 2. How those objects distribute across 3 nodes
# 3. What happens when a node fails
```

### 1.2 Ceph Components Deep Dive
**Goal**: Understand each daemon's role

#### Study Topics:
- **Monitor (MON)**
  - Maintains cluster maps (OSD, MON, PG, CRUSH)
  - Consensus using Paxos
  - Quorum requirements (why odd numbers)

- **OSD (Object Storage Daemon)**
  - One per disk/device
  - Handles data storage, replication, recovery
  - Heartbeat and peering

- **Manager (MGR)**
  - Metrics, monitoring, orchestration
  - Dashboard and API endpoints
  - Module system (prometheus, dashboard, etc.)

#### Review Questions:
1. Why do you need at least 3 MONs for production?
2. What happens during OSD failure and recovery?
3. How do MONs maintain consistency?

## Module 2: Storage Types (Week 2)

### 2.1 Block Storage (RBD)
**Goal**: Master Ceph's block storage capabilities

#### Study Topics:
- **RBD Architecture**
  - How block devices map to objects
  - Striping and performance implications
  - Thin provisioning and snapshots

- **Use Cases**
  - Database storage
  - VM disks
  - Kubernetes PVCs (RWO)

#### Key Concepts:
- **Image**: A block device in Ceph
- **Snapshot**: Point-in-time copy
- **Clone**: Writable snapshot copy
- **Mirroring**: Cross-cluster replication

#### Lab Exercise:
```yaml
# Create a conceptual RBD pool design:
pool:
  name: rbd-nvme
  replication: 3
  min_size: 2
  compression: aggressive
  autoscale: true
```

### 2.2 File Storage (CephFS)
**Goal**: Understand shared filesystem capabilities

#### Study Topics:
- **CephFS Architecture**
  - Metadata Server (MDS) role
  - Directory fragmentation
  - Client caching (caps system)

- **MDS Concepts**
  - Active/standby configuration
  - Multiple active MDS scaling
  - Metadata pool vs data pool

#### Key Features:
- **Snapshots**: Directory-level snapshots
- **Quotas**: Directory size limits
- **Layouts**: Custom data pool per directory

#### Use Cases:
- Shared application data
- Home directories
- Media storage
- AI/ML datasets

### 2.3 Object Storage (RGW)
**Goal**: Learn S3-compatible object storage

#### Study Topics:
- **RADOS Gateway Architecture**
  - RESTful API frontend
  - S3 and Swift compatibility
  - Multi-tenancy and users

- **Advanced Features**
  - Lifecycle policies
  - Versioning
  - Multipart uploads
  - Bucket policies

#### Integration Points:
- Backup targets (Velero)
- Static website hosting
- Data archival
- Application object storage

## Module 3: Rook Orchestration (Week 3)

### 3.1 Operator Pattern
**Goal**: Understand Kubernetes operators

#### Study Topics:
- **Operator Concepts**
  - Custom Resource Definitions (CRDs)
  - Control loops and reconciliation
  - Declarative configuration

- **Rook Architecture**
  - Operator deployment model
  - CSI driver integration
  - Automatic failure handling

### 3.2 Rook CRDs Deep Dive
**Goal**: Master Rook's custom resources

#### Key CRDs to Study:
1. **CephCluster**
   - Defines entire Ceph deployment
   - Node placement and affinity
   - Resource specifications

2. **CephBlockPool**
   - Configures RBD pools
   - Replication settings
   - Device classes

3. **CephFilesystem**
   - Creates CephFS instances
   - MDS configuration
   - Multiple filesystems

4. **CephObjectStore**
   - Deploys RGW instances
   - Configures S3 endpoints
   - Zone and realm setup

#### Practice Exercise:
```yaml
# Write a complete CephCluster spec covering:
# - 3 node deployment
# - Resource limits
# - Placement constraints
# - Monitoring enabled
```

### 3.3 CSI Integration
**Goal**: Understand storage provisioning

#### Study Topics:
- **CSI Architecture**
  - Provisioner, attacher, snapshotter
  - Dynamic provisioning workflow
  - Volume lifecycle

- **StorageClass Design**
  - Parameters for each storage type
  - Reclaim policies
  - Volume expansion

## Module 4: Data Flow & Algorithms (Week 4)

### 4.1 CRUSH Algorithm
**Goal**: Master data placement logic

#### Study Topics:
- **CRUSH Fundamentals**
  - Hierarchical cluster map
  - Placement rules
  - Failure domains

- **CRUSH Map Structure**
  - Buckets (root, datacenter, rack, host)
  - Device classes (hdd, ssd, nvme)
  - Rule definitions

#### Key Concepts:
- **Failure Domain**: Isolation boundary
- **Device Class**: Storage tier separation
- **Primary Affinity**: Read performance optimization

### 4.2 Data Flow Patterns
**Goal**: Understand I/O paths

#### Study Topics:
- **Write Path**
  1. Client � Primary OSD
  2. Primary � Replica OSDs
  3. Acknowledgment flow

- **Read Path**
  - Primary OSD selection
  - Read balancing
  - Cache tiers (deprecated but conceptual)

- **Recovery Flow**
  - Degraded vs misplaced objects
  - Backfill vs recovery
  - Priority and throttling

## Module 5: Operations & Monitoring (Week 5)

### 5.1 Health Management
**Goal**: Interpret cluster health

#### Study Topics:
- **Health States**
  - HEALTH_OK, HEALTH_WARN, HEALTH_ERR
  - Common warnings and fixes
  - PG states (active, clean, etc.)

- **Monitoring Metrics**
  - Cluster capacity and usage
  - IOPS and throughput
  - Latency percentiles

#### Key Commands:
```bash
# Essential health commands to understand:
ceph status
ceph health detail
ceph osd tree
ceph df
rados df
```

### 5.2 Performance Tuning
**Goal**: Optimize for workloads

#### Study Topics:
- **Pool Tuning**
  - PG calculations
  - Compression settings
  - EC profiles

- **Network Optimization**
  - Public vs cluster networks
  - Jumbo frames
  - Network bandwidth planning

- **Hardware Considerations**
  - NVMe vs SSD vs HDD
  - Memory requirements
  - CPU for compression/EC

### 5.3 Maintenance Operations
**Goal**: Safe cluster maintenance

#### Study Topics:
- **Node Maintenance**
  - Setting OSD flags (noout, norebalance)
  - Draining nodes
  - Rolling upgrades

- **Disaster Recovery**
  - Backup strategies
  - Snapshot management
  - Cross-cluster mirroring

## Module 6: Production Readiness (Week 6)

### 6.1 Deployment Planning
**Goal**: Design production architecture

#### Exercises:
1. **Capacity Planning**
   - Calculate raw vs usable capacity
   - Growth projections
   - Performance requirements

2. **Failure Scenario Planning**
   - Node failure impact
   - Network partition handling
   - Recovery time objectives

### 6.2 Security Considerations
**Goal**: Secure Ceph deployment

#### Study Topics:
- **Authentication**
  - CephX protocol
  - User and key management
  - Kubernetes secret integration

- **Encryption**
  - Encryption at rest
  - Encryption in transit
  - Key management

### 6.3 Integration Patterns
**Goal**: Connect applications to Ceph

#### Study Topics:
- **Application Patterns**
  - Database on RBD
  - Shared data on CephFS
  - Backups to RGW

- **Kubernetes Patterns**
  - StatefulSet storage
  - Job scratch space
  - Persistent logging

## Practical Labs Setup

### Option 1: Rook Test Cluster
```bash
# Use Rook's test cluster (single node)
git clone https://github.com/rook/rook.git
cd rook/deploy/examples
kubectl create -f crds.yaml -f common.yaml -f operator.yaml
kubectl create -f cluster-test.yaml
```

### Option 2: Vagrant Multi-Node
```ruby
# Vagrantfile for 3-node test cluster
Vagrant.configure("2") do |config|
  (1..3).each do |i|
    config.vm.define "ceph-#{i}" do |node|
      node.vm.box = "ubuntu/jammy64"
      node.vm.network "private_network", ip: "192.168.50.#{10+i}"
      node.vm.disk :disk, size: "20GB", name: "osd-#{i}"
    end
  end
end
```

### Option 3: Kind with Local Volumes
```yaml
# kind-config.yaml for testing
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraMounts:
  - hostPath: /tmp/ceph1
    containerPath: /var/lib/rook
- role: worker
  extraMounts:
  - hostPath: /tmp/ceph2
    containerPath: /var/lib/rook
```

## Assessment Checkpoints

### Module 1 Check
- [ ] Can explain RADOS and object storage foundation
- [ ] Understand all daemon types and their roles
- [ ] Know why Ceph needs odd number of MONs

### Module 2 Check
- [ ] Differentiate RBD, CephFS, and RGW use cases
- [ ] Understand MDS role in CephFS
- [ ] Know when to use each storage type

### Module 3 Check
- [ ] Can write Rook CRDs from memory
- [ ] Understand operator reconciliation
- [ ] Know CSI provisioning workflow

### Module 4 Check
- [ ] Can explain CRUSH placement decisions
- [ ] Understand failure domains
- [ ] Know data flow for reads/writes

### Module 5 Check
- [ ] Can interpret cluster health output
- [ ] Know basic troubleshooting steps
- [ ] Understand maintenance procedures

### Module 6 Check
- [ ] Can design a production cluster
- [ ] Understand security implications
- [ ] Ready to deploy in homelab

## Recommended Resources

### Official Documentation
1. [Ceph Documentation](https://docs.ceph.com/)
2. [Rook Documentation](https://rook.io/docs/)
3. [Ceph Architecture Paper](https://ceph.com/assets/pdfs/weil-rados-pdsw07.pdf)

### Books
1. "Learning Ceph" by Anthony D'Atri
2. "Mastering Ceph" by Nick Fisk
3. "Ceph Cookbook" by Vikhyat Umrao

### Video Courses
1. [Ceph Fundamentals](https://www.youtube.com/playlist?list=PLrBUGiINAakN87iSX3MkZsDD07Q8k_BPp)
2. [Rook Deep Dive](https://www.youtube.com/watch?v=yqnb-ZAnLH0)
3. [CNCF Webinars on Rook](https://www.cncf.io/webinars/)

### Community Resources
1. [Ceph Mailing Lists](https://ceph.io/community/)
2. [Rook Slack Channel](https://rook-io.slack.com/)
3. [Reddit r/ceph](https://www.reddit.com/r/ceph/)

## Learning Timeline

### Accelerated Path (2-3 weeks)
- Focus on Modules 1, 2, and 3
- Skip deep algorithm details
- Use test cluster for hands-on

### Standard Path (4-6 weeks)
- Complete all modules in order
- Do all exercises and labs
- Build test implementations

### Deep Mastery (8-12 weeks)
- Add production scenarios
- Contribute to documentation
- Deploy multiple test clusters

## Next Steps After Learning

1. **Build Test Cluster**
   - Deploy Rook in VM environment
   - Test all three storage types
   - Practice failure scenarios

2. **Design Homelab Architecture**
   - Apply learning to your specific needs
   - Document design decisions
   - Plan migration strategy

3. **Start Small**
   - Begin with block storage only
   - Add complexity gradually
   - Monitor and learn from metrics

## Module 7: Talos Linux Integration (Bonus Week)

### 7.1 Talos-Specific Considerations
**Goal**: Understand Ceph on immutable Linux

#### Study Topics:
- **Talos Architecture Impact**
  - Immutable OS implications
  - API-driven configuration
  - No SSH access patterns

- **Kernel Module Management**
  - RBD module verification
  - Machine config extensions
  - Kernel version requirements

#### Key Differences:
- **Disk Management**
  - No manual partitioning
  - Machine config for disk setup
  - Automated wiping procedures

- **Maintenance Patterns**
  - API-based node management
  - Coordinated upgrades
  - Health monitoring via kubectl

### 7.2 Anton Homelab Specifics
**Goal**: Apply learning to your environment

#### Hardware Mapping:
```yaml
# Your specific setup
nodes:
  k8s-1:
    ip: 192.168.1.98
    disks: [nvme0n1, nvme2n1]
    capacity: 2TB
  k8s-2:
    ip: 192.168.1.99
    disks: [nvme0n1, nvme1n1]
    capacity: 2TB
  k8s-3:
    ip: 192.168.1.100
    disks: [nvme0n1, nvme2n1]
    capacity: 2TB
```

#### Migration Scenarios:
1. **Current Apps Analysis**
   - PostgreSQL databases (~20Gi)
   - DragonflyDB cache (1Gi)
   - Airflow development (10-20Gi)

2. **Future Workloads**
   - AI model storage (CephFS)
   - Backup repository (RGW)
   - Production databases (RBD)

### 7.3 Practical Exercises
**Goal**: Hands-on with homelab context

#### Exercise 1: Design Your Pools
```yaml
# Design pools for your workloads
pools:
  - name: nvme-databases
    type: replicated
    size: 3
    device-class: nvme
    compression: lz4
    
  - name: nvme-cache
    type: replicated
    size: 2  # Less critical
    device-class: nvme
    compression: none
    
  - name: bulk-storage
    type: erasure-coded
    profile: 4+2  # Future expansion
    compression: zstd
```

#### Exercise 2: Capacity Planning
```bash
# Calculate for your setup
# Raw: 6TB (6x 1TB NVMe)
# Usable with 3-replica: ~2TB
# Usable with EC 4+2: ~4TB

# Current usage: 120Gi
# Growth rate: ??/month
# Time until Ceph needed: ??
```

#### Exercise 3: Talos Machine Config
```yaml
# Plan machine config patches
machine:
  disks:
    - device: /dev/nvme0n1
      partitions: []  # Wipe for Ceph
    - device: /dev/nvme2n1
      partitions: []  # Wipe for Ceph
```

## Quick Reference Cards

### Ceph Component Cheat Sheet
```
MON: Brain (cluster state)     - Need 3+ for quorum
MGR: Manager (metrics/API)     - Active/standby pair
OSD: Storage (one per disk)    - Handles actual data
MDS: Metadata (CephFS only)    - Manages file metadata
RGW: Gateway (S3/Swift API)    - Object storage interface
```

### Storage Type Decision Tree
```
Need block storage for database?          → RBD (ceph-block)
Need shared filesystem for pods?          → CephFS (ceph-filesystem)
Need S3-compatible object storage?        → RGW (ceph-objectstore)
Need high IOPS single-pod access?         → RBD on NVMe pool
Need bulk storage with erasure coding?    → RGW with EC pool
```

### Common Ceph Commands
```bash
# Health and status
ceph -s                     # Quick status
ceph health detail          # Detailed health
ceph osd tree              # OSD hierarchy

# Performance monitoring
ceph osd pool stats        # Pool statistics
rados bench -p <pool> 10 write  # Benchmark

# Maintenance
ceph osd set noout         # Prevent rebalancing
ceph osd unset noout       # Resume normal ops
```

### Rook Troubleshooting
```bash
# Check operator
kubectl -n rook-ceph logs -l app=rook-ceph-operator

# Check cluster status
kubectl -n rook-ceph get cephcluster

# Access toolbox
kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- bash

# Force mon failover
kubectl -n rook-ceph delete pod -l mon=a
```

## Learning Validation Projects

### Project 1: Blog Platform Storage
Design storage for a blog platform with:
- PostgreSQL database (RBD)
- Image uploads (CephFS)
- Static site backups (RGW)
- Calculate capacity for 1000 posts

### Project 2: AI/ML Pipeline
Design storage for ML workloads:
- Training data lake (CephFS)
- Model checkpoints (RBD snapshots)
- Result archives (RGW lifecycle)
- Performance requirements

### Project 3: Disaster Recovery
Plan DR strategy including:
- Cross-region replication
- Snapshot schedules
- RTO/RPO targets
- Backup verification

## Conclusion

This learning plan provides a structured path from Ceph novice to production-ready operator. Focus on understanding concepts before implementation, and always test in isolated environments before touching production systems. Remember: Ceph is powerful but complex - patience and systematic learning will pay dividends in operational excellence.

The addition of Talos-specific content and practical exercises will help you apply theoretical knowledge to your actual homelab environment. Start with the accelerated path if you need quick results, but invest in the full curriculum for long-term operational success.