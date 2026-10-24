---
title: Talos and node health
---

# Talos and node health

Talos nodes are immutable and managed only through their API. This guide covers read-only node investigation and how to choose a target safely. Upgrades, node replacement, and any config apply have their own high-risk procedures.

## Where node configuration comes from

The source of truth is `talos/talconfig.yaml`, `talos/talenv.yaml`, and the files in `talos/patches/`. Talhelper generates the machine configuration from them; never edit the generated files by hand. After changing a source file, regenerate and review the diff:

```sh
mise exec -- task talos:generate-config
```

Generating and reviewing config does not apply it. Applying is a separate, separately approved step.

`talosVersion` selects the installed OS image and the configuration format used by Talhelper. Talos 1.14 uses separate documents for the resolver and Kubernetes control-plane components; keep those settings in their typed patches rather than duplicating them in the legacy `machine.network` or `cluster` blocks. Validate every generated node configuration with the target Talos client before a rollout.

Talhelper 3.1.17 does not copy `additionalApiServerCertSans` into Talos 1.14's `KubeAPIServerConfig`. Set API-server certificate names explicitly in the controller patch's `certExtraSANs`; `additionalMachineCertSans` continues to configure the Talos API certificate.

## Choose a target

`scripts/cluster-targets.py` resolves which node a command talks to. The Talos task wrappers and safety checks all use it. The public inventory holds logical node names only; exact fallback endpoints come from ignored private operator configuration.

Inspect the redacted selection before any operation:

```sh
mise exec -- task talos:targets
```

Check which source the target came from and that the membership matches the cluster you expect. If private fallback configuration is missing, you have an access limitation. Do not guess node addresses or copy discovered ones into guides or scripts.

## Investigate a node

Fix the Talos context, the target node, and the time window before you start. Then:

```sh
mise exec -- talosctl health
mise exec -- talosctl get members
mise exec -- talosctl get services
mise exec -- talosctl get disks
```

Start with node readiness and etcd membership. Then look for the earliest relevant evidence in the OS, network interfaces, disks, or services. Line evidence up by node and time rather than by symptom. Avoid broad log dumps, and redact credentials and machine identifiers before sharing.

## Shutdown order

When a node shuts down or reboots gracefully, the kubelet stops pods one priority tier at a time, lowest first, so writers finish before the storage under them stops. The budgets live in `talos/patches/global/machine-kubelet.yaml`; the two storage classes live in `kubernetes/apps/kube-system/priority-classes/`.

| Tier | PriorityClass | Members | Budget |
| --- | --- | --- | --- |
| Ordinary workloads | none (priority 0) | Everything not listed below | 60 s |
| Storage consumers | `storage-consumer` | Loki; Harbor core, jobservice and registry | 120 s |
| Storage services | `storage-service` | SeaweedFS; Harbor's database and cache | 90 s |
| Longhorn | `longhorn-critical` | Longhorn | 60 s |
| Cluster critical | `system-cluster-critical` | Control plane, Flux, DNS, gateways | 30 s |
| Node critical | `system-node-critical` | Cilium, Multus, storage network | 30 s |

Each pod gets the shorter of its own grace period and its tier's budget. The next tier starts once every pod in the current one has exited and its volumes are unmounted, or when the budget runs out. Talos waits at most 20 minutes for the kubelet, and Kubernetes starts evicting a NotReady node's pods after five minutes, so the budgets stay inside both; `scripts/tests/test_shutdown_tiers.py` checks them. Under memory pressure the kubelet evicts lower tiers first among pods that use more memory than they request, so tiered workloads request their observed working set.

Only the kubelet's own shutdown follows the tiers:

| Operation | What stops the pods |
| --- | --- |
| `talosctl reboot`, `talosctl shutdown --force`, the power button | The kubelet, in tier order |
| `talosctl upgrade`, `talosctl reboot --drain`, `talosctl shutdown` | A drain first evicts every evictable pod at once, honoring disruption budgets; the kubelet then stops what is left in tier order |
| `talosctl reboot --mode=force`, power loss, kernel panic, watchdog reset | Nothing; processes die with the node |

Because a drain ignores priority, planned maintenance still fences writers first ([SeaweedFS node maintenance](seaweedfs.md#node-maintenance)).

## Changing a node

Every Talos apply, reboot, reset, upgrade, or replacement needs:

1. The matching high-risk skill's preconditions.
2. An etcd quorum check.
3. A rollback plan.
4. Explicit operator approval.

For a reboot or upgrade, `mise exec -- task -x talos:node-gate NODE=<node> PHASE=<phase>` checks the first two for one node and changes nothing. Run `PHASE=pre` before cordon, `PHASE=return` before uncordon and `PHASE=post` after uncordon, and stop at any failure. The [upgrade skill](https://github.com/wcygan/anton/blob/main/.agents/skills/upgrade-talos-or-k8s/SKILL.md#node-gate) lists the checks and what to do when one fails.

For Kubernetes API access during this work, prefer the Tailscale operator context. Use the documented administrator fallback only after confirming which identity it uses.

## etcd health

Every node runs an etcd member, and each node's API server talks only to its local member. Three members tolerate one failure. Losing a second member loses quorum, and the Kubernetes API stops.

### etcd metrics

Each member serves plain-HTTP `/metrics` and `/health` on port 2381, set by `listen-metrics-urls` in the controller patch. kube-prometheus-stack scrapes the node addresses in `kubeEtcd.endpoints` as job `kube-etcd`, sends them no credentials, and provides Grafana's etcd dashboard. Keep those endpoints equal to the control-plane nodes in `talconfig.yaml`; `scripts/tests/test_etcd_monitoring.py` fails when they differ.

The listener binds every host interface and has no authentication. It serves metrics and health checks, never keys or values.

Changing etcd's `extraArgs` does not restart etcd. Talos applies the new configuration at once, but the etcd service reads its arguments only when it starts, and Talos cannot restart etcd through its API. The change takes effect at each node's next reboot or upgrade.

### etcd alerts

The rules live in `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-etcd.yaml`. `scripts/verify-etcd-alerts.py` replays them against three synthetic members with promtool. Healthy members have one leader, WAL fsync and backend commit p99 near 10–20 ms, and a database far below the 2 GiB quota.

| Alert | Severity | Fires when | First response |
| --- | --- | --- | --- |
| `EtcdNoLeader` | critical | A member has had no leader for 1 minute | Read members and leader with `talosctl etcd status`. For one member, check that node's network and etcd logs. If two members have no leader, quorum is lost: reboot or reset nothing, and plan recovery from Talos's etcd disaster-recovery guide with the operator. |
| `EtcdMembersDown` | warning | Scrapes of a member fail in every 5-minute window for 15 minutes | Check the node and `talosctl service etcd`. Hold all other node maintenance until the member is back. |
| `EtcdFrequentLeaderChanges` | warning | Four or more elections in 15 minutes | Check the latency alerts, recent reboots, and etcd logs for slow `fdatasync` or missed heartbeats. |
| `EtcdHighFsyncDurations` | warning | WAL fsync p99 above 500 ms for 10 minutes | Look for contention or errors on that node's system disk. |
| `EtcdHighCommitDurations` | warning | Backend commit p99 above 250 ms for 10 minutes | Look for contention or errors on that node's system disk. |
| `EtcdDatabaseNearQuota` | warning above 50%, critical above 80% | The physical database nears its quota | Compare DB size with size in use in `talosctl etcd status`. If most is free, defragment; if most is in use, find the writer. At 100% etcd raises `NOSPACE` and rejects writes. |
| `EtcdDatabaseGrowingFast` | warning | Growth over 4 hours would reach the quota within 4 hours | Find the controller or workload writing in a loop. Defragmenting only buys time. |
| `EtcdDatabaseFragmented` | info, never pages | Free pages exceed a quarter of the quota for 1 hour | Plan a defragmentation. |
| `EtcdMetricsUnavailable` | warning | Fewer etcd scrape targets than control-plane nodes for 15 minutes | Compare `kubeEtcd.endpoints` with the nodes, and check the `kube-etcd` target in Prometheus. |

Start every investigation read-only:

```sh
mise exec -- talosctl etcd status
mise exec -- talosctl etcd alarm list
mise exec -- talosctl logs etcd
```

`SilentRebootPrecursor` also reads etcd's failed-proposal counter, so it depends on this scrape too.

### Defragmentation

etcd reuses free pages, so fragmentation alone does not grow the database, and defragmenting does not change what etcd stores. It only gives back quota and disk space, and the database grows back toward its working size afterwards. While it runs, the member blocks reads and writes, which pauses that node's API server for a few seconds.

Defragment when `EtcdDatabaseFragmented` fires, when `EtcdDatabaseNearQuota` fires and most of the database is free, or after a `NOSPACE` alarm. Do not schedule it. Defragmenting is a live change and needs operator approval:

1. Confirm three healthy members and one leader with `talosctl etcd status`, no alarm in `talosctl etcd alarm list`, no other etcd alert except the one that prompted this, and no other node maintenance in progress. Note which member leads.
2. Defragment one follower with `mise exec -- talosctl -n <node> etcd defrag`. Name exactly one node: `talosctl` runs the command on every node you list at the same time.
3. Before the next member, check `talosctl etcd status` again: three members, one leader, matching raft indexes, no errors, and the defragmented member's DB size close to its size in use. The Kubernetes API must answer, and no new etcd alert may fire. Stop at the first failure.
4. Repeat for the other follower, then defragment the leader last.
5. If etcd had raised `NOSPACE`, clear it with `talosctl etcd alarm disarm` once every member is below its quota.

Defragmentation rewrites the same data, so there is nothing to roll back. If a member does not return healthy, stop and treat it as a member failure. Never defragment a member while another is unhealthy.
