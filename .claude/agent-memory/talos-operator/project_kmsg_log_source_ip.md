---
name: KmsgLogConfig source-IP mapping in Vector sink
description: In talos-log-sink-vector kernel stream, k8s-1 shows as a 10.100.100.x Tailscale IP while k8s-2/k8s-3 show as 192.168.1.99/100 LAN IPs
type: project
---

Plan 0009 Phase 1 streams Talos kernel dmesg via KmsgLogConfig document (url `tcp://192.168.1.105:6001/`) to the Vector sink. When tailing `/vector-data-dir/talos-sink-YYYY-MM-DD.log` in `talos-log-sink-vector-0 -c rotator`, the `.host` field per kernel record is:

- `10.100.100.1` for k8s-1 (Cilium Tailscale-native routing picks the tailnet address as source)
- `192.168.1.99` for k8s-2
- `192.168.1.100` for k8s-3

**Why:** k8s-1's outbound path to the ClusterIP/sink Service lands on the Tailscale-native route first; k8s-2 and k8s-3 take the LAN path. This is expected, not a misconfig.

**How to apply:** When verifying "all three nodes streaming kernel logs", match on the `host` field but do NOT expect `192.168.1.98` for k8s-1 — you will miss it. Use `jq -r '.host' | sort | uniq -c` to confirm three distinct source IPs; `10.100.100.1` IS k8s-1.
