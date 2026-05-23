---
name: longhorn-node-ops
description: Add or remove Longhorn disks on a Talos node, drain/evict replicas before maintenance, fix disk-routing mismatches, and integrate a replaced node into the Longhorn topology. Use for disk swaps, pre-reboot eviction, or when a node's longhorn disks don't match the Talos annotation. Pairs with add-or-replace-node for the Talos side.
---

# longhorn-node-ops

Disk and node-level Longhorn operations on anton.

## Talos truth lives in `talconfig.yaml`

The GitOps source of truth for Longhorn disk topology is the Talos per-node patch:

- `machine.kubelet.extraMounts` — bind-mounts each `/var/mnt/longhorn-N` into the kubelet namespace with `rshared, rw`.
- `machine.nodeLabels.node.longhorn.io/create-default-disk: "config"` — opts the node into Longhorn's `createDefaultDiskLabeledNodes: true` gate.
- `machine.nodeAnnotations.node.longhorn.io/default-disks-config` — JSON array of disks Longhorn should register.

**Load-bearing gotcha:** Longhorn only reads `default-disks-config` at **first node registration**. Changes after that are not a live feedback loop — the annotation remains GitOps truth for future re-registration, but changing it on an already-registered node requires a kubectl patch against `nodes.longhorn.io/<node>` to take effect.

## Anton topology

- k8s-1: 2× WD_BLACK at `/var/mnt/longhorn-{1,2}`
- k8s-2: 1× WD_BLACK at `/var/mnt/longhorn-1` (second NVMe slot empty — followup tracked in `context/hardware.md`)
- k8s-3: 2× WD_BLACK at `/var/mnt/longhorn-{1,2}`

## Recipes

### Add a second NVMe to k8s-2 (when hardware returns)

1. Install the drive, boot the node, find the serial: `talosctl -n k8s-2 get discoveredvolumes`.
2. Edit `talos/talconfig.yaml` under the k8s-2 entry:
   - Add a `UserVolume` `longhorn-2` with the `disk.serial` selector.
   - Add the `/var/mnt/longhorn-2` bind mount under `machine.kubelet.extraMounts`.
   - Append `{"path":"/var/mnt/longhorn-2","allowScheduling":true}` to `default-disks-config`.
3. `task talos:generate-config && task talos:apply-node IP=192.168.1.99 MODE=auto`.
4. Confirm the mount: `talosctl -n k8s-2 ls /var/mnt/`.
5. Because Longhorn already has k8s-2 registered with one disk, the annotation change is not picked up. kubectl-patch `nodes.longhorn.io/k8s-2` to add the new disk (see [disk-model](references/disk-model.md)).

### Evict replicas before long node maintenance

```sh
kubectl annotate nodes.longhorn.io/<node> -n storage \
  node.longhorn.io/allow-scheduling=false \
  node.longhorn.io/eviction-requested=true --overwrite
```

Wait for:

```sh
kubectl get replicas.longhorn.io -n storage -o json | jq '[.items[] | select(.spec.nodeID=="<node>")] | length'
```

to reach `0`, then reboot. Un-evict after: set both annotations back. For short reboots (within `staleReplicaTimeout`) eviction is not required — cordon + reboot is enough.

### Fix a disk-routing mismatch

Two-pass kubectl patch if Longhorn registered the wrong disk (e.g. the 500 GB Talos EPHEMERAL default instead of the declared NVMes):

1. Patch 1 — add new disks + disable the wrong one + request eviction on it.
2. Wait for replica count on the wrong disk to reach zero.
3. Patch 2 — remove the wrong-disk key via JSON merge null.

Full patch JSON and reason behind the two-pass flow: [disk-model](references/disk-model.md).

### Integrate a replaced node

After `add-or-replace-node` finishes on the Talos side the new node starts fresh — no existing `nodes.longhorn.io` entry — so the `default-disks-config` annotation is read correctly at first registration. Verify with `kubectl get nodes.longhorn.io -n storage -o wide` and check `status.diskStatus` for every expected disk.

## References

- [Talos + Longhorn](references/talos.md) — **canonical home** for Talos gotchas (extensions, kubelet mounts, preUpgradeChecker, upgrade traps). `longhorn-volume-ops` and `longhorn-backup-dr` link here.
- [Disk model](references/disk-model.md) — how Longhorn disks/nodes/replicas fit together; the two-pass kubectl patches
- [Node maintenance best practices](references/best-practices-node-maintenance.md)
