# Rook + Ceph

**TL;DR**: We're using Rook Ceph to provide unified storage for the Anton homelab cluster:
- **Block Storage** (RBD) - For databases and single-pod applications
- **File Storage** (CephFS) - For shared data across multiple pods
- **Object Storage** (S3) - For backups and cloud-native applications

**Strategy**: Hybrid Progressive approach - start with block storage only, add filesystem and object storage as needed.

**Status**: Planning phase - see `bootstrap/` directory for implementation plans.
