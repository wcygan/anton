---
name: talos-inspect
description: Read-only triage skill for Anton's Talos OS layer. Use to check cluster health, inspect node disks (install disks, serials, NVMe, volumes), or diagnose node networking (interfaces, routes, bonds, VIP, inter-node reachability, DNS, MTU). Keywords — talos health, cluster healthy, healthcheck, check nodes, node triage, etcd members, etcd quorum, talosctl get disks, NVMe, install disk, disk inventory, volume status, talos network, interface, link, route, bond, VIP, MTU, duplicate IP, resolvers, clock skew.
allowed-tools: Read, Bash
---

# Talos inspect

One-stop read-only diagnostic skill for Anton at the **Talos / OS layer**. Reach for this *before* `debug-flux-reconciliation`: if the kernel, disks, or node network is broken, application symptoms are downstream noise.

> **Read-only.** This skill never runs `apply-config` (without `--dry-run`), `upgrade`, `reset`, `bootstrap`, or `etcd remove-member`. If triage reveals a fix that needs one of those, stop and hand off to the matching skill (`upgrade-talos-or-k8s`, `add-or-replace-node`, etc.).

## Common invocation shape

Always use the repo's generated talosconfig (gitignored, produced by `task talos:generate-config`) and fan out to all three nodes:

```sh
TALOS="talosctl --talosconfig ./talos/clusterconfig/talosconfig"
NODES="k8s-1,k8s-2,k8s-3"

$TALOS -e k8s-1 -n $NODES <command>
```

Prefer Tailscale MagicDNS hostnames (`k8s-1` etc.) over `192.168.1.x` — the LAN addresses only work on-network. See `anton-remote-access` for how the endpoint wiring works.

## Decision tree — which reference file?

| You are asking… | Start with |
| --- | --- |
| "Is the cluster healthy?" / nothing specific | [`references/health.md`](references/health.md) |
| Node just rebooted, `NotReady`, or crash looping | [`references/health.md`](references/health.md) (services + dmesg) |
| Etcd quorum, members, leader, slow apply | [`references/health.md`](references/health.md) (etcd section) |
| Clock skew / NTP / time drift | [`references/health.md`](references/health.md) (clock section) |
| Planning a node replacement; picking an install disk | [`references/disks.md`](references/disks.md) |
| Disk full, NVMe errors, volume not mounted | [`references/disks.md`](references/disks.md) |
| Enumerating block devices or serials for `talconfig.yaml` | [`references/disks.md`](references/disks.md) |
| VIP unreachable, CNI flapping, node-to-node silence | [`references/network.md`](references/network.md) |
| Interface/link state, MTU, bond status, routes, DNS | [`references/network.md`](references/network.md) |

When in doubt, run the 60-second pulse below first, then jump.

## Golden 60-second health pulse

A yes/no "is anything obviously broken at the OS layer":

```sh
$TALOS -e k8s-1 -n $NODES version          # client/server skew
$TALOS -e k8s-1 -n $NODES health           # full Talos health probes
$TALOS -e k8s-1 -n $NODES service          # anything in Failed?
$TALOS -n k8s-1 etcd members               # 3 healthy members?
kubectl get nodes -o wide                  # all Ready, kubelet version sane?
kubectl get pods -A | rg -v 'Running|Completed'   # anything stuck?
```

If all six are clean, the OS layer is fine — the problem is upstream (Flux, app, ingress). Hand off to `debug-flux-reconciliation`.

## Hard rules

- **Read-only, always.** Never run `apply-config` without `--mode=no-reboot --dry-run`. This skill does not mutate machine config.
- **Never paste** `talosconfig`, `controlplane.yaml`, `worker.yaml`, or any `*.sops.*` contents into the conversation. File paths are fine; contents are not.
- **Never write the real tailnet name** into a committed file — use the placeholder `<tailnet-name>.ts.net` per repo `CLAUDE.md`. MagicDNS short hostnames (`k8s-1` etc.) are fine.
- **Don't improvise a fix.** If inspection reveals a mutation is needed (sysctl patch, version bump, bad disk, dead node), stop and hand off to the right skill.
- **Cite the docs for anything unfamiliar.** Talos `v1.12` docs at `https://docs.siderolabs.com/talos/v1.12/` — WebFetch before guessing at resource schemas or flag names.

## Related skills

- `anton-remote-access` — how `talosctl` endpoints, Tailscale MagicDNS, and kubeconfig are wired
- `debug-flux-reconciliation` — app-layer triage once the OS layer looks fine
- `upgrade-talos-or-k8s` — if inspection reveals a version skew that needs fixing
- `add-or-replace-node` — if inspection reveals a bad disk or a dead node
- `talos` (global, user-invocable) — Talos v1.12 docs lookup for unfamiliar resources
