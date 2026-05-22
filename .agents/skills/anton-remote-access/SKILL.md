---
name: anton-remote-access
description: Remote access reference for Anton. Use when Codex needs to reach or reason about kubectl, flux, talosctl, Tailscale MagicDNS, kubeconfig, talosconfig, off-LAN node access, or failed connectivity to k8s nodes.
---

# Anton Remote Access

Goal: Use Anton's expected remote access paths for read-only inspection and operator-reviewed actions.

Success means:
- Kubernetes commands use the repo kubeconfig and the Tailscale operator proxy context.
- Talos commands use `./talos/clusterconfig/talosconfig`.
- Node references use Tailscale MagicDNS hostnames: `k8s-1`, `k8s-2`, `k8s-3`.
- Mutating commands wait for explicit operator approval.

Stop when: the access path is clear enough to run the requested read-only command or to hand the operator a safe mutation command.

## Environment

The repo sets these paths through `Taskfile.yaml` and `.mise.toml`:

```sh
KUBECONFIG=./kubeconfig
TALOSCONFIG=./talos/clusterconfig/talosconfig
SOPS_AGE_KEY_FILE=./age.key
```

The expected Kubernetes context is `tailscale-operator.<tailnet-name>.ts.net`; use the placeholder in committed docs. `admin@anton` is a fallback when Tailscale is unavailable.

## Read-Only Commands

```sh
kubectl config current-context
kubectl get nodes -o wide
flux get ks -A
flux get hr -A
talosctl --talosconfig ./talos/clusterconfig/talosconfig \
  -e k8s-1 -n k8s-1,k8s-2,k8s-3 health
```

Use `-e k8s-1` as the Talos endpoint and fan out with `-n k8s-1,k8s-2,k8s-3` for all-node inspection.

## Mutation Handoff

For apply, upgrade, reset, drain, delete, or reconcile commands, first present the exact command, target node or namespace, expected effect, and rollback or verification step. Proceed only after the operator explicitly approves that action.
