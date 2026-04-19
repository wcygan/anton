---
name: SFP+ mesh Phase 4b complete (plan 0004)
description: VTEP loopbacks (dummy0 /32) + SFP+ peer-VTEP /32 routes rolled out no-reboot on all 3 nodes; 6/6 VTEP pings bidirectional; Talos v1.12 requires DummyLinkConfig as a separate multi-doc YAML item
type: project
---

2026-04-19 Phase 4b of plan 0004 complete on all three nodes.

**Change set (commit 26db7f58):**
- Added `routes:` block to each of the 6 SFP+ `/31` `networkInterfaces` entries — each pointing a peer VTEP `/32` at the peer's `/31` /31 address (the DAC-local peer IP).
- Added a per-node `DummyLinkConfig` document via `talos/patches/<hostname>/` carrying the node's `/32` VTEP on `dummy0`:
  - k8s-1 dummy0 → 10.100.100.1/32
  - k8s-2 dummy0 → 10.100.100.2/32
  - k8s-3 dummy0 → 10.100.100.3/32

**talhelper v3.1.7 gotcha (verified):** talhelper silently drops `networkInterfaces[].dummy: true` and emits a regular `LinkConfig` without creating the dummy kernel device. Workaround: write `DummyLinkConfig` as a separate `apiVersion: v1alpha1 / kind: DummyLinkConfig / name: dummy0 / addresses: [...]` document, wired in via per-node `patches:`. Source check: talhelper `pkg/talos/networkconfig.go` never emits `DummyLinkConfigV1Alpha1`. Phase 4c (VXLAN overlay) and any future dummy/bridge/bond-beyond-basics links that need `kind: <Foo>LinkConfig` will need the same pattern.

**Rollout:**
- All 3 nodes: `MODE=auto` resolved to **NOREBOOT** (additive LinkConfig/DummyLinkConfig/RouteConfig are hot-applicable on Talos v1.12). Apply wall time ~<1s per node after talhelper render.
- Etcd stayed 3/3 healthy throughout, raft term 28 stable, leader k8s-3 never moved, raft index advanced linearly across all three (157475912 → 157477353 over the run).
- VIP 192.168.1.101 stayed on k8s-3 enp87s0 (unchanged).
- No service churn on any node.

**VTEP reachability matrix (6 pings, 3 echo each, all -I dummy0-source):**
| From → To | VTEP | RTT min/avg/max (ms) | loss |
| --- | --- | --- | --- |
| k8s-1 → k8s-2 | 10.100.100.2 | 0.277 / 0.333 / 0.401 | 0% |
| k8s-1 → k8s-3 | 10.100.100.3 | 0.074 / 0.151 / 0.231 | 0% |
| k8s-2 → k8s-1 | 10.100.100.1 | 0.292 / 0.377 / 0.490 | 0% |
| k8s-2 → k8s-3 | 10.100.100.3 | 0.182 / 0.220 / 0.244 | 0% |
| k8s-3 → k8s-1 | 10.100.100.1 | 0.196 / 0.270 / 0.312 | 0% |
| k8s-3 → k8s-2 | 10.100.100.2 | 0.311 / 0.336 / 0.374 | 0% |

Matches the Phase 2 regime (0.15–0.5 ms) — confirms VTEP traffic is riding the SFP+ DAC, not the 1G management path. Each node's route table shows `10.100.100.<peer>/32 via 10.100.0.<peer-31>` on the expected ethSel interface, so longest-prefix match forces the DAC.

**Execution note (non-blocking):** during the 6-ping run, the first attempt saw several `kubelet exec → apiserver-proxy closed network connection` transients through the tailscale-operator proxy. These resolved on single-exec retries and did not affect the underlay. Pattern: when running many parallel `kubectl exec` calls through the operator proxy, prefer sequential invocations to avoid the Tailscale/apiserver-proxy socket churn.

**Next:** Phase 4c (VXLAN overlay DaemonSet) will ride on these /32 VTEPs. The underlay contract is: each node has its own /32 on `dummy0`, and `ip route get <peer-vtep>` on each node hits the DAC interface of the corresponding link (not the management NIC, not any other path).
