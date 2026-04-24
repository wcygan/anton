---
name: Kubelet reservation changes hot-reload without reboot
description: apply-config MODE=auto for kubelet extraConfig (systemReserved/kubeReserved/evictionHard) and machine nodeLabels/nodeTaints reloads in-place — no reboot, etcd term unchanged
type: project
---

On Talos 1.12.6, `talosctl apply-config --mode=auto` for the following changes produces `Applied configuration without a reboot` and the kubelet hot-reloads in seconds:

- `machine.kubelet.extraConfig.systemReserved`
- `machine.kubelet.extraConfig.kubeReserved`
- `machine.kubelet.extraConfig.evictionHard`
- `machine.nodeLabels`
- `machine.nodeTaints`

**Why:** validated on 2026-04-24 plan 0010 Phase 2 rolling apply across k8s-1/k8s-2/k8s-3. All three nodes applied in under 60s total wall-clock, etcd leader stayed k8s-1, raft term stayed 29 (no member restart), allocatable dropped cleanly, no pod eviction storm.

**How to apply:** For kubelet-only reservation/eviction tuning you do NOT need a full rolling reboot workflow. `MODE=auto` is sufficient and the etcd quorum gate collapses to a sanity check rather than a hard pause. Dry-run first with `--mode=no-reboot --dry-run` to confirm the diff scope is purely kubelet/labels/taints — if the diff touches kernel args, sysctls, extensions, or install disk fields, it WILL want a reboot and the normal one-at-a-time workflow applies.

**Allocatable math:** `kubectl` reports `cpu` allocatable as integer cores when whole cores are reserved (19950m → 19) — this is a display artifact, the 500m+500m reservations are real. Memory allocatable lands at exactly `capacity − (systemReserved + kubeReserved + evictionHard.memory.available)`, not the naive subtraction from pre-existing allocatable. Baseline allocatable already had internal eviction slack, so the observed delta will look ~0.6 GiB smaller than a pure reservation sum.

**Off-LAN gotcha:** `talosctl -e k8s-1 -n k8s-1,k8s-2,k8s-3 <cmd>` fails for the non-endpoint nodes with `name resolver error: produced zero addresses` because the `-e` server proxies via LAN IPs. Workaround: loop `-e $n -n $n` per node. This is an environmental quirk, not a config issue.
