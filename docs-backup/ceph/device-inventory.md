# Ceph Storage Device Inventory

*Generated: 2025-01-09*  
*Part of Ceph bootstrap objective 1.2*

## Overview

Each MS-01 node contains 3 NVMe drives total. The 500GB drive serves as the system disk, while the two 1TB drives are available for Ceph storage.

## Hardware Configuration

### Node: k8s-1 (192.168.1.98)
| Device | Size | Model | Serial | WWID | Usage |
|--------|------|-------|--------|------|-------|
| nvme0n1 | 1.0 TB | WD_BLACK SN7100 1TB | 251021802190 | eui.e8238fa6bf530001001b448b4d7a7f99 | **Available for Ceph** |
| nvme1n1 | 1.0 TB | WD_BLACK SN7100 1TB | 251021802186 | eui.e8238fa6bf530001001b448b4d7a7f6f | **Available for Ceph** |
| nvme2n1 | 500 GB | CT500P3SSD8 | 24304A343650 | eui.000000000000000100a075244a343650 | System Disk (Talos) |

### Node: k8s-2 (192.168.1.99)
| Device | Size | Model | Serial | WWID | Usage |
|--------|------|-------|--------|------|-------|
| nvme0n1 | 1.0 TB | WD_BLACK SN7100 1TB | 251021802221 | eui.e8238fa6bf530001001b448b4d7a7f78 | **Available for Ceph** |
| nvme1n1 | 1.0 TB | WD_BLACK SN7100 1TB | 251021801877 | eui.e8238fa6bf530001001b448b4d7a7c16 | **Available for Ceph** |
| nvme2n1 | 500 GB | CT500P3SSD8 | 24304A23D2F0 | eui.000000000000000100a075244a23d2f0 | System Disk (Talos) |

### Node: k8s-3 (192.168.1.100)
| Device | Size | Model | Serial | WWID | Usage |
|--------|------|-------|--------|------|-------|
| nvme0n1 | 1.0 TB | WD_BLACK SN7100 1TB | 251021800405 | eui.e8238fa6bf530001001b448b4d7a7236 | **Available for Ceph** |
| nvme1n1 | 1.0 TB | WD_BLACK SN7100 1TB | 251021801882 | eui.e8238fa6bf530001001b448b4d7a7c10 | **Available for Ceph** |
| nvme2n1 | 500 GB | CT500P3SSD8 | 24304A23705F | eui.000000000000000100a075244a23705f | System Disk (Talos) |

## Ceph Storage Summary

- **Total Nodes**: 3
- **Devices per Node**: 2 (nvme0n1, nvme1n1)
- **Total Ceph Devices**: 6 NVMe drives
- **Individual Drive Size**: 1.0 TB each
- **Raw Storage Capacity**: 6.0 TB
- **Expected Usable Capacity**: ~2.0 TB (with 3-way replication)

## Device Preparation Status

### Current State
- ✅ **6 NVMe devices identified** (2 per node)
- ✅ **Talos patches consolidated** - Storage patches updated to Ceph-ready configuration
- ✅ **Legacy configuration archived** - Original mounts backed up for rollback if needed

### Device Selection Strategy
1. **Consistent naming**: Use nvme0n1 and nvme1n1 on all nodes
2. **Hardware uniformity**: All devices are identical WD_BLACK SN7100 1TB
3. **No conflicts**: System disk (nvme2n1) is different model/size

## Next Steps

1. ✅ **Talos patches created**: Storage patches consolidated and Ceph-ready
2. **Apply configuration**: When ready for Ceph, regenerate and apply Talos config
3. **Validate readiness**: Confirm devices are unmounted and ready for Ceph OSDs

## Device Paths for Ceph Configuration

When configuring Rook-Ceph, use these device paths:

```yaml
storage:
  devices:
    - name: "/dev/nvme0n1"
    - name: "/dev/nvme1n1"
```

**Note**: Paths are consistent across all nodes due to identical hardware configuration.