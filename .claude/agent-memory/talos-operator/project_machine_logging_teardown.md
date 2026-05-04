---
name: machine.logging teardown hot-reload
description: Removing machine.logging.destinations from Talos 1.13 machineconfig is a no-reboot apply; rolled out on all 3 nodes 2026-05-04 (plan 0007 Phase 5)
type: project
---

Plan 0007 Phase 5 (2026-05-04): removed the temporary Vector-sink TCP target `tcp://192.168.1.105:6000` from `talos/patches/global/machine-logging.yaml` by deleting the patch entirely and dropping its include from `talos/talconfig.yaml`. Rolled out on all 3 nodes via direct talosctl with `--mode=auto`, order k8s-2 -> k8s-3 -> k8s-1. Each node reported "Applied configuration without a reboot". k8s-2 boot ID `28688229-2d15-4216-b028-8b558a5530fe` unchanged across the entire rollout. etcd 3/3 throughout.

**Why:** confirms `machine.logging.destinations` (service log forwarding) is hot-reloadable on Talos 1.13 — no different from the kubelet-extraConfig hot-reload behavior already noted. Distinct from `KmsgLogConfig` (kernel stream), which is also hot-reloadable but a separate resource.

**How to apply:** future teardowns or additions of `machine.logging.destinations` can be done with `MODE=auto` (or direct talosctl `--mode=auto`) without reboot planning. The `logginglinks` COSI resource type does NOT exist — verify removal via `talosctl get machineconfigs -o yaml | grep -A2 '^\s*logging:'` (returning nothing) rather than via a dedicated resource type.

**Off-LAN invocation (validated 3x in this rollout):**
```
talosctl --talosconfig ./talos/clusterconfig/talosconfig \
  --endpoints <tailscale-ip> --nodes <tailscale-ip> \
  apply-config --file ./talos/clusterconfig/kubernetes-<node>.yaml --mode=auto
```
Tailscale IPs at the time: k8s-1=100.75.61.79, k8s-2=100.87.89.3, k8s-3=100.100.217.100. The Taskfile `task talos:apply-node` precondition uses LAN endpoints and fails off-LAN — direct talosctl is the working path.
