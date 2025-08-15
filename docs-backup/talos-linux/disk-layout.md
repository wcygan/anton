# Talos Node Disk Layout

This document describes the actual disk layout for each node in the Anton cluster, discovered during Ceph storage troubleshooting.

## Overview

Each node has 3 NVMe drives, but the device naming differs between nodes. This is important for Rook-Ceph configuration.

## Node Disk Configurations

### k8s-1 (192.168.1.98)
- **nvme0n1**: 1.0 TB WD_BLACK SN7100 (Serial: 251021802190) - **Ceph OSD**
- **nvme1n1**: 1.0 TB WD_BLACK SN7100 (Serial: 251021802186) - **Ceph OSD**
- **nvme2n1**: 500 GB CT500P3SSD8 (Serial: 24304A343650) - **System disk**

### k8s-2 (192.168.1.99)
- **nvme0n1**: 1.0 TB WD_BLACK SN7100 (Serial: 251021801877) - **Ceph OSD**
- **nvme1n1**: 1.0 TB WD_BLACK SN7100 (Serial: 251021802221) - **Ceph OSD**
- **nvme2n1**: 500 GB CT500P3SSD8 (Serial: 24304A23D2F0) - **System disk**

### k8s-3 (192.168.1.100) ⚠️ Different Layout
- **nvme0n1**: 1.0 TB WD_BLACK SN7100 (Serial: 251021801882) - **Ceph OSD**
- **nvme1n1**: 500 GB CT500P3SSD8 (Serial: 24304A23705F) - **System disk**
- **nvme2n1**: 1.0 TB WD_BLACK SN7100 (Serial: 251021800405) - **Ceph OSD**

## Important Notes

1. **k8s-3 has a different disk layout**: The second 1TB drive is `nvme2n1` instead of `nvme1n1`
2. This affects Rook-Ceph configuration which must explicitly list the correct devices
3. The system disks are all 500GB CT500P3SSD8 drives but on different device names

## Verification Commands

To verify disk layout on any node:

```bash
# Using talosctl
talosctl get disks -n <node-ip>

# Example for k8s-3
talosctl get disks -n 192.168.1.100
```

## Rook-Ceph Configuration

The Ceph cluster configuration must account for the different device names:

```yaml
storage:
  useAllDevices: false
  deviceFilter: "^nvme[012]n1$"  # Matches nvme0n1, nvme1n1, and nvme2n1
  nodes:
    - name: "k8s-1"
      devices:
        - name: "nvme0n1"
        - name: "nvme1n1"
    - name: "k8s-2"
      devices:
        - name: "nvme0n1"
        - name: "nvme1n1"
    - name: "k8s-3"
      devices:
        - name: "nvme0n1"
        - name: "nvme2n1"  # Different from other nodes!
```

## Troubleshooting

### Symptom: Missing OSD on k8s-3
If Ceph shows only 5 OSDs instead of 6, check:
1. The CephCluster resource lists `nvme2n1` for k8s-3 (not nvme1n1)
2. The deviceFilter regex includes "2": `^nvme[012]n1$`
3. OSD prepare job logs for device discovery errors

### Symptom: OSD prepare job skips devices
Check logs for messages like:
```
skipping device "nvme2n1" that does not match the device filter/list
```

This indicates the device configuration doesn't match the actual hardware.

## Historical Context

This disk layout difference was discovered during Ceph storage recovery when:
1. Initial deployment had 5 OSDs instead of expected 6
2. Investigation revealed k8s-3's second 1TB drive was on nvme2n1
3. Rook configuration was hardcoded for nvme1n1 on all nodes
4. Fix required updating the explicit device list for k8s-3

## References

- [Talos Disk Management](https://www.talos.dev/v1.10/reference/configuration/v1alpha1/config/#disk)
- [Rook Storage Selection](https://rook.io/docs/rook/latest-release/CRDs/Cluster/ceph-cluster-crd/#storage-selection-settings)