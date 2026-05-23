---
name: add-or-replace-node
description: Add or replace a Talos node in Anton. Use to add a node, replace node, scaffold a new control plane, recover a dead node, plan node replacement like k8s-4, or edit nodes.yaml / talconfig.yaml. Generates patches, applies via talosctl.
allowed-tools: Read, Write, Edit, Bash
---

# Add or replace a Talos node

Task skill for joining a new node, replacing a dead one, or staging a new control plane (e.g. `k8s-4`). This is **high stakes**: a wrong patch or wrong disk serial bricks the node. Read every step before running anything.

> **`nodes.yaml` and `cluster.yaml` no longer exist** in this repo — they were Makejinja inputs that `task template:tidy` archived after the initial bootstrap. The actual source-of-truth for the node inventory is `talos/talconfig.yaml` (it still uses `${talosVersion}` and `${kubernetesVersion}` placeholders, but the per-node entries are committed verbatim). When the docs or older skills say "edit nodes.yaml", read it as "edit `talos/talconfig.yaml`".

## Pre-flight — gather everything BEFORE editing config

| Datum | Where to get it | Notes |
| --- | --- | --- |
| Hostname | pick one (`k8s-4`, `k8s-5`, …) | lowercase alphanumeric + hyphens; cannot be `global`/`controller`/`worker` |
| Static IP (`/24`) | pick a free `192.168.1.x` outside DHCP | must be reachable from the workstation (LAN or Tailscale) |
| Default gateway | `192.168.1.254` (current) | check existing entries in `talos/talconfig.yaml` |
| Interface MAC | `talosctl -n <ip> get addresses` after first boot, OR vendor sticker | needed for `deviceSelector.hardwareAddr` |
| Install disk | serial (preferred) or `/dev/sdX` path | run `talosctl -n <ip> get disks` from a maintenance boot |
| Schematic ID | factory.talos.dev — pick the same extensions as existing nodes | 64-char hex; verify it matches the other nodes' `talosImageURL` unless intentionally diverging |
| Control plane? | `controlPlane: true` for CP, omit (or false) for worker | adding a control plane changes etcd quorum math — see Hard Rules |

Verify cluster is currently healthy before changing anything:
```sh
kubectl get nodes -o wide
talosctl --talosconfig ./talos/clusterconfig/talosconfig -n k8s-1 etcd members
flux get ks -A --status=all | rg -v 'True'   # nothing should print except headers
```
If anything is unhealthy, FIX FIRST.

## Workflow A — add a brand-new node (e.g. join `k8s-4`)

1. **Add the node entry** to `talos/talconfig.yaml`. Use an existing node entry as the template — copy its full block, change hostname / IP / MAC / disk serial. Keep `talosImageURL` identical to the others unless adding a node with a different schematic.
   ```yaml
   - hostname: "k8s-4"
     ipAddress: "192.168.1.<x>"
     installDiskSelector:
       serial: "<new-disk-serial>"
     machineSpec:
       secureboot: false
     talosImageURL: factory.talos.dev/installer/<schematic-id>
     controlPlane: true        # or omit for a worker
     networkInterfaces:
       - deviceSelector:
           hardwareAddr: "<new-mac>"
         dhcp: false
         addresses: ["192.168.1.<x>/24"]
         routes:
           - network: "0.0.0.0/0"
             gateway: "192.168.1.254"
         mtu: 1500
         vip:
           ip: "192.168.1.101"   # ONLY for control plane nodes
   ```
2. **Per-node patches (optional).** If this node needs anything different from the global/controller scope, create `talos/patches/<hostname>/<patch>.yaml`. talhelper picks them up automatically. Most nodes don't need this.
3. **Re-render machine configs:**
   ```sh
   task talos:generate-config
   ```
   The output lands in `talos/clusterconfig/kubernetes-<hostname>.yaml` (gitignored). Eyeball it before applying.
4. **Boot the new hardware** off a Talos maintenance image at the same `talosVersion` pinned in `talos/talenv.yaml`. The node will sit in maintenance mode waiting for a config push.
5. **Apply over the insecure API:**
   ```sh
   task talos:apply-node IP=192.168.1.<x> MODE=auto
   ```
   `MODE=auto` reboots if needed. The node comes back up with its assigned config and joins the cluster.
6. **Post-join verification (mandatory):**
   ```sh
   talosctl --talosconfig ./talos/clusterconfig/talosconfig -n 192.168.1.<x> health
   talosctl ... -n 192.168.1.<x> service                       # nothing in Failed
   talosctl ... -n k8s-1 etcd members                          # new member, healthy (CP only)
   kubectl get node <hostname> -o wide                         # Ready
   kubectl get pods -A -o wide | rg <hostname>                 # workloads landing
   flux get ks -A --status=all | rg -v True                    # nothing degraded
   ```
7. **Commit:** `talos/talconfig.yaml` and any new files under `talos/patches/<hostname>/`. Suggested message: `feat(talos): join <hostname> as <control-plane|worker>`.

## Workflow B — replace a dead node (same hostname, new hardware)

The simpler case: hardware died, replacement is identical-looking from the cluster's perspective.

1. **Cordon and drain** the dead node (best effort — it may not respond):
   ```sh
   kubectl cordon <hostname>
   kubectl drain <hostname> --ignore-daemonsets --delete-emptydir-data --force --timeout=60s
   ```
2. **Remove the dead etcd member** (control plane only — required before re-adding the same name):
   ```sh
   talosctl ... -n k8s-1 etcd members              # find the dead member id
   talosctl ... -n k8s-1 etcd remove-member <id>
   ```
3. **Update the node entry** in `talos/talconfig.yaml`: change MAC and disk serial to the new hardware. Keep hostname and IP the same.
4. Re-render and apply: `task talos:generate-config && task talos:apply-node IP=<ip> MODE=auto`
5. **Delete the stale Kubernetes Node object** so the new join is clean:
   ```sh
   kubectl delete node <hostname>
   ```
6. Run the post-join verification block from Workflow A.

## Workflow C — replace by renaming (e.g. retire `k8s-3`, introduce `k8s-4`)

1. Add `k8s-4` per **Workflow A** (boot new hardware in parallel, do not disturb `k8s-3`).
2. Wait until `k8s-4` is `Ready` and etcd shows 4 healthy members.
3. **Remove `k8s-3`:**
   ```sh
   kubectl cordon k8s-3
   kubectl drain k8s-3 --ignore-daemonsets --delete-emptydir-data
   talosctl ... -n k8s-1 etcd remove-member <k8s-3-id>
   talosctl ... -n 192.168.1.<k8s-3-ip> reset --graceful=true --reboot=true
   kubectl delete node k8s-3
   ```
4. Delete the `k8s-3` block from `talos/talconfig.yaml` and `talos/patches/k8s-3/` if any.
5. Re-render: `task talos:generate-config`. Commit the removal as a separate commit from the addition.

## Hard rules

- **Etcd quorum is the hard limit.** A 3-node cluster tolerates losing exactly one member at a time. NEVER remove an etcd member before its replacement is `Healthy`.
- **One node operation at a time.** No parallel `apply-node` or `reset` commands across multiple control planes.
- **Schematic IDs are public** — safe to commit. Disk serials and MACs are also fine in git.
- **Never run `task talos:reset`** during a replacement workflow. It is a destructive cluster-wide reset, not a per-node operation. The per-node reset is `talosctl ... reset` against a specific endpoint.
- **Apply mode `auto` may reboot.** If you need to confirm the change is non-disruptive first, use `MODE=no-reboot`; talhelper rejects the apply if a reboot would be required.

## Related skills

- Reaching the new node from off-LAN before joining → `anton-remote-access`
- Bumping the Talos image after a successful join → `upgrade-talos-or-k8s`
- Triaging Flux when the new node is up but workloads won't schedule → `debug-flux-reconciliation`
