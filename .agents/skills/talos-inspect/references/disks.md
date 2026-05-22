# Disk inventory and storage inspection

Read-only storage inspection at the Talos layer. Good for: `add-or-replace-node` pre-flight, capacity planning, NVMe health triage, install-disk selection, volume sanity. All commands use the shape from `SKILL.md`:

```sh
TALOS="talosctl --talosconfig ./talos/clusterconfig/talosconfig"
NODES="k8s-1,k8s-2,k8s-3"
```

## Fleet-wide inventory

```sh
$TALOS -e k8s-1 -n $NODES get disks                  # block devices: name, size, model, serial
$TALOS -e k8s-1 -n $NODES get systemdisk             # which disk holds the Talos install
$TALOS -e k8s-1 -n $NODES get discoveredvolumes      # detected volumes (partitions, filesystems)
$TALOS -e k8s-1 -n $NODES get volumemountstatus      # what is actually mounted where
```

What to look for:

| Query | Healthy output |
| --- | --- |
| `get disks` | All three nodes report the same install disk model/size. Serials differ (expected). No `ReadOnly` flag set. |
| `get systemdisk` | Exactly one disk flagged; matches the one named in `talos/talconfig.yaml` under `installDiskSelector`. |
| `get discoveredvolumes` | `META`, `STATE`, `EPHEMERAL` partitions present on the install disk. |
| `get volumemountstatus` | `EPHEMERAL` mounted at `/var`; no errors. |

## Picking an install disk (pre `add-or-replace-node`)

Before joining a new node, capture the serial of the disk you intend to install onto. Serials are safe to commit — they are not secrets.

```sh
# From a Talos maintenance-mode boot on the new hardware:
talosctl -n <new-node-ip> --insecure get disks
```

Use the serial (preferred) in `installDiskSelector:` in `talos/talconfig.yaml`. Model-only selection is possible but fragile when you have two identical drives.

## NVMe / storage health signals

Talos doesn't ship `smartctl` in the default image. You have two options:

1. **Kernel signals** (always available). Grep `dmesg` for hardware-level errors:
   ```sh
   $TALOS -n k8s-1 dmesg | rg -i 'nvme|ata|scsi|i/o error|medium error|bad block|timeout'
   ```
   Patterns that matter:

   - `nvme: I/O timeout` / `nvme: controller is down` — drive about to fail, or PCIe issue. Cross-check `etcd` slow-apply logs in `references/health.md`.
   - `Buffer I/O error on device` — hardware fault. Do not assume transient.
   - `EXT4-fs error` — filesystem corruption. Not a recovery you run from here.

2. **SMART via extension** (optional). The `util-linux-tools` and `iscsi-tools` extensions in the Talos factory provide richer disk tooling. Adding extensions is not in this skill's scope — it requires a new schematic ID and a rolling Talos upgrade.

## Disk pressure and free space

```sh
$TALOS -n k8s-1 read /proc/mounts                    # raw mount table
$TALOS -n k8s-1 usage /var                           # space used by path
$TALOS -n k8s-1 usage /var/lib/containerd            # images + snapshots
$TALOS -n k8s-1 usage /var/lib/kubelet               # kubelet pod volumes
```

The `EPHEMERAL` partition holds `/var` and is the most common culprit for disk pressure. Top three causes:

1. **Runaway container images** under `/var/lib/containerd`. Kubelet image GC is controlled by `imageGCHighThresholdPercent` in the kubelet config — read via `get machineconfig`, do not edit from here.
2. **Orphaned CSI volumes** under `/var/lib/kubelet/pods/*/volumes/`. Usually a sign that a stateful pod failed to clean up; fix at the app / Flux layer.
3. **Log floods** from a crash-looping pod writing to `/var/log/pods/*`.

When a node reports `DiskPressure` in `kubectl describe node`, this is where to look first.

## Container image storage (read-only triage)

```sh
$TALOS -n k8s-1 containers                           # containers + image IDs on this node
kubectl get pods -A -o jsonpath='{..image}' | tr ' ' '\n' | sort -u | wc -l
```

Expect the number of unique images in-use to match roughly what `/var/lib/containerd` holds. A big divergence means old images are pinned; image GC needs a closer look (kubelet config, not this skill).

## Rook / Ceph disks (future-proofing)

The cluster previously ran Rook-Ceph and may again. When OSDs return:

- Extra disks appear under `get disks` as `rbd*` entries (Ceph RBD clients) and as `loop` devices where bluestore is layered on files.
- OSD-layer health belongs in a dedicated Rook/Ceph skill — not this one. This skill stops at the block device.

Until Rook is back, the three nodes should each expose only their single install disk plus whatever `rbd` clients mount from an external target (none at present).

## Docs — WebFetch when unsure

- `https://docs.siderolabs.com/talos/v1.12/learn-more/resources` — resource schemas (`Disks`, `DiscoveredVolumes`, `VolumeMountStatus`, `SystemDisk`)
- `https://docs.siderolabs.com/talos/v1.12/talos-guides/install/` — install disk selection semantics
