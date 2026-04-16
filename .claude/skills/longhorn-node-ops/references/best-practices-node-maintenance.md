---
name: longhorn-node-maintenance
description: Pre-reboot and node-replace best practices for Longhorn in anton.
---

# Node maintenance best practices

Canonical: https://longhorn.io/docs/1.11.1/best-practices/

## Before rebooting a node

Anton is 3× control plane with 2-replica default. Rebooting one node drops each volume to 1 replica — degraded, not faulted. But if the reboot coincides with an active rebuild on a second node, a volume can briefly hit `faulted`.

Safe order for a single-node reboot:

1. Check cluster health: `flux get hr -n storage`, `kubectl get nodes.longhorn.io -n storage -o wide`.
2. Confirm no volume is currently rebuilding:
   ```sh
   kubectl get replicas.longhorn.io -n storage -o json \
     | jq '[.items[] | select(.status.currentState != "running")] | length'
   ```
   Should be `0`.
3. Cordon Kubernetes scheduling: `kubectl cordon <node>`.
4. (Optional, long reboots) Evict replicas off the node — only needed if the reboot will exceed `staleReplicaTimeout` (anton: 48 h), which is almost never.
5. Reboot via `talosctl -n <node> reboot`.
6. Wait until the node is `Ready` and all its replicas are back to `running`.
7. `kubectl uncordon <node>`.

## Rolling reboots

Do them one at a time, never concurrent. A 2-replica volume cannot survive two simultaneous node losses. Upgrade flows using `upgrade-talos-or-k8s` already serialize correctly.

## Replacing a node

Hand off to `add-or-replace-node` for the Talos side. Longhorn specifics:

- Evict the failing node before removing it: set `allowScheduling=false` + `evictionRequested=true` on `nodes.longhorn.io/<node>`, wait for replica count on that node to reach 0.
- When the replacement boots, the new node registers fresh — the Talos `default-disks-config` annotation is read correctly at first registration.
- If you're re-using the same hostname, ensure the old `nodes.longhorn.io` CR is deleted before the replacement joins, otherwise Longhorn will reuse the stale CR with its stale disk list.

## Dedicated disks

Anton's Longhorn disks are dedicated 1 TB NVMes at `/var/mnt/longhorn-{1,2}`. Don't co-locate other workloads on them — Longhorn's sparse replica files compete poorly with hostPath/emptyDir IO.
