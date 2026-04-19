# Longhorn storageNetwork over a VXLAN overlay — the macvlan host-shim

## TL;DR

Longhorn's `defaultSettings.storageNetwork` ships pod-to-pod replica traffic over a Multus secondary network. The setting's documentation only requires *pod-to-pod* reachability and silently assumes a flat L2 underlay where the host already has a native MAC on the storage segment. **If your storageNetwork's NAD parent is a virtual device (a VXLAN, GRE tunnel, anything that does L2 encapsulation on egress), bare macvlan-bridge and ipvlan-L2 NADs will both break Longhorn v1's iSCSI engine in the same way: the host-side iSCSI initiator cannot reach a co-located IM pod's iSCSI target.** The fix is to make the host itself a peer macvlan child of the same parent — a "host-shim" interface — so intra-host child↔child delivery sidesteps the parent's egress path.

This note explains the failure mode and the workaround as it landed in anton's plan 0004 Phase 5b (closed 2026-04-19). There is, as far as we can tell, **zero upstream Longhorn precedent** for this pattern; `longhorn/longhorn#9049` has been open since 2024-07 with the same failure on a flat L2 underlay and no fix.

## Why anton needed this

Anton's three MS-01 nodes are wired in a 10G SFP+ point-to-point full-mesh DAC topology — three separate /31 links, no shared L2 segment between the three SFP+ ports. To give Longhorn the shared subnet its single-NAD storageNetwork model assumes, a per-node DaemonSet (`kubernetes/apps/network/storage-vxlan/`) brings up `vxlan-storage` (VNI 100) carrying `10.100.1.0/24` across all three nodes. Each node owns a per-node VTEP loopback at `10.100.100.X/32`.

The NAD (`kubernetes/apps/storage/longhorn-config/app/networkattachment.yaml`) attaches Longhorn IM pods' second interface (`lhnet1`) onto `vxlan-storage` and pulls per-pod IPs via Whereabouts.

This works for pod-to-pod across nodes (the original Phase 4d smoke test). It does *not* work for the host-to-local-pod path that Longhorn v1 actually needs.

## The failure mode

Longhorn's v1 data engine has a split personality on the iSCSI path:

- The **iSCSI target** lives inside the IM pod, bound to the pod's `lhnet1` IP.
- The **iSCSI initiator** is the kernel's `iscsiadm`, which longhorn-manager invokes via `nsenter` into the **host** mount and net namespaces.

Whenever a workload on node N attaches a Longhorn volume, the engine on node N opens an iSCSI connection from the host netns to a replica's IM pod. If that replica is co-located on node N (which `defaultDataLocality: best-effort` actively encourages), the connection target is a pod on the *same host* as the initiator. That's the path that breaks.

Symptoms in longhorn-manager logs, surfaced via `printInstanceLogs` from the **engine** instance log (not the replica log — the replica only sees clean connects and EOFs):

```
iscsiadm: cannot make connection to 10.100.1.16: Host is unreachable
```

Volumes flap between `attached` and `detached`, `Robustness: unknown`, repeated `DetachedUnexpectedly` events.

## Why naive NADs fail over a VXLAN parent

Two NAD plugins were tried before the host-shim landed. Both failed for the same structural reason via different mechanisms.

### Attempt 1 — `type: macvlan, mode: bridge`

macvlan-bridge intentionally isolates the parent device from its children: the parent and its children each get distinct MACs, and the kernel does not forward frames between the parent and a same-host child. From the kernel's perspective, this is a feature — it stops the parent from accidentally seeing its own children's traffic. From Longhorn's perspective, it's the gate that breaks the host-to-local-pod path.

Cross-host traffic works (different hosts have different MACs reachable over the underlay), but every engine→target attach has to talk to the *local* IM pod first. Macvlan blocks it.

### Attempt 2 — `type: ipvlan, mode: l2`

ipvlan L2 children share the parent's MAC, so naively this looks like it should fix the macvlan isolation problem. It doesn't, in this topology. Live tcpdump on a probe pod confirmed the actual mechanism:

| where | what was seen |
|---|---|
| host `vxlan-storage` | sent ARP requests for `10.100.1.18` (the local pod's IP). Got replies for `10.100.1.2` (a remote VTEP) — so the vxlan tunnel itself is fine. |
| pod `net1` | **0 packets**. The ARP for the local pod never arrived. |

The host's TX path always egresses through the vxlan parent. ARP for the local pod is sent into the vxlan tunnel and broadcast to *remote* VTEPs — none of which answer, because that IP is local. The local ipvlan child of `vxlan-storage` never sees the ARP because the kernel does not loop the parent's TX back into local children. Same gate as macvlan, different mechanism.

## The host-shim fix

Add a peer macvlan-bridge child of `vxlan-storage` on each host, and migrate the host's per-node L3 address from the parent onto the shim:

```
vxlan-storage  (parent — L2 encap to remote VTEPs, no L3 address)
├── lhnet1-host  (macvlan/bridge child, MAC X, IP 10.100.1.{1,2,3}/24)  ← host iSCSI initiator
├── net1@IM-pod-A (macvlan/bridge child, MAC Y, IP 10.100.1.16/24)
├── net1@IM-pod-B (macvlan/bridge child, MAC Z, IP 10.100.1.17/24)
└── ...
```

The mechanism that makes this work is buried in the kernel's macvlan source: **macvlan-bridge maintains a hash table of child MACs, and when one child TX's a frame, the kernel checks whether the destination MAC is in the table. If it matches another local child, the frame is delivered directly without ever entering the parent's `ndo_start_xmit`** — which, for a vxlan parent, is what would have encapsulated the frame and shipped it to remote VTEPs.

The result:

- **Same-host traffic** (host-shim ↔ local pod) is delivered intra-host as a macvlan child↔child hop. No vxlan encap. ~100 µs RTT.
- **Cross-host traffic** (host-shim → remote pod, or pod → remote pod) falls through to the parent's egress, gets vxlan-encapsulated, and rides the SFP+ DAC. ~500 µs RTT.

## Wiring on anton

The shim is provisioned by the same DaemonSet that builds the VXLAN overlay (`kubernetes/apps/network/storage-vxlan/app/daemonset.yaml`). Idempotent ip-link bringup:

```sh
ip link show lhnet1-host >/dev/null 2>&1 || \
  ip link add lhnet1-host link vxlan-storage type macvlan mode bridge
ip link set lhnet1-host mtu 8950 up

# Migrate the L3 address from the parent to the shim.
ip addr del "${NODE_OVERLAY_IP}/24" dev vxlan-storage 2>/dev/null || true
ip addr replace "${NODE_OVERLAY_IP}/24" dev lhnet1-host
```

The `del || true` covers both legacy state (address still on the bare parent from a pre-Phase-5b cluster) and steady-state restarts (already migrated; `del` fails harmlessly).

The vxlan parent does not need its own L3 address for the tunnel to work — VXLAN's `local` parameter (set at link creation, here `10.100.100.X/32` on `dummy0`) is what the kernel uses for tunnel-source addressing. The L3 address that previously sat on `vxlan-storage` was only ever for the host's own traffic on the overlay segment, which is exactly what now goes through the shim.

The NAD itself stays as plain macvlan-bridge over the same parent. Pod IM IPs come from Whereabouts on `10.100.1.0/24` with `10.100.1.0/28` excluded — the exclusion reserves `.1/.2/.3` for the per-node host-shim addresses (and a small buffer).

## Verifying the wire

Reachability matrix for any new node or after a DaemonSet rollout:

```sh
# 1. Pod ↔ pod cross-node: must work over the VXLAN overlay.
kubectl exec lhnet-probe-k8s-1 -- ping -c 3 10.100.1.16   # remote pod IP

# 2. Host → local pod: the gate. ~100 µs RTT, no encap.
kubectl exec hostshell-k8s-1 -- ping -c 3 10.100.1.18      # local pod IP

# 3. Host → remote pod: shim → vxlan parent → remote. ~500 µs RTT.
kubectl exec hostshell-k8s-1 -- ping -c 3 10.100.1.16      # remote pod IP
```

All three legs must show 0% loss before flipping `defaultSettings.storageNetwork`. Phase 5b's full smoke test pinned six pods (three NAD-attached probes + three `hostNetwork: true` shells, one per node) to walk the whole matrix.

Confirm engine + replica binding once Longhorn picks up the storage network:

```sh
kubectl -n storage get engines.longhorn.io \
  -o custom-columns=VOLUME:.spec.volumeName,NODE:.spec.nodeID,STORAGEIP:.status.storageIP
```

Every running engine should show `STORAGEIP` in `10.100.1.16-254`, matching its node's IM pod `lhnet1` address. Same for replicas. If you see engine IPs in the Cilium pod CIDR (e.g. `10.42.x.y`), the storage network either isn't applied yet or the IMs haven't cycled — IMs only restart when they have no attached engines, so workloads using existing volumes must be detached (typically by scaling consumers down) for the new network to take effect.

## Throughput observed

Plan 0004 Phase 5b's burst test (10 GiB urandom dd, 2-replica volume, engine + local replica on `k8s-2`, remote replica on `k8s-3`):

| Direction | Iface | Rate (avg over 2-min window) |
|---|---|---|
| `k8s-2` TX | `enp2s0f0np0` (SFP+ #0) | **790 Mbps** |
| `k8s-2` TX | `enp2s0f1np1` (SFP+ #1) | **790 Mbps** |
| `k8s-2` TX | `lhnet1-host` (host shim → local IM) | 797 Mbps |
| `k8s-2` TX | `enp87s0` (2.5 GbE mgmt) | 0.4 Mbps |
| `k8s-3` RX | `enp2s0f0np0` (SFP+) | **988 Mbps** |
| `k8s-3` RX | `enp87s0` (mgmt) | 0.5 Mbps |

dd was urandom-bound at **146 MiB/s**, so the SFP+ ports were nowhere near their 9.76–9.90 Gbit/s iperf3 ceiling — the proportions are what matter. Replica traffic rides the SFP+ mesh; the 2.5 GbE management interface sees less than 1 Mbps of Longhorn traffic. A non-urandom write source (or a forced replica rebuild) will push the wire harder; the baseline doc has the rebuild-path measurement as a follow-up.

## When the shim is *not* needed

If the NAD's `master:` is a physical NIC on a flat L2 segment shared by all your nodes — which is what every Longhorn community example assumes — the host already has its own MAC on the storage subnet via the underlying interface. macvlan-bridge children can talk to other children of the same parent in that case because the parent's egress goes onto a real wire that all the pods' frames traverse anyway. No shim required.

The shim is specific to topologies where the NAD parent is a virtual device whose egress encapsulates: VXLAN, GRE, IPIP, anything where "send out the parent" doesn't deliver the frame to a same-host child. If you have one of those topologies, you'll hit the same gate.

## References

- Plan: [`context/plans/0004-sfp-mesh-multus-storagenetwork.md`](https://github.com/wcygan/anton/blob/main/context/plans/0004-sfp-mesh-multus-storagenetwork.md) — full forensics, tcpdump captures, every commit
- ADRs: 0009 (SFP+ full-mesh), 0017 (Multus adoption), 0018 (install-cni init container)
- Manifests:
  - `kubernetes/apps/network/storage-vxlan/app/daemonset.yaml` — overlay + shim provisioning
  - `kubernetes/apps/storage/longhorn-config/app/networkattachment.yaml` — NAD definition
  - `kubernetes/apps/storage/longhorn/app/helmrelease.yaml` — `defaultSettings.storageNetwork`
- Upstream issue (open, no fix): [`longhorn/longhorn#9049`](https://github.com/longhorn/longhorn/issues/9049)
- Longhorn storage-network docs (silent on host↔pod path): https://longhorn.io/docs/1.11.1/advanced-resources/deploy/storage-network/
