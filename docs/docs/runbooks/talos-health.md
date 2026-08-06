---
sidebar_position: 1
---

# Talos health from the operator workstation

Anton uses Tailscale as the canonical remote path for Talos inspection. The
generated `talosconfig` contains the nodes' LAN addresses, so a workstation
outside the home LAN can otherwise reach one endpoint while silently failing
to inspect the other nodes.

## Standard check

Run the repository wrapper through Mise:

```sh
mise exec -- task talos:health
```

The wrapper:

1. probes k8s-1, k8s-2, and k8s-3 individually over their Tailscale IPs;
2. runs Talos's server-side health check through a reachable Tailscale endpoint;
3. checks Kubernetes node readiness through the Tailscale operator kubeconfig;
4. exits non-zero if any configured node could not be reached.

The health command discovers the cluster's internal etcd/control-plane
addresses server-side. Do not pass the Tailscale IPs as
`--control-plane-nodes`; those are not the addresses etcd advertises.

## Tailscale address mapping

The wrapper's default mapping is:

| Node | Tailscale endpoint |
| --- | --- |
| k8s-1 | `100.75.61.79` |
| k8s-2 | `100.87.89.3` |
| k8s-3 | `100.100.217.100` |

For a temporary address change, override the complete mapping so that the
wrapper continues to require all three nodes:

```sh
TALOS_TAILSCALE_NODES='k8s-1=100.x.x.x,k8s-2=100.x.x.x,k8s-3=100.x.x.x' \
  mise exec -- task talos:health
```

If an address changes permanently, update the mapping in
`scripts/talos-health.sh` and `context/hardware.md` together. Do not commit the
tailnet name; use node labels and Tailscale IPs.

## Flux version

The repository pins Flux CLI 2.9.3 in `.mise.toml`. Use Mise so a global
Homebrew or other installation cannot shadow the pinned version:

```sh
mise install
mise exec -- flux version
mise exec -- flux check
```

The same rule applies to `task reconcile`, which invokes the Mise-pinned Flux
binary internally.
