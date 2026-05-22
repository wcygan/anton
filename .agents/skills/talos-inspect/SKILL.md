---
name: talos-inspect
description: Read-only Talos OS triage for Anton. Use to check cluster health, node readiness, etcd quorum, Talos services, disks, NVMe inventory, install disks, routes, interfaces, MTU, VIP, inter-node reachability, DNS, or suspected node-level failures.
---

# Talos Inspect

Goal: Diagnose Anton below the Kubernetes workload layer with read-only Talos and kubectl commands.

Success means:
- Health, disks, and network checks use the repo talosconfig.
- The report names the first failing layer and the evidence behind it.
- Findings hand off mutating fixes to an operator-approved workflow.

Stop when: the Talos layer is classified as healthy, degraded, or blocked by connectivity/tooling.

## Workflow

1. Read `talos/AGENTS.md`.
2. Pick the relevant reference:
   - `references/health.md` for node, etcd, service, and control-plane health.
   - `references/disks.md` for install disks, NVMe, volumes, and Longhorn disk inputs.
   - `references/network.md` for interfaces, routes, bonds, VIP, DNS, MTU, and reachability.
3. Run read-only checks only.
4. Return a ranked finding list with command evidence and the next safe handoff.

## Command Shape

```sh
TALOS="talosctl --talosconfig ./talos/clusterconfig/talosconfig"
$TALOS -e k8s-1 -n k8s-1,k8s-2,k8s-3 health
$TALOS -e k8s-1 -n k8s-1,k8s-2,k8s-3 service etcd
$TALOS -e k8s-1 -n k8s-1,k8s-2,k8s-3 get disks
kubectl get nodes -o wide
```

Use the Tailscale MagicDNS names so inspection works off-LAN.

## Boundaries

Treat `apply-config`, `upgrade`, `reset`, `bootstrap`, reboot, and etcd member changes as mutation handoffs. Provide the command and safety gates; wait for the operator to approve execution.
