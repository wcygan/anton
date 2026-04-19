---
name: SFP+ mesh Phase 2 complete (plan 0004)
description: 2026-04-19 SFP+ /31 addressing rolled out to all 3 nodes via MODE=auto no-reboot; all 6 pings bidirectional; full-mesh ready for Phase 3 iperf3
type: project
---

Phase 2 of plan 0004 (SFP+ /31 addressing) applied cleanly on 2026-04-19.

**Outcome:**
- `task talos:apply-node MODE=auto` resolved to **"Applied configuration without a reboot"** on all three nodes (k8s-1, k8s-2, k8s-3). Adding networkInterfaces without touching existing ones is a non-disruptive change at Talos v1.12.6.
- Per-node verified addresses land on the right MACs:
  - k8s-1 enp2s0f0np0 (:a0) → 10.100.0.0/31; enp2s0f1np1 (:a1) → 10.100.0.2/31
  - k8s-2 enp2s0f0np0 (:b8) → 10.100.0.4/31; enp2s0f1np1 (:b9) → 10.100.0.1/31
  - k8s-3 enp2s0f0np0 (:a8) → 10.100.0.5/31; enp2s0f1np1 (:a9) → 10.100.0.3/31
- All 6 /31 pairs ping bidirectionally, RTT 0.18–0.49 ms (DAC copper).
- VIP 192.168.1.101 stayed on k8s-3 throughout; etcd leader and quorum unaffected.

**Why:** Phase 2 acceptance criterion #2 gate. Proved the config is safe and no-reboot before running Phase 3 (iperf3), Phase 4 (NAD), Phase 5 (Longhorn).

**How to apply:**
- Talos has no built-in `ping` — use `kubectl exec` into a host-network netshoot pod (hostNetwork: true, nodeSelector on hostname, NET_ADMIN/NET_RAW caps). `talosctl -- ping` does not exist; the `--` separator confuses talosctl flag parsing.
- The `jq '.spec.linkName | startswith(...)'` pre-flight check failed on null linkName entries — guard with `select(.spec.linkName != null)` or just use awk on tabular output.
- SFP+ NIC names on MS-01 are `enp2s0f0np0` and `enp2s0f1np1` (not `enp2s0`). The mgmt NIC is `enp87s0` (aliased to `ethSel0`). `ethSel1`/`ethSel2` aliases resolve at render time and show up on whichever enp2s0fN the MAC is on — don't assume ethSelN maps to a specific physical port.
- For non-disruptive additive network changes like this, MODE=auto is safe. MODE=no-reboot would be stricter but auto got the same result here.
