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

## Establish current disk state

Node disk counts, models, serials, and free slots change over time. Do not infer current hardware from old plans or prior node-specific examples. Before authoring a Talos disk patch or Longhorn node patch, inspect the current `talos/talconfig.yaml`, generated config, Talos discovered volumes, node annotations, Longhorn `nodes.longhorn.io` objects, and replica placement. Record disagreements as separate observations; preserve uncertainty until the exact disk identity is confirmed.

After adding a disk to an already-registered node, expect Longhorn not to reread `default-disks-config`; use the two-pass disk procedure in [disk-model](references/disk-model.md) only after confirming the intended disk and exact Longhorn node object.

## Recipes

### Add a disk to a node

1. Inspect the target node's discovered volumes and identify the disk by a stable identifier, not device order.
2. Edit `talos/talconfig.yaml` for that node: add a `UserVolume` with the confirmed disk selector, its kubelet bind mount, and the intended `default-disks-config` entry.
3. Generate and review the Talos configs. Apply only after following the node-operation approval and quorum gates.
4. Confirm the mount and Talos state. If the node is already registered in Longhorn, add the disk to its Longhorn node resource after checking replica placement.

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

Use the two-pass kubectl patch only after confirming the exact disk mismatch in Talos and Longhorn state:

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
