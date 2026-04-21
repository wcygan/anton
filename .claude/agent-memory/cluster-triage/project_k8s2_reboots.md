---
name: k8s-2 reboot saga
description: k8s-2 rebooted 9+ times between 2026-04-13 and 2026-04-20; suspected Longhorn DaemonSet unmount deadlock
type: project
---

k8s-2 in the anton cluster has rebooted 9+ times in the week of Apr 13-20 2026 (at least one more by 2026-04-20 ~15:00 UTC, on top of the 9 already logged). k8s-1 and k8s-3 uptime 90h+ over the same window — single-node problem.

**Why:** Apr 18 reboot had a kubelet log smoking gun — graceful shutdown manager timed out (`context deadline exceeded`) unmounting longhorn-csi-plugin, longhorn-manager, engine-image, longhorn-ui, and node-exporter host-path volumes. Classic Longhorn-on-DaemonSet shutdown deadlock. Node went down dirty, e2fsck ran on the Longhorn ext4s at next boot.

**Blind spot:** Talos sequencer shutdown phase logs go via kernel `printk` only; the kernel ring buffer is wiped at every boot. `/var/log/kernel.log` does not persist. No off-box logging configured yet. Root cause for most reboots unknown.

**How to apply:**
- Full triage notes at `/Users/wcygan/Development/notes/ideas/k8s-2-reboot-issues.md`.
- Recommended fix-out-of-the-gate: Tier 1 = `machine.logging.destinations[]` to UDP collector on tailnet; Tier 5 = bump kubelet `shutdownGracePeriodRequested` above 30s.
- k8s-2 is NOT holding kube-controller-manager / kube-scheduler / cilium-operator / any Flux controller / any l2announce lease as of 2026-04-20 — leader thrash is ruled out for downstream blast radius.
- Neither kured nor system-upgrade-controller is installed; reboots are NOT coming from an in-cluster operator.
- Don't re-litigate the OS-layer evidence; focus new triage on anything above Talos (Tailscale, Cilium k8s-2 specifics, eviction loops, apiserver connectivity from k8s-2, admission webhooks, PDB gaps).
