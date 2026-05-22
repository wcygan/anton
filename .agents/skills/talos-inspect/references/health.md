# Health inspection

Read-only triage at the OS / Talos / etcd layer for Anton. All commands assume the shape from `SKILL.md`:

```sh
TALOS="talosctl --talosconfig ./talos/clusterconfig/talosconfig"
NODES="k8s-1,k8s-2,k8s-3"
```

## Fleet-wide pulse

```sh
$TALOS -e k8s-1 -n $NODES version
$TALOS -e k8s-1 -n $NODES health
$TALOS -e k8s-1 -n $NODES service
$TALOS -e k8s-1 -n $NODES get members
```

| Query | What to look for |
| --- | --- |
| `version` | All three at the same `Server Version`. Client/server skew warnings → plan an upgrade via `upgrade-talos-or-k8s`. |
| `health` | Every subprobe `OK`. A single failure on one node usually means kubelet or etcd is flapping on that node. |
| `service` | Every row `Running Healthy`. Anything `Failed` or unexpectedly `Finished` → `logs` it. |
| `get members` | Three discovered members, matching the three nodes. A missing member = node offline or discovery broken. |

## Per-node follow-up

When the fleet pulse flags one node, drill in:

```sh
$TALOS -n k8s-2 service               # per-service state, last restart, exit code
$TALOS -n k8s-2 logs <service>        # kubelet / machined / etcd / apid / trustd / containerd
$TALOS -n k8s-2 dmesg | tail -200     # kernel messages — panics, OOM, NVMe/network resets
$TALOS -n k8s-2 get staticpods        # control-plane static pods (CP nodes only)
$TALOS -n k8s-2 containers            # running containers + image IDs
$TALOS -n k8s-2 processes             # top-like process list
$TALOS -n k8s-2 memory                # usage by category
```

Follow `dmesg` when a node just rebooted — kernel panics, NVMe timeouts, driver resets, and OOM kills all print here. Grep patterns that actually matter:

```sh
$TALOS -n k8s-2 dmesg | rg -i 'panic|oom|i/o error|segfault|hung task|nvme: I/O timeout'
```

Common services and what their failure means:

| Service | If it's unhealthy |
| --- | --- |
| `machined` | Core Talos agent. Almost never fails. If it does, the node needs a reboot. |
| `kubelet` | Node won't register with the API. Check logs for cert issues or disk pressure. |
| `etcd` | Quorum at risk. Stop touching other nodes and read the etcd section below. |
| `apid` | talosctl can't reach the node. Check Tailscale / LAN path from workstation. |
| `trustd` | Cert distribution service. Expired PKI → plan a rotation via `rotate-credential`. |
| `cri` | containerd. If down, no pods run on this node. |
| `kubelet-serving-cert-approver` | Missing approver → kubelet TLS will expire silently. |

## Etcd inspection

All three nodes in Anton are control planes, so etcd must have **exactly three healthy members**. A 3-node cluster tolerates losing one member at a time; losing two is quorum loss and requires disaster recovery.

```sh
$TALOS -n k8s-1 etcd members          # id, name, peer/client URLs, learner flag
$TALOS -n k8s-1 etcd status           # leader, raft index, db size, db size in use
$TALOS -n k8s-1 service etcd          # process-level health
$TALOS -n k8s-1 logs etcd             # peer warnings, compaction, slow apply
```

Warning signs:

- **`alarm: NOSPACE`** — the etcd database needs defragmentation. Plan a defrag (separate operation, not in this skill's scope — read Talos docs under `advanced/disaster-recovery`).
- **`slow fdatasync` / `apply took too long (> 100ms)`** in logs — disk I/O contention. Cross-check `references/disks.md` for NVMe errors on the same node.
- **`request stats sender failed: EOF`** / **peer loss** — network path between control planes is flaky. Cross-check `references/network.md` for MTU / link state.
- **Quorum loss (< 2 healthy members)** — STOP. Do not reboot anything else. This is a disaster-recovery situation; do not improvise.
- **`db size in use` vs `db size` divergence** — compaction is keeping up but defrag hasn't run recently. Not urgent until `NOSPACE` alarms fire.

Etcd **snapshots** are a separate mutating operation; this skill only reads state. See the pre-flight block in `upgrade-talos-or-k8s` for the exact snapshot command, or run the Talos docs `advanced/disaster-recovery` procedure.

## Clock skew

Etcd is extremely sensitive to wall-clock drift between members. Symptoms: leader re-elections every few minutes, `slow fdatasync` or `clock drift` messages in etcd logs, random `context deadline exceeded` from the API.

```sh
$TALOS -e k8s-1 -n $NODES service timed     # Talos NTP sync service (timed)
$TALOS -e k8s-1 -n $NODES time              # wall clock per node
```

All three wall clocks should be within ~1 second of each other. Larger drift → investigate NTP reachability (router ACL, upstream NTP outage, VLAN misrouting).

## Kubernetes-layer sanity checks

Complementary checks that aren't strictly Talos but belong in the same triage pass:

```sh
kubectl get nodes -o wide
kubectl top nodes                                   # needs metrics-server
kubectl get pods -A -o wide | rg -v 'Running|Completed'
kubectl get events -A --sort-by='.lastTimestamp' | tail -30
```

If these are noisy but Talos health is clean, the problem is upstream. Hand off to `debug-flux-reconciliation`.

## Docs — WebFetch when unsure

- `https://docs.siderolabs.com/talos/v1.12/learn-more/resources` — `get <resource>` schema
- `https://docs.siderolabs.com/talos/v1.12/reference/cli/` — talosctl flag reference
- `https://docs.siderolabs.com/talos/v1.12/advanced/disaster-recovery` — etcd recovery (read-only reference)
