---
name: longhorn-talos
description: Canonical Talos gotchas for running Longhorn in anton.
---

# Longhorn on Talos

Canonical: https://longhorn.io/docs/1.11.1/advanced-resources/os-distro-specific/talos-linux-support/

This is the shared Talos reference — `longhorn-volume-ops` and `longhorn-backup-dr` link here instead of duplicating.

## Required Talos system extensions

Installed via the Image Factory schematic (currently `445a99db4002e6127e7f6e2a96377ac2c06d0de52f7a186b5536c0ac2f2a2ece`):

- `siderolabs/iscsi-tools` — iSCSI initiator; Longhorn's data path is iSCSI.
- `siderolabs/util-linux-tools` — `nsenter`, `blkid`, etc. used by the longhorn-driver CSI pod.

Both are in anton's schematic. If you rebuild the schematic, verify both extensions are still selected before promoting the new installer URL.

## Kubelet bind mounts

Longhorn writes under `/var/lib/longhorn` by default — on Talos that path is read-only. Anton redirects via kubelet `extraMounts`:

```yaml
machine:
  kubelet:
    extraMounts:
      - destination: /var/mnt/longhorn-1
        type: bind
        source: /var/mnt/longhorn-1
        options: [bind, rshared, rw]
```

`rshared` is load-bearing. Without it, the mount is not propagated into the kubelet's mount namespace and longhorn-manager fails health checks.

## `preUpgradeChecker` must stay disabled

The upstream `preUpgradeChecker` Job writes under the root filesystem and fails on Talos' read-only rootfs. Always disable in the HelmRelease:

```yaml
preUpgradeChecker:
  jobEnabled: false
  upgradeVersionCheck: false
```

## Upgrade trap: data preservation

Talos upgrades wipe `/var/lib/*` by default unless a path is declared as a user volume. Because anton's Longhorn data lives at `/var/mnt/longhorn-{1,2}` and is declared via `UserVolumeConfig` with `disk.serial` selectors, Talos preserves it across upgrades. **Do not move the mount path off `/var/mnt/` or drop the UserVolume declaration** — that turns an upgrade into a data loss event.

## Recovery

If a node's Longhorn disks aren't registering after a Talos reconfigure:

1. `talosctl -n <node> ls /var/mnt/` — confirm the directory exists and is mounted.
2. `talosctl -n <node> get userVolumeStatus` — confirm the user volume is mounted with the expected filesystem.
3. `kubectl get nodes.longhorn.io -n storage <node> -o yaml` — check `status.diskStatus`.
4. If Longhorn registered the node before the mount was available, kubectl-patch the disk in (see [disk-model](disk-model.md)).
