---
name: anton-remote-access
description: Remote access reference for Anton. Use when Claude needs to reach or reason about kubectl, flux, talosctl, Tailscale target resolution, kubeconfig, talosconfig, off-LAN node access, or failed connectivity to k8s nodes.
allowed-tools: Read, Bash
---

# Anton remote access

Use Anton's repository-owned contexts and target resolver from a workstation.
The workstation is not assumed to be on the node LAN.

## TL;DR

```sh
# Talos — the wrapper resolves the complete Tailscale endpoint set
mise exec -- task talos:targets
mise exec -- task talos:health

# Kubernetes — via the repository kubeconfig and expected context
mise exec -- kubectl config current-context
mise exec -- kubectl get nodes
```

## Access paths

Talos inspection resolves `k8s-1`, `k8s-2`, and `k8s-3` through
`scripts/cluster-targets.py`. It accepts a complete live `tailscale status
--json` result or falls back as one set to `scripts/cluster-targets.json`; it
never mixes live and fallback addresses. Generated LAN endpoints remain valid
only from the home network.

The Tailscale extension is configured per-node in `talos/patches/<hostname>/`;
the auth key is in `talos/talenv.sops.yaml`. State is in memory
(`TS_STATE_DIR=mem:`), so a reboot can leave a stale device entry. Report that
entry as an external operator handoff; removing it requires separate approval.

## talosctl

The generated talosconfig at `talos/clusterconfig/talosconfig` is gitignored
(produced by `mise exec -- task talos:generate-config`). It contains LAN
defaults, so direct off-LAN queries must use the shared resolver:

```sh
NODES="$(python3 scripts/cluster-targets.py resolve --format addresses --show-addresses)"
ENDPOINT="${NODES%%,*}"
mise exec -- talosctl --talosconfig ./talos/clusterconfig/talosconfig \
  --endpoints "$ENDPOINT" --nodes "$NODES" <read-only-command>
```

Common read-only queries:

```sh
mise exec -- talosctl ... get disks        # block devices (NVMe, loops, rbd)
mise exec -- talosctl ... get members      # cluster membership
mise exec -- talosctl ... get addresses    # interface addresses
mise exec -- talosctl ... version          # server vs client version skew
mise exec -- talosctl ... dmesg -f         # kernel log (follow)
mise exec -- talosctl ... logs <service>   # machined / kubelet / etcd / etc.
```

If talosctl errors with `failed to determine endpoints` or `talos config file
is empty`, pass the repository talosconfig and resolved endpoints explicitly.

## kubectl

The expected Kubernetes context is the Tailscale operator proxy, with
`admin@anton` only as fallback. Check the repository context before
troubleshooting connectivity:

```sh
mise exec -- kubectl config current-context
mise exec -- kubectl config view --minify
```

## What NOT to commit

Per the top-level repository rule, keep the real tailnet name out of Git. Use
`<tailnet-name>.ts.net` in documentation, examples, and commit messages. The
only committed Tailscale node-address fallback is
`scripts/cluster-targets.json`; other docs and skills consume its resolver.

If you discover a real tailnet name in the working tree, do not commit until it has been replaced with the placeholder.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `failed to determine endpoints` | generated config has unusable defaults | resolve the complete target set with `scripts/cluster-targets.py` |
| `talos config file is empty` | default config has no context | pass `--talosconfig ./talos/clusterconfig/talosconfig` explicitly |
| `i/o timeout` on a LAN IP | workstation is off-LAN | use `mise exec -- task talos:health` or the resolved Tailscale targets |
| `server version X is older than client version Y` | client/server skew, harmless until a major release | plan a Talos upgrade via the `upgrade-talos-or-k8s` skill |
| Live target resolution is incomplete | device signed out / key expired | inspect the resolver's fallback reason; re-auth only through an approved Talos workflow |
| `kubectl` hangs from off-LAN | wrong kubeconfig context | confirm the context and expected operator proxy before changing configuration |

## Related skills

- Upgrading Talos or Kubernetes versions → `upgrade-talos-or-k8s`
- Adding or replacing a node → `add-or-replace-node`
- Triaging a Flux sync that looks broken from a remote workstation → `debug-flux-reconciliation`
