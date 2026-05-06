# Evidence: iTCO_wdt is loaded but unfed; `panic_on_*_nmi` sysctls exist but are off; both lockup detectors are compiled out

**Date:** 2026-05-06 (loop iteration #5, opus 4.7)
**Source:** Live `talosctl read /proc/sys/...`, `talosctl read /proc/modules`, `talosctl get watchdogtimerconfigs`, `talosctl list /dev/` on all three nodes.
**Status:** One revived hypothesis, one new high-leverage forensic lever, one verified structural constraint.

## Three findings

### Finding 1 — iTCO unfed-watchdog hypothesis is **revived** by the 2026-05-05 cluster-wide event

State observed on all three nodes (k8s-1, k8s-2, k8s-3):

```
$ talosctl read /proc/modules | grep -i tco
iTCO_wdt 12288 0 - Live 0x0000000000000000
iTCO_vendor_support 12288 1 iTCO_wdt, Live 0x0000000000000000
watchdog 45056 1 iTCO_wdt, Live 0x0000000000000000

$ talosctl list /dev/ | grep watch
watchdog
watchdog0

$ talosctl get watchdogtimerconfigs
NODE   NAMESPACE   TYPE   ID   VERSION   DEVICE   TIMEOUT
(no rows on any node)
```

`iTCO_wdt` (Intel TCO Watchdog) is loaded with **refcount 0** on every node — no process has `/dev/watchdog0` open. `WatchdogTimerConfig` is empty cluster-wide — Talos is not feeding the watchdog. This is the exact state Talos issue [#10556](https://github.com/siderolabs/talos/issues/10556) flagged: if BIOS enables the iTCO timer at firmware level and the OS doesn't feed it, the watchdog hardware-resets the node with zero kernel logs.

`evidence-2026-04-30-web-research.md` raised this hypothesis but recorded a counter-argument: "iTCO_wdt loaded identically on k8s-1 and k8s-2 with no `WatchdogTimerConfig` configured on any node. If the watchdog is the cause, it should affect all nodes equally — but only k8s-2 reboots." It then marked **"Action needed: Verify watchdog BIOS settings per-node and confirm whether watchdog timeout differs. Consider explicitly configuring `WatchdogTimerConfig` on all nodes to ensure Talos feeds the watchdog, or disabling the TCO timer in BIOS."** — the action was never completed (no follow-up in `evidence-2026-05-04-bios-1.27-flash.md`, `evidence-2026-05-05-dual-silent-reboot.md`, or any iter-#0..#4 evidence).

The 2026-05-05 cross-node event materially weakens the original counter-argument. **All three nodes are now silent-reboot-capable** (k8s-1 and k8s-3 both reboot for the first time on 2026-05-05; k8s-2 holds for once). The "if it were iTCO, all nodes should reboot" reasoning is now consistent with observed behavior, not against it.

What changes the prior:
- The iTCO timer's typical default timeout (BIOS-configurable, 4 s to 10 min) is **roughly compatible** with intervals observed in the prior k8s-2 series (R3 → R4 = 16.8 h, R4 → R5 = 7 h — too long for a single iTCO countdown, but consistent with iTCO firing irregularly when something happens to stop the (currently nonexistent) feed).
- Without a feed loop active, the iTCO timer **doesn't continuously count down on a fixed schedule** — it counts only when something writes to it, which happens at boot in some BIOS modes, then never again. So an iTCO that fires irregularly when the boot-time write is somehow re-armed is plausible.
- A more likely mode: BIOS programs the iTCO to count down *during normal operation* and expects the OS to feed it; without a feed, the timer expires once on a deterministic schedule after boot. The fact that we see *multiple* silent reboots without all of them being a fixed interval after boot weakens this strong form.

So the hypothesis isn't proven, but it isn't ruled out either. **Easy to falsify and easy to fix.**

#### Discriminating test (cheap, software-only, reversible)

Add a Talos `WatchdogTimerConfig` to the global machine config:

```yaml
apiVersion: v1alpha1
kind: WatchdogTimerConfig
device: /dev/watchdog0
timeout: 5m0s
```

This makes Talos open `/dev/watchdog0`, set a 5-minute hardware timeout, and feed the watchdog every <5 min. Apply via `task talos:apply-node IP=<ip> MODE=auto` to one node first as canary.

- **If the canary node stops silent-rebooting and the others continue:** iTCO unfed-timeout was the cause. Roll out cluster-wide.
- **If the canary node keeps silent-rebooting:** the silent reboots are not iTCO-driven. Hypothesis falsified at the cost of one canary reboot interval.

Alternative discriminator (no config change): blacklist the `iTCO_wdt` module on one node via Talos `KernelModulesConfig` (`disabled: [iTCO_wdt]`). If the BIOS-side timer is what's firing, removing the module won't help because the hardware timer is independent of the driver. So this test specifically distinguishes "BIOS-active iTCO with no driver feeding" (driver-blacklist doesn't fix) from "driver-mediated iTCO" (driver-blacklist fixes).

### Finding 2 — Three `panic_on_nmi` sysctls are writable but disabled — high-leverage forensic lever

State observed on all three nodes:

```
kernel/panic_on_unrecovered_nmi = 0
kernel/panic_on_io_nmi          = 0
kernel/unknown_nmi_panic        = 0
```

These three sysctls control whether hardware-induced NMIs (Non-Maskable Interrupts) cause a kernel panic with full traceback, or are silently swallowed. The defaults Talos ships are `0` (silent swallow). On Raptor Lake hardware where MCE (Machine Check Exception) escalation produces NMIs, this means an MCE-induced silent reboot would leave **no kernel log trace**.

**Setting them to `1` converts a class of silent failures into logged failures.** Trade-off: any unrelated hardware NMI (rare on a Linux server but not zero) would also panic the system. This is the right trade for a forensic-investigation phase.

The sysctls are writable (no `NotFound`), so they can be set via Talos `SysctlConfig` patch:

```yaml
apiVersion: v1alpha1
kind: SysctlConfig
sysctls:
  kernel.panic_on_unrecovered_nmi: "1"
  kernel.panic_on_io_nmi: "1"
  kernel.unknown_nmi_panic: "1"
```

This is **independent of every other test** in plan 0013. It strictly improves forensic posture for the next event regardless of which hypothesis turns out to be correct. Recommended as a default for the rest of the silent-reboot investigation window. Cost: one config patch, no reboot needed (sysctls apply immediately on apply-config).

**Combined with the kernel sink restored at `35533bdb`, this is the strongest forensic surface available without rebuilding the Talos UKI.** A panic emits a full traceback to `/dev/kmsg` before the reboot; the kernel sink ships kmsg over UDP; UDP datagrams flush at write-time (per the comment in `talos/patches/global/machine-kmsg.yaml` — that's specifically why UDP was added alongside TCP). So if any next silent-reboot is NMI-induced, we get the traceback off the box.

### Finding 3 — Both software lockup detectors are compiled out (not just disabled)

Verified:

```
kernel/watchdog          = NotFound
kernel/nmi_watchdog      = NotFound
kernel/softlockup_panic  = NotFound
kernel/hardlockup_panic  = NotFound
kernel/watchdog_thresh   = NotFound
kernel/hung_task_panic   = NotFound
kernel/hung_task_timeout = NotFound
```

Absence of `/proc/sys/kernel/watchdog*` confirms `CONFIG_LOCKUP_DETECTOR=n` in the Talos kernel build. Absence of `/proc/sys/kernel/hung_task_*` confirms `CONFIG_DETECT_HUNG_TASK=n`.

This is the README's load-bearing assumption ("Talos kernel has no `CONFIG_HARDLOCKUP_DETECTOR` / `SOFTLOCKUP_DETECTOR`") — **verified for the first time, no prior evidence note recorded the actual proof**. This means there is no path to enable a software lockup detector without rebuilding Talos with a custom kernel config.

A custom Talos kernel build (via `imager` with overlay) is possible but high-effort. **The iTCO hardware watchdog (Finding 1) is the only available "kernel hang → forced reset on a deterministic timer" mechanism**. Combined with the NMI-panic sysctls (Finding 2), this gives:

- Kernel hang due to silent CPU wedge → iTCO timer fires after configured timeout → hardware reset (still silent on this node, but deterministic interval, and other nodes' kernel sinks may capture peer-side observation per iter #2)
- Kernel hang due to MCE / hardware NMI → panic with traceback → kernel sink ships traceback over UDP

The two together cover materially more failure modes than the current state.

## Stack ranking against plan 0013 acceptance criteria

| Action | Cost | Reversibility | Improves forensic surface? | Tests a hypothesis? |
|---|---|---|---|---|
| Set `panic_on_*_nmi=1` (Finding 2) | trivial — single SysctlConfig patch | trivial — flip back to 0 | **Yes (large)** | No — pure forensic lever |
| Add `WatchdogTimerConfig` 5m timeout (Finding 1) | small — one machine config edit | trivial — remove the doc | Modestly | Yes — iTCO unfed-watchdog hypothesis |
| Runtime PM-QoS DaemonSet (iter #3) | small — one DaemonSet manifest | trivial — `kubectl delete ds` | No | **Yes — Vmin/C-state hypothesis directly** |
| Custom Talos kernel with `CONFIG_LOCKUP_DETECTOR=y` | high — `imager` overlay + reinstall | high — re-imager + reboot | Yes (largest) | No — pure forensic lever |
| Plan 0013 Phase 3 controlled reboot | medium — one node down | One reboot of recovery work | Yes | Yes — cascade hypothesis |

The first three rows are **mutually independent** and **cumulatively additive**. They could all land in a single PR with a small Talos config patch + a small DaemonSet manifest and meaningfully improve the next-event forensic catch.

## Verification trail

```
$ for n in k8s-1 k8s-2 k8s-3; do echo === $n ===; for f in panic_on_unrecovered_nmi panic_on_io_nmi unknown_nmi_panic watchdog hung_task_panic; do v=$(talosctl --endpoints $n -n $n read /proc/sys/kernel/$f 2>&1); printf "  %-28s = %s\n" "$f" "$v"; done; done
=== k8s-1 ===
  panic_on_unrecovered_nmi    = 0
  panic_on_io_nmi             = 0
  unknown_nmi_panic           = 0
  watchdog                    = error reading: ... no such file or directory
  hung_task_panic             = error reading: ... no such file or directory
=== k8s-2 ===  (identical)
=== k8s-3 ===  (identical)

$ for n in k8s-1 k8s-2 k8s-3; do echo === $n ===; talosctl --endpoints $n -n $n get watchdogtimerconfigs; done
NODE   NAMESPACE   TYPE   ID   VERSION   DEVICE   TIMEOUT
(0 rows on every node)
```

## Cross-references

- `evidence-2026-04-30-web-research.md` — raised the iTCO hypothesis; left action unclosed
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — `install.extraKernelArgs` blocked, but **`SysctlConfig` is not blocked** (it applies at runtime, not at boot); the NMI-panic sysctls are deployable today
- `evidence-2026-05-06-k8s-2-precursor-nic-flap.md` (iter #2) — kernel-sink-armed + NMI-panic-on + iTCO-feeding gives a much better chance at capturing a re-flap-style precursor signature on the next event
- `evidence-2026-05-06-betty-retention-and-flap-rates.md` (iter #4) — once betty has ≥48 h retention, it complements the in-cluster forensic surface
- Plan 0013 Phase 1 acceptance criterion 1 (`Vector kernel sink demonstrably captures kernel-side trace through the next silent-reboot event`) — current forensic surface counts on the next event being a soft event that can write to kmsg before reset. NMI-panic sysctls extend this to MCE-class hardware events. iTCO feeding bounds the worst-case time-to-reset.
- Talos issue #10556 — the upstream description of iTCO-unfed-silent-reboot

## Suggested next action — three independent landings

I am surfacing, not applying, but the three independent recommendations below can land in a single small PR:

1. **Add `SysctlConfig` patch** to `talos/patches/global/`:
   ```yaml
   apiVersion: v1alpha1
   kind: SysctlConfig
   sysctls:
     kernel.panic_on_unrecovered_nmi: "1"
     kernel.panic_on_io_nmi: "1"
     kernel.unknown_nmi_panic: "1"
   ```
2. **Add `WatchdogTimerConfig`** to the same place (or a new file) with `device: /dev/watchdog0, timeout: 5m0s`. Apply to one canary node first.
3. **Author the iter-#3 PM-QoS DaemonSet** under `kubernetes/apps/kube-system/idle-mitigations/`.

Apply via `task talos:apply-node IP=<ip> MODE=auto` for (1) and (2). (3) is a Flux-managed DaemonSet.
