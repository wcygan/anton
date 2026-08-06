# Network diagnostics

Read-only inspection of node-level networking: interfaces, addresses, routes, bonds, VLANs, MTU, the control-plane VIP, DNS, and inter-node reachability. This stops at the host network — for pod-to-pod or service-level networking, that's the `kubernetes` / Cilium layer.

All commands use the shape from `SKILL.md`:

```sh
TALOS="mise exec -- talosctl --talosconfig ./talos/clusterconfig/talosconfig"
K8S1="100.75.61.79"
K8S2="100.87.89.3"
K8S3="100.100.217.100"
NODES="$K8S1,$K8S2,$K8S3"
```

Use the same Tailscale IP for `--endpoints` and `--nodes` in direct queries.
For the standard all-node check, run `mise exec -- task talos:health` so a
node that is unreachable is reported instead of omitted.

## Fleet-wide interface snapshot

```sh
$TALOS -e $K8S1 -n $NODES get links                  # interfaces: name, state, MTU, MAC
$TALOS -e $K8S1 -n $NODES get addresses              # IPv4/IPv6 per link
$TALOS -e $K8S1 -n $NODES get routes                 # default + per-link routes
$TALOS -e $K8S1 -n $NODES get resolvers              # DNS servers in effect
$TALOS -e $K8S1 -n $NODES get hostname               # configured vs effective
```

| Query | What to look for |
| --- | --- |
| `get links` | Physical interface `UP`, correct MTU (typically 1500), correct MAC. Bonded pairs appear as `bondX` + member links. |
| `get addresses` | One static `/24` on the main interface matching `talos/talconfig.yaml`. The VIP `192.168.1.101` appears on whichever control plane currently owns it. |
| `get routes` | Default route via `192.168.1.254`. No unexpected duplicates or blackholes. |
| `get resolvers` | DNS matches the upstream configured in the machine config. |
| `get hostname` | Matches the `hostname:` in `talos/talconfig.yaml` for that node. |

## Control-plane VIP inspection

Anton uses a shared VIP (`192.168.1.101`) that floats across `k8s-1/2/3`. Only one node owns it at a time; `machined` runs the election.

```sh
# Which node currently holds the VIP?
$TALOS -e $K8S1 -n $NODES get addresses | rg 192.168.1.101

# machined is the service that manages it:
$TALOS -e $K8S1 -n $NODES service machined
$TALOS -e $K8S1 -n $NODES logs machined | rg -i 'vip'
```

Symptoms of VIP trouble:

- **Flapping** (VIP bouncing every few seconds) — usually a gratuitous-ARP conflict with another host on the LAN, or a switch with aggressive ARP aging. Check `dmesg` for `neighbor table overflow` or `duplicate IPv4 address`.
- **Held by a node that just rebooted** — VIP resolves but times out. The old holder lost the lease ungracefully; wait for re-election or check whether `machined` is healthy on all three.
- **Never acquired after a cold cluster boot** — no CP has taken ownership. `machined` logs on each will say why (usually ACL / etcd-not-ready).

## Inter-node reachability

When something feels like a partition, confirm raw L3 reachability between all three nodes. Talos doesn't ship `ping`, but there are two indirect probes:

```sh
# 1. Etcd peers should all see each other.
$TALOS -n $K8S1 etcd members          # expects three HEALTHY members

# 2. Talos discovery service lists affiliates it has talked to.
$TALOS -e $K8S1 -n $NODES get affiliates
$TALOS -e $K8S1 -n $NODES get members
```

If `etcd members` shows one peer as unhealthy but the node is otherwise up, it is almost certainly network-level: MTU mismatch, firewall ACL, duplicate IP, or a dead switch port.

From the **workstation** (not from nodes — Talos has no shell) you can L4-probe:

```sh
nc -vz "$K8S1" 50000         # Talos apid
nc -vz "$K8S1" 6443          # Kubernetes API
nc -vz "$K8S1" 2379          # etcd client (control plane only)
nc -vz "$K8S1" 2380          # etcd peer (control plane only)
```

Use the current Tailscale IP variables above rather than assuming MagicDNS is
available on the operator workstation. If a port refuses over Tailscale but
accepts on-LAN, the Tailscale extension on the node may have de-authed — see
`anton-remote-access` for re-auth guidance.

## MTU and bond diagnostics

MTU mismatch is a classic silent failure: small packets pass, large ones drop. If Anton ever grows a VLAN or bonded NIC in front of a node:

```sh
$TALOS -e $K8S1 -n $NODES get links | rg -i 'mtu|bond'
$TALOS -n $K8S1 dmesg | rg -i 'bond|link down|link up|mtu'
```

Healthy bond:

- Each member link reports `master bondX` and `UP`
- The `bondX` master reports `UP` with the negotiated mode
- MTUs match across member links and the master

One member `DOWN` = redundancy loss but no outage. Fix at the switch side; Talos doesn't own that layer.

## DNS and NTP (network-adjacent)

```sh
$TALOS -e $K8S1 -n $NODES get resolvers              # upstream DNS
$TALOS -e $K8S1 -n $NODES service timed              # NTP sync health
$TALOS -e $K8S1 -n $NODES time                       # wall clock per node
```

Clock drift > 1s across nodes will break etcd — cross-link `references/health.md` for the etcd symptom list. Flaky upstream DNS manifests as slow `trustd` / `apid` cert operations and slow `machined` discovery.

## CNI boundary

Cilium runs **above** this layer. If the host network is clean (links UP, VIP held, DNS resolving, etcd quorum healthy) but pod networking is broken, the problem belongs to Cilium — run `cilium status` and `cilium connectivity test` instead. That's outside this skill's scope.

## Docs — WebFetch when unsure

- `https://docs.siderolabs.com/talos/v1.12/talos-guides/network/` — network guide (static, DHCP, VLAN, bond, VIP)
- `https://docs.siderolabs.com/talos/v1.12/learn-more/resources` — resource schemas (`links`, `addresses`, `routes`, `resolvers`, `affiliates`, `members`)
- `https://docs.siderolabs.com/talos/v1.12/reference/configuration/network/` — machine config network field reference
