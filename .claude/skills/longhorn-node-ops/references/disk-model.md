---
name: longhorn-disk-model
description: How Longhorn disks, nodes, and replicas fit together; kubectl patches for anton.
---

# Disk model

Canonical: https://longhorn.io/docs/1.11.1/concepts/

## The CR hierarchy

- `nodes.longhorn.io/<node>` — one per Kubernetes Node. `spec.disks` is a map keyed by arbitrary disk name → `{path, allowScheduling, evictionRequested, storageReserved, tags}`.
- `replicas.longhorn.io/<id>` — one replica. `spec.nodeID` + `spec.diskID` pins it to a specific disk.
- `instancemanagers.longhorn.io/<id>` — one per node, hosts engine + replica processes.

Longhorn identifies disks internally by UUID (`status.diskStatus[<name>].diskUUID`), not by name. The name in `spec.disks` is purely a label.

## Two-pass disk swap

Longhorn refuses to delete a disk with live replicas. Swapping a disk requires two patches.

Anton example — replacing the Talos EPHEMERAL default-disk on a node with two declared NVMes (what we actually did in plan 0001 Phase 2):

**Pass 1** — add new disks, disable the old one, request eviction:

```sh
kubectl patch nodes.longhorn.io <node> -n storage --type=merge -p "$(cat <<'EOF'
{
  "spec": {
    "disks": {
      "longhorn-1": {
        "path": "/var/mnt/longhorn-1",
        "allowScheduling": true,
        "evictionRequested": false,
        "storageReserved": 0,
        "tags": []
      },
      "longhorn-2": {
        "path": "/var/mnt/longhorn-2",
        "allowScheduling": true,
        "evictionRequested": false,
        "storageReserved": 0,
        "tags": []
      },
      "default-disk-<hash>": {
        "path": "/var/lib/longhorn/",
        "allowScheduling": false,
        "evictionRequested": true,
        "storageReserved": 0,
        "tags": []
      }
    }
  }
}
EOF
)"
```

Wait for eviction:

```sh
kubectl get replicas.longhorn.io -n storage -o json \
  | jq '[.items[] | select(.spec.diskID=="<old-disk-uuid>")] | length'
```

Should reach `0` before proceeding.

**Pass 2** — remove the old disk key entirely via JSON merge null:

```sh
kubectl patch nodes.longhorn.io <node> -n storage --type=merge \
  -p '{"spec":{"disks":{"default-disk-<hash>":null}}}'
```

## Why this is not GitOps

The Longhorn disk list on a live node is runtime state. The GitOps truth is the Talos `default-disks-config` annotation, which is only read at **first registration**. For future node rebuilds or replacements the Talos annotation routes correctly; for live migrations on an already-registered node the two-pass kubectl patch above is the escape hatch.

Keep the Talos annotation in `talos/talconfig.yaml` matching the intended disk set, even when you correct drift via kubectl — future re-registration depends on it.
