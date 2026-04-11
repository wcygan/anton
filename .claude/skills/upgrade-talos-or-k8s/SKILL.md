---
name: upgrade-talos-or-k8s
description: Rolling upgrade for Anton's Talos OS or Kubernetes. Use to upgrade talos, bump kubernetes version, edit talenv, run a rolling upgrade across nodes, or change the talos version. High-stakes — one node at a time, etcd quorum gated.
allowed-tools: Read, Bash
---

# Upgrade Talos or Kubernetes

High-stakes checklist task skill. Two version pins drive everything: `talosVersion` and `kubernetesVersion` in `talos/talenv.yaml`. Bump the pin first, then run the corresponding rolling upgrade. Never parallelize. Never skip the health gate between nodes.

> **DESTRUCTIVE if mishandled.** Losing etcd quorum during a control-plane rolling upgrade can wedge the cluster. Stop and ask the user before deviating from the workflow below.

## Pre-flight (run BEFORE bumping any pin)

1. **Confirm cluster is currently healthy.** All three control planes must be Ready and etcd must have quorum (a 3-node cluster tolerates exactly one missing member).
   ```sh
   kubectl get nodes -o wide
   talosctl --talosconfig ./talos/clusterconfig/talosconfig -e k8s-1 -n k8s-1,k8s-2,k8s-3 service etcd
   talosctl --talosconfig ./talos/clusterconfig/talosconfig -n k8s-1 etcd members
   ```
   Expect three members, all `Healthy=true`. If any node is unhealthy, FIX FIRST and abort the upgrade.
2. **Take an etcd snapshot.** Cheap insurance.
   ```sh
   mkdir -p $HOME/anton-backup-$(date +%Y%m%d)
   talosctl --talosconfig ./talos/clusterconfig/talosconfig -n k8s-1 \
     etcd snapshot $HOME/anton-backup-$(date +%Y%m%d)/etcd-pre-upgrade.db
   ls -lh $HOME/anton-backup-$(date +%Y%m%d)/etcd-pre-upgrade.db   # must be > 0 bytes
   ```
3. **Confirm Flux is healthy** so it doesn't fight the rolling reboot.
   ```sh
   flux check
   flux get ks -A --status=all | rg -v 'True'   # nothing should print except headers
   ```
4. **Read the upstream release notes** for the new Talos and Kubernetes versions. Breaking changes (CRD removals, feature gates, kubelet flags) MUST be triaged before the bump.
5. **Confirm kubeconfig + talosconfig point at the right cluster.** This skill operates against whichever cluster the local config points to — there is no `--context` guard.

## Workflow A — Talos OS rolling upgrade

For bumping `talosVersion` (the OS image baked into each node).

1. **Bump the pin** in `talos/talenv.yaml`:
   ```yaml
   talosVersion: v1.X.Y    # new version
   ```
2. **Re-render machine configs** so the new version threads through `talconfig.yaml`:
   ```sh
   task configure
   task talos:generate-config
   ```
3. **Roll one node at a time**, control planes first. The rule is **strictly serial** for control planes — you CANNOT lose quorum:
   ```sh
   # control plane 1
   task talos:upgrade-node IP=<k8s-1-ip>
   # WAIT for the node to come back. Then verify:
   talosctl ... -n <k8s-1-ip> version          # new version reported
   talosctl ... -n <k8s-1-ip> health           # must return ok
   kubectl get node <k8s-1-name> -o wide        # Ready, new kubelet
   talosctl ... -n k8s-1 etcd members           # 3 healthy members again

   # ONLY THEN, control plane 2
   task talos:upgrade-node IP=<k8s-2-ip>
   # … repeat the verify block …

   # ONLY THEN, control plane 3
   task talos:upgrade-node IP=<k8s-3-ip>
   ```
4. **Workers** (if any) come last, also one at a time. Same verify block between each.
5. **Commit** the `talenv.yaml` bump and the regenerated `talconfig.yaml` AFTER all nodes are upgraded and healthy. One commit per upgrade pair (`feat(talos): upgrade vA.B.C -> vX.Y.Z`).

**Health gate between nodes (mandatory):**

| Check | Command | Expected |
| --- | --- | --- |
| node Ready | `kubectl get node <name>` | `Ready` |
| Talos version reported | `talosctl ... -n <ip> version` | new version, no skew warnings |
| etcd members healthy | `talosctl ... -n <ip> etcd members` | 3 healthy members |
| no panicked services | `talosctl ... -n <ip> service` | nothing in `Failed` |
| Flux still green | `flux get ks -A --status=all` | all `Ready=True` |

If ANY check fails, STOP. Do not move to the next node. Investigate; rollback if needed.

## Workflow B — Kubernetes version bump

For bumping `kubernetesVersion`. talhelper handles the rolling upgrade across all nodes.

1. **Bump the pin** in `talos/talenv.yaml`:
   ```yaml
   kubernetesVersion: v1.X.Y
   ```
2. **Re-render** so the new version reaches talconfig:
   ```sh
   task configure
   ```
3. **Run the rolling Kubernetes upgrade:**
   ```sh
   task talos:upgrade-k8s
   ```
   Under the hood: `talhelper gencommand upgrade-k8s --extra-flags "--to '<version>'" | bash`. talhelper rolls control planes first, then workers. Watch the output — it does NOT auto-pause on failures.
4. **Verify after the run:**
   ```sh
   kubectl get nodes -o wide                    # all nodes show new kubelet version
   kubectl get pods -A | rg -v 'Running|Completed'   # nothing stuck
   flux check
   ```
5. **Commit** the `talenv.yaml` bump.

**Skip a major Kubernetes version at your peril.** Talos and upstream Kubernetes only support N-1/N-2 skews. If you need to jump multiple versions, do them sequentially (`v1.34 → v1.35 → v1.36`), running a full Workflow B between each.

## Rollback

Talos OS rollback (reverts the system disk to the previous image):
```sh
talosctl --talosconfig ./talos/clusterconfig/talosconfig -n <ip> rollback
talosctl ... -n <ip> version    # confirm previous version
```
Run this on the affected node only. Pair it with `talosctl ... -n <ip> health` and `kubectl get node <name>` before moving on.

Kubernetes downgrade is **not** supported. If a Kubernetes upgrade fails halfway through, finish the roll forward (`task talos:upgrade-k8s` is idempotent), then triage the failing component. Restoring etcd from the snapshot is the last-resort recovery — coordinate with the user before doing it.

## Hard rules

- Never parallelize. One node at a time, always.
- Control planes BEFORE workers, always.
- Health gate between every node, no exceptions.
- Never skip the etcd snapshot. The cost of taking it is seconds; the cost of skipping it is hours.
- Never bump both `talosVersion` and `kubernetesVersion` in the same change. Bump one, run that workflow to completion, commit, THEN do the other.
- Never run `task talos:reset` as part of an upgrade. If you need it, you have a different problem.

## Related skills

- Reaching nodes from off-LAN before/during the upgrade → `anton-remote-access`
- Replacing a node that fails to come back → `add-or-replace-node`
- Triaging Flux after the upgrade looks complete but apps are unhealthy → `debug-flux-reconciliation`
