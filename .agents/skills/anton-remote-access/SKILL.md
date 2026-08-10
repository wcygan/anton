---
name: anton-remote-access
description: Remote access reference for Anton. Use when Codex needs to reach or reason about kubectl, flux, talosctl, Tailscale MagicDNS, kubeconfig, talosconfig, off-LAN node access, or failed connectivity to k8s nodes.
---

# Anton Remote Access

Goal: Use Anton's expected remote access paths for read-only inspection and operator-reviewed actions.

Success means:
- Kubernetes commands use the repo kubeconfig and the Tailscale operator proxy context.
- Talos commands use `./talos/clusterconfig/talosconfig`.
- Talos inspection resolves all node endpoints through
  `scripts/cluster-targets.py`; do not copy its inventory into this skill or
  rely on generated LAN endpoints from an off-LAN shell.
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
mise exec -- kubectl config current-context
mise exec -- kubectl get nodes -o wide
mise exec -- flux get ks -A
mise exec -- flux get hr -A
mise exec -- task talos:targets
mise exec -- task talos:health
```

For direct inspection, resolve the effective set with
`python3 scripts/cluster-targets.py resolve --format addresses
--show-addresses`. Use one reachable address for `--endpoints` and the complete
comma-separated result for `--nodes`. The health wrapper is preferred because
it probes the complete set before running the server-side health check.

## Mutation Handoff

For apply, upgrade, reset, drain, delete, or reconcile commands, first present the exact command, target node or namespace, expected effect, and rollback or verification step. Proceed only after the operator explicitly approves that action.
