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

Generic two-pass disk transition: substitute the exact confirmed disk names, UUID, and path from the current Longhorn node resource. Do not reuse historical node inventory.

**Pass 1** — add new disks, disable the old one, request eviction:

```sh
kubectl patch nodes.longhorn.io <node> -n storage --type=merge -p "$(cat <<'EOF'
{
  "spec": {
    "disks": {
      "<new-disk-name-1>": {
        "path": "<new-disk-path-1>",
        "allowScheduling": true,
        "evictionRequested": false,
        "storageReserved": 0,
        "tags": []
      },
      "<new-disk-name-2>": {
        "path": "<new-disk-path-2>",
        "allowScheduling": true,
        "evictionRequested": false,
        "storageReserved": 0,
        "tags": []
      },
      "<old-disk-name>": {
        "path": "<old-disk-path>",
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
  -p '{"spec":{"disks":{"<old-disk-name>":null}}}'
```

## Why this is not GitOps

The Longhorn disk list on a live node is runtime state. The GitOps truth is the Talos `default-disks-config` annotation, which is read at **first registration**. For a live migration on an already-registered node, confirm the current Talos annotation and Longhorn node resource, then use the two-pass patch above only if the operator has approved that live change.

Keep the Talos annotation in `talos/talconfig.yaml` aligned with the confirmed intended disk set, even when correcting live drift through Longhorn.
