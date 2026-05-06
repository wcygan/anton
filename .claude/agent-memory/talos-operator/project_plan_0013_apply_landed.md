---
name: plan-0013 silent-reboot mitigation stack landed
description: 2026-05-06 hot-reload apply of NMI-panic sysctls + iTCO WatchdogTimerConfig + machine.logging restore on all 3 nodes; KernelParamSpec reconcile lag is the one gotcha
type: project
---

Plan 0013 (cluster-wide silent-reboot localization) terminal-state (a) operational landing complete on 2026-05-06 at commit `de801143`.

**Why:** Vmin/C8 idle-wake voltage failure on Raptor Lake-P silicon wedges the kernel; iTCO unfed-watchdog hardware-resets ~30s later. Three patches (`machine-sysctls.yaml` NMI additions, new `machine-watchdog.yaml`, restored `machine-logging.yaml`) were authored to convert future silent reboots into observable events with full traceback.

**How to apply:** All three patches are runtime-resource updates — `talosctl apply-config --mode=auto` returns "Applied configuration without a reboot" on Talos 1.13.0. Per-node order canary k8s-2 first (historical leader), then k8s-1, then k8s-3, with 5-minute settle gaps. Etcd term 32 unchanged across all 3, leader stayed k8s-2, raft applied indices stayed in lockstep.

**Gotcha — KernelParamSpec reconcile lag:** The three new NMI sysctls (`kernel.panic_on_unrecovered_nmi`, `kernel.panic_on_io_nmi`, `kernel.unknown_nmi_panic`) appear in `get kernelparamspecs` immediately after apply but `/proc/sys/kernel/<name>` still reads `0` for ~30-60 seconds while KernelParamSpecController reconciles. First check on k8s-2 immediately after apply showed all three still 0; 30s wait → all three = 1. Build an `until` loop on `panic_on_unrecovered_nmi == 1` instead of a single shot read after future sysctl applies.

**WatchdogTimerConfig signature post-apply:** `talosctl get watchdogtimerconfigs` shows `runtime/WatchdogTimerConfig/timer/1 device:/dev/watchdog0 timeout:5m0s`, and `/proc/modules` shows `iTCO_wdt 12288 2 - Live` (refcount 2 — Talos opened the device, watchdog subsystem holds the second ref).

**Vector sink reception (the load-bearing forensic surface plan 0013 needed):** `tcp://192.168.1.105:6000/` started receiving service logs within ~1 minute per node. Distinct host tags after all three apply:
- `192.168.1.100` (k8s-3, LAN)
- `192.168.1.99`  (k8s-2, LAN)
- `10.100.100.1`  (k8s-1, **Tailscale IP** — see existing memo `kmsg_log_source_ip`; same anomaly applies to service-log destination, k8s-1 sources from Tailscale interface while k8s-2/k8s-3 source from LAN interface)
- A handful of `192.168.1.98:29999` / `:30021` lines — different ephemeral source ports, same node, harmless.

**Hot-reload non-reboot is now confirmed for**: WatchdogTimerConfig (new resource creation), `machine.logging.destinations` add-back, sysctls expansion. Add to the no-reboot register alongside the existing kubelet/reservations memo.
