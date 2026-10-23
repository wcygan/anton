---
name: upgrade-talos-or-k8s
description: Rolling upgrade for Anton's Talos OS or Kubernetes. Use to upgrade talos, bump kubernetes version, edit talenv, run a rolling upgrade across nodes, or change the talos version. High-stakes — one node at a time, etcd quorum gated.
---

# Upgrade Talos or Kubernetes

High-stakes checklist task skill. Two version pins drive everything: `talosVersion` and `kubernetesVersion` in `talos/talenv.yaml`. Bump the pin first, then run the corresponding rolling upgrade. Never parallelize. Never skip the [node gate](#node-gate): it must pass before cordon, before uncordon and after uncordon.

> **DESTRUCTIVE if mishandled.** Losing etcd quorum during a control-plane rolling upgrade can wedge the cluster. Stop and ask the user before deviating from the workflow below.

## Pre-flight (run BEFORE bumping any pin)

1. **Confirm the cluster is healthy with the pre gate** for the first node. It must exit 0. It covers node readiness, etcd quorum (a 3-node cluster tolerates exactly one missing member), Flux, firing alerts and storage:
   ```sh
   mise exec -- task -x talos:node-gate NODE=k8s-1 PHASE=pre
   ```
   If it fails, fix that first or abort the upgrade.
2. **Take and verify an etcd snapshot at the approved recovery location.**
   `talosctl etcd snapshot` writes on the machine running the client: invoking it
   on the Mac transfers the database to the Mac. Follow the recovery-location rule
   below before selecting that execution host or destination. A cluster-only
   checkpoint needs an explicitly approved in-cluster client and storage target;
   missing that capability does not authorize a Mac export. Record the cluster
   identity, capture time, revision, nonzero size and checksum. Preserve an existing
   verified pre-upgrade snapshot when continuing the same rollout; state its age
   and any unmet freshness requirement instead of silently taking another export.
3. **Read the upstream release notes** for the new Talos and Kubernetes versions. Breaking changes (CRD removals, feature gates, kubelet flags) MUST be triaged before the bump.
4. **Confirm kubeconfig + talosconfig point at the right cluster.** The gate pins the Tailscale operator context and checks that `talconfig.yaml`, Kubernetes and Talos agree on every node. The mutating commands below have no such guard, so confirm the context before each one.

For Anton storage nodes, complete the [Longhorn node preconditions](../longhorn-node-ops/SKILL.md)
and [SeaweedFS maintenance procedure](../seaweedfs-ops/references/node-maintenance.md)
before the first node outage. Node readiness alone does not establish storage or
data readiness.

## Recovery location and transfer authority

Keep maintenance recovery checkpoints and verification near the data by default.
Do not initiate backups or large exports to the operator's Mac or another external
destination as an automatic upgrade preflight. A transfer requires a separate,
explicit user request naming the destination and scope; an upgrade request alone
does not authorize it. Preserve existing backups and partial files unless their
removal is separately requested.

In-cluster snapshots and clone-based verification share the cluster's failure
domain. Do not describe them as independent disaster-recovery backups or claim
that they satisfy an independent-backup freshness contract. If the operator
explicitly selects cluster-only recovery for a maintenance window, record that
choice and the remaining disaster-recovery gap. Keep identity, quorum, storage
health, writer-fencing and data-consistency gates active; a location preference
does not authorize data repair or waive those gates.

At verified maintenance closure, account for every temporary recovery snapshot.
Release redundant maintenance snapshots to the [maintenance retention policy](../../../docs/docs/guides/storage.md#maintenance-snapshot-retention)
using their actual UID and a delete-after timestamp. Preserve any explicitly open
recovery or investigation hold; creation age is not evidence that a hold ended.
Never release the two monthly verified checkpoint generations. The scheduled
cleanup owns CSI deletion and Longhorn reclamation; do not delete replica files.

## Node gate

`task -x talos:node-gate NODE=<node> PHASE=<phase>` runs `scripts/node-gate.py`,
a read-only check of one node. It runs only `kubectl get`, `talosctl get/ls/read`
and `talosctl etcd members/status`, and prints PASS or FAIL per check. Exit 0
means every check passed. Exit 1 means a check failed. Exit 2 means the gate could
not start (arguments, context, talosconfig or Tailscale targets) or could not
write its report. `-x` passes these codes through; without it `task` reports any
failure as 201. Any non-zero exit stops the window. Read the exit status itself:
piping the gate through `tail` hides it.

| Phase | Run when | Must pass before | Checks |
| --- | --- | --- | --- |
| `pre` | the node is schedulable and untouched | cordon | node + cluster |
| `return` | the node is back from its reboot, still cordoned | uncordon | node + `multus-status` |
| `post` | the node is uncordoned | the next node | node + `multus-status` + cluster |

Node checks:
- `identity`: the `talconfig.yaml` address, Kubernetes InternalIP and Talos
  nodename agree, with Talos reached through a peer's Tailscale endpoint.
- `nodes`: all three are Ready. Only `return` allows a cordon, and only on the
  target.
- `versions`: before cordon, at most one pin is pending, by one patch or minor
  step. After the reboot, Talos and the kubelet match `talenv.yaml`.
- `etcd`: exactly three voting members, each healthy, with one agreed leader
  and no errors.
- `talos-services` and `control-plane` are healthy.
- `cni-config`: `/etc/cni/net.d` holds only `00-multus.conf` (type
  `multus-shim`) and `whereabouts.d`.
- `cni-daemons`: Cilium, Multus, Whereabouts and storage VXLAN are Ready on
  the node.
- `instance-managers`: every Longhorn instance manager, on every node, has
  `lhnet1` with an address in the `longhorn-storage` range, and running replicas
  serve on that address.

`multus-status` requires every Running pod-network pod on the node to have a
`network-status` whose default address is its pod IP and that lists each
attachment it requested. A missing or stale annotation means its sandbox
bypassed Multus. Before cordon the drain and reboot recreate such pods, and
`cni-config` gates the cause, so `pre` skips this check.

Cluster checks:
- `longhorn`: Longhorn nodes are Ready and Schedulable, and attached volumes
  are healthy.
- `seaweedfs`: `SeaweedFS_volumeServer_read_only_volumes` is 0 and reported by
  every volume server.
- `pods`: every pod is Ready or Succeeded. Pods under two minutes old are left
  to settle, and Failed tombstones are left to pod-gc.
- `flux`: every object is Ready at its current generation and none is
  suspended.
- `alerts`: Watchdog must be present, because without it an empty list proves
  nothing. Any other firing alert fails, with two exceptions: an alert named in
  `ACCEPT_ALERTS` after assessment, and `NodeUnexpectedReboot` or
  `MultusDaemonRestarting` for the target after its reboot or for a `REBOOTED`
  node. `PodBypassedMultus` and `CronJobSuccessOverdue` fail unless accepted.
- `disruption-budgets`: no budget may be below its healthy minimum. Before
  cordon, every budget covering a pod on the node must allow a disruption, so the
  SeaweedFS and CoreDNS budgets hold through the drain. Two kinds of budget are
  released by their controllers after cordon. Longhorn instance-manager budgets
  are released when every volume has a healthy replica elsewhere, which
  `longhorn` gates. A CloudNativePG primary budget passes only when every instance
  of its cluster is ready to take over.

`WAIT=<seconds>` reruns failing checks every 20 seconds until one full pass, or
until the time runs out. `REBOOTED=<nodes>` names the nodes already rolled in this
window. Their reboot alerts last up to 30 minutes and would otherwise fail the
next node's pre gate. Each run writes a JSON report under `.private/node-gate/`.
Reports can name private workloads, so keep them out of public PRs and docs; quote
the PASS/FAIL lines instead.

## Workflow A — Talos OS rolling upgrade

For bumping `talosVersion` (the OS image baked into each node).

1. **Bump the pin** in `talos/talenv.yaml`:
   ```yaml
   talosVersion: v1.X.Y    # new version
   ```
2. **Re-render machine configs** so the new version threads through `talconfig.yaml`:
   ```sh
   task talos:generate-config
   ```
3. **Roll one node at a time**, control planes first. The rule is **strictly serial** for control planes — you CANNOT lose quorum. For each node, every step needs the previous one to succeed:
   ```sh
   # a. Pre gate. REBOOTED names the nodes already rolled in this window.
   mise exec -- task -x talos:node-gate NODE=<node> PHASE=pre REBOOTED=<rolled nodes>
   # b. Cordon, then drain through the Kubernetes API proxy.
   mise exec -- kubectl --context "$CONTEXT" cordon <node>
   mise exec -- task drain:node NODE=<node> CONTEXT="$CONTEXT" \
     CLUSTER_UID=<uid> NODE_UID=<uid> OPERATOR_UID=<uid> TIMEOUT=600
   # c. Upgrade that node only. The drain is done, so skip the client's own.
   mise exec -- talosctl --talosconfig ./talos/clusterconfig/talosconfig \
     -e <peer Tailscale IP> -n <node LAN IP> \
     upgrade --image <node talosImageURL>:<talosVersion> --drain=false --timeout 15m
   # d. Return gate. The node is back and still cordoned.
   mise exec -- task -x talos:node-gate NODE=<node> PHASE=return WAIT=900
   # e. Uncordon, then run the post gate. Only then start the next node.
   mise exec -- kubectl --context "$CONTEXT" uncordon <node>
   mise exec -- task -x talos:node-gate NODE=<node> PHASE=post WAIT=1200
   ```
   `task drain:node` moves the in-cluster API proxy off the node before the drain. Collect its UIDs as in the [Harbor continuity drain](../anton-cluster-health/references/harbor-continuity.md). The upgrade client's own drain uses the node's admin kubeconfig and LAN API endpoint, which off-LAN cannot reach. On-LAN, `task talos:upgrade-node IP=<ip>` also works for step c. Do not repeat an installer write to diagnose a failed drain.

   Keep the node cordoned until the return gate passes. Node Ready and Multus Pod Ready can precede `/etc/cni/net.d/00-multus.conf`. Cilium writes its config to `/etc/cni/multus/net.d`, so until Multus writes `00-multus.conf`, containerd starts no pod-network pods. Before 2026-10-23, a Cilium config in `/etc/cni/net.d` let pods start without Multus for about 30 seconds after each boot. A Longhorn instance manager then came up without `lhnet1`. `cni-config` and `multus-status` catch a regression, and `PodBypassedMultus` alerts on one.
4. **Workers** (if any) come last, also one at a time, through the same three gates.
5. **Commit** the `talenv.yaml` bump and the regenerated `talconfig.yaml` AFTER all nodes are upgraded and healthy. One commit per upgrade pair (`feat(talos): upgrade vA.B.C -> vX.Y.Z`).

If a gate fails, follow [Stop and roll back](#stop-and-roll-back). Do not move to the next node.

## Workflow B — Kubernetes version bump

For bumping `kubernetesVersion`. Talhelper generates the command; `talosctl`
performs the rolling upgrade across all nodes.

1. **Bump the pin** in `talos/talenv.yaml`:
   ```yaml
   kubernetesVersion: v1.X.Y
   ```
2. **Re-render** so the new version reaches talconfig:
   ```sh
   task talos:generate-config
   ```
   Then run the pre gate for every node. Each must exit 0 and report the Kubernetes step as pending:
   ```sh
   mise exec -- task -x talos:node-gate NODE=<node> PHASE=pre
   ```
3. **Run the rolling Kubernetes upgrade:**
   ```sh
   task talos:upgrade-k8s
   ```
   Under the hood: `talhelper gencommand upgrade-k8s --extra-flags "--to '<version>'" | bash`.
   `talosctl` checks compatibility and removed flags/APIs, then updates each
   control-plane component serially, waiting for its pod to recover before the
   next node. Kubelets follow, control planes before workers. A failed recovery
   gate stops the command; investigate the exact component before resuming.

   Off-LAN, this client fetches an admin kubeconfig from Talos rather than using
   the local Kubernetes proxy context. If its LAN endpoint is unreachable, use
   `--endpoint` with an approved reachable API path that preserves the cluster CA
   and certificate names. Never disable TLS verification. Run
   `upgrade-k8s --dry-run --pre-pull-images=false` with that path first.
4. **Verify after the run** with the post gate for every node. It requires the new kubelet and control-plane versions, Ready pods and green Flux:
   ```sh
   mise exec -- task -x talos:node-gate NODE=<node> PHASE=post WAIT=900
   ```
   `upgrade-k8s` reboots no node and recreates no pod-network pods. So when `multus-status` fails here, the pods it names bypassed Multus at an earlier boot: compare their `sandbox since` times with the node's last boot. Restarting them is a separately approved mutation; the next node reboot also recreates them.
5. **Commit** the `talenv.yaml` bump.

**Skip a major Kubernetes version at your peril.** Talos and upstream Kubernetes only support N-1/N-2 skews. If you need to jump multiple versions, do them sequentially (`v1.34 → v1.35 → v1.36`), running a full Workflow B between each.

## Stop and roll back

A failed gate stops the window. The failing check names what to fix; the node's
state decides what is safe. Fix one cause at a time and rerun the same gate.

| Gate | Failing check | Node state | Do |
| --- | --- | --- | --- |
| any | exit 2 | unchanged | Restore access (context, talosconfig, Tailscale targets). Never proceed without a gate result. |
| any | `etcd` | any | Stop all node work, and take no other node down. Restoring the snapshot is the last resort, with the user. |
| `pre` | any | schedulable, untouched | Do not cordon. Fix the cause or end the window; nothing to roll back. |
| `return` | `versions`, `talos-services`, `nodes` after `WAIT` | cordoned, rebooted | Leave it cordoned. If the upgrade caused it, roll back this node only (below) and rerun the return gate. |
| `return` | `cni-config`, `cni-daemons`, `multus-status` | cordoned | Do not uncordon. Remove the cause of any extra file in `/etc/cni/net.d`: Cilium `cni.confPath` and Multus `multusAutoconfigDir` must stay `/etc/cni/multus/net.d`. Restart bypassed pods only after that. |
| `return` | `instance-managers` | cordoned, drained | The failure names the instance manager and its engine and replica counts. With no engines, deleting that one pod (separately approved) lets Longhorn recreate it on the storage network. With engines, do not delete it: that detaches attached volumes mid-write, as on 2026-10-22. Move those consumers first. |
| `post` | `longhorn`, `seaweedfs`, `pods`, `disruption-budgets` after `WAIT` | uncordoned | Do not start the next node. Follow `longhorn-volume-ops`, or `seaweedfs-ops` and its `references/health-alerts.md`. Never force a SeaweedFS volume writable. |
| `pre`, `post` | `alerts` | — | Investigate each alert. Pass `ACCEPT_ALERTS` only for one already assessed, and record why. |

Talos OS rollback (reverts the system disk to the previous image):
```sh
talosctl --talosconfig ./talos/clusterconfig/talosconfig -e <peer Tailscale IP> -n <node LAN IP> rollback
talosctl --talosconfig ./talos/clusterconfig/talosconfig -e <peer Tailscale IP> -n <node LAN IP> version    # confirm previous version
```
Run this on the affected node only, then rerun the return gate against the version it rolled back to:
```sh
mise exec -- task -x talos:node-gate NODE=<node> PHASE=return TALOS_VERSION=<previous version> WAIT=900
```
Then stop. Roll no other node until the user decides whether to retry the upgrade or revert the pin.

Kubernetes downgrade is **not** supported. If a Kubernetes upgrade fails halfway through, finish the roll forward (`task talos:upgrade-k8s` is idempotent), then triage the failing component. Restoring etcd from the snapshot is the last-resort recovery — coordinate with the user before doing it.

## Hard rules

- Never parallelize. One node at a time, always.
- Control planes BEFORE workers, always.
- Pre, return and post node gates for every node, no exceptions. A non-zero exit is a stop.
- Never skip the verified pre-upgrade etcd recovery point. Follow the recovery-location rule; retaining an existing snapshot does not authorize another external export.
- Never bump both `talosVersion` and `kubernetesVersion` in the same change. Bump one, run that workflow to completion, commit, THEN do the other.
- Never run `task talos:reset` as part of an upgrade. If you need it, you have a different problem.

## Related skills

- Reaching nodes from off-LAN before/during the upgrade → `anton-remote-access`
- Replacing a node that fails to come back → `add-or-replace-node`
- Triaging Flux after the upgrade looks complete but apps are unhealthy → `debug-flux-reconciliation`
