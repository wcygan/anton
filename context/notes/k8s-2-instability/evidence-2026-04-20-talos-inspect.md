# 2026-04-20 — Talos watchdog + kernel cmdline + cilium-envoy inspection

Phase 1 steps 3 and 5 from the synthesis action list. Read-only `talosctl` and `kubectl` queries against k8s-2, with k8s-1 baseline where relevant.

Capture time: 2026-04-20 ~18:40 UTC. k8s-2 uptime 36–48 min during this window (boot at 17:52 UTC).

## What I was looking for

Four things, per `2026-04-20-multi-agent-rca.md`:

1. Is a Talos `runtime.watchdogTimer` armed on k8s-2?
2. Does the kernel cmdline have `nowatchdog`, `watchdog_thresh`, `panic=`, `hardlockup_panic=`?
3. dmesg signals for `softdog`, `iTCO`, `watchdog`, `NMI`, `hardlockup`, `rcu_sched`, `thermal`, `throttle`, `mce`, `oops`, `panic`, `nvme.*(hung|reset|error|timeout)`?
4. Has `cilium-envoy-fzfdj` been restart-looping on k8s-2? (cluster-triage hypothesis 2)

## Findings

### Talos runtime watchdog: NOT configured on any node

```
$ talosctl -n 100.87.89.3 get watchdogtimerconfigs -o yaml
(empty)
$ talosctl -n 100.87.89.3 get watchdogtimerstatuses -o yaml
(empty)
$ talosctl -n 100.75.61.79 get watchdogtimerconfigs -o yaml
(empty)    # k8s-1 baseline
```

k8s-2's `machineconfig` has empty `sysctls:` and empty `kernel:` sections. No per-node overrides. k8s-1, k8s-2, k8s-3 are rendered from the same `talos/talconfig.yaml` template → they share this config.

**Implication:** the Talos `runtime.WatchdogTimer` controller is not opening `/dev/watchdog` on any node. Nothing in the Talos userspace is petting the hardware TCO.

### Kernel cmdline: identical on k8s-1 and k8s-2

```
talos.platform=metal console=tty0 init_on_alloc=1 slab_nomerge pti=on
consoleblank=0 nvme_core.io_timeout=4294967295 printk.devkmsg=on
selinux=1 module.sig_enforce=1
```

Notable absences and presences:

| Flag | Present? | Meaning |
|---|---|---|
| `nowatchdog` | No | Kernel watchdogs (softdog, iTCO) remain enabled |
| `watchdog_thresh=N` | No | Default (10s) softlockup threshold |
| `panic=N` | No | Kernel panics do not auto-reboot — they hang forever |
| `panic_on_oops=1` | No | Non-fatal BUG()s don't panic — they continue running in undefined state |
| `hardlockup_panic=1` | No | CPU hard lockups print a trace but don't panic → silent hang |
| `printk.devkmsg=on` | Yes | Prereq for Tier-2 netconsole if we go there |
| `nvme_core.io_timeout=4294967295` | Yes | Effectively disables NVMe request timeout → a wedged NVMe controller will never self-recover, the kernel will wait forever |

**This kernel config makes k8s-2's observed reboot pattern almost indistinguishable from a hardware event.** Any soft hang, oops, or NVMe stall does not produce a panic trace — the system just sits there until the iTCO watchdog (hardware) or a power-level event resets it.

### iTCO_wdt hardware watchdog: present on k8s-1 and k8s-2 identically

k8s-2 dmesg (current boot):
```
iTCO_vendor_support: vendor-support=0
iTCO_wdt iTCO_wdt: Found a Intel PCH TCO device (Version=6, TCOBASE=0x0400)
iTCO_wdt iTCO_wdt: initialized. heartbeat=30 sec (nowayout=0)
```

k8s-1 dmesg: **exactly the same three lines** (different timestamps — booted 2026-04-16).

`/dev/watchdog` and `/dev/watchdog0` character devices exist on k8s-2. Neither is held open by a Talos service (no `watchdog` service in `talosctl get services`).

**`nowayout=0`** means: if `/dev/watchdog` is opened and then closed cleanly (single `V` magic-close write), the timer is stopped. If it's opened and the process dies without closing, the timer keeps running and fires after 30s. Since no Talos process opens it, the timer should be dormant.

**Critical implication for the talos-operator hypothesis:** for the iTCO TCO watchdog to be the reboot cause, *something* must open `/dev/watchdog` and then stop petting it. Nothing in Talos currently does so. BIOS-armed pre-boot handover is possible in theory but would affect k8s-1 equally → it hasn't rebooted in 94h, so BIOS-armed-TCO is not the distinguishing factor.

→ **talos-operator's "silent hardware watchdog" hypothesis is weakened but not disproved.** It remains the best explanation for the 50s-silent signature if a *soft* hang (CPU stuck with interrupts disabled) were to fire the iTCO — which is precisely what hardlockup_panic would diagnose but can't without the sysctl set.

### dmesg: current boot is clean

Filters applied: `watchdog|thermal|throttl|mce|oops|panic|nvme.*(hung|reset|error|timeout)`, ex-ACPI/LAPIC noise.

- No thermal throttling
- No MCE (machine check exception)
- No NVMe errors — all three controllers (`nvme0`, `nvme1`, `nvme2`) initialize cleanly, host memory buffer allocated, 20/0/0 default/read/poll queues, partitions enumerated (`nvme1n1: p1 p2 p3 p4 p5 p6` — standard Talos layout, p4=META, p5=STATE on XFS)
- `XFS (nvme1n1p5): Ending clean mount` — Talos STATE filesystem came up cleanly this boot
- `CPU0: Thermal monitoring enabled (TM1)` — only TM1 (older), not TM2 with frequency scaling — typical for Talos minimal kernel
- Only 2 thermal zones registered (`LNXTHERM:00`, `x86_pkg_temp`). No per-core zones.

### Current thermal state: idle cool

```
zone0 (LNXTHERM:00): 27800 mC   = 27.8°C (ACPI chassis)
zone1 (x86_pkg_temp): 46000 mC  = 46.0°C (CPU package)
```

Tells us **nothing** about load-time behaviour — this is ~48 minutes post-boot. A cold reading can't falsify a thermal-under-load hypothesis. Continuous thermal monitoring across another reboot is the only way to know.

### machinestatus / machined logs

```
stage: running
ready: true
unmetConditions: []
```

`talosctl logs machined | grep 'reboot|shutdown|sequencer|panic|fail|error'` returned zero hits. Talos `machined` logs are an in-memory ring (not persisted to the STATE partition) — this boot has had no reboot events yet, and previous boots' logs are gone.

### cilium-envoy-fzfdj on k8s-2: exonerated

`restartCount=2` — but the lastState shows:

```json
{
  "finishedAt": "2026-04-20T17:52:25Z",   // 7s after node boot
  "exitCode": 255,
  "reason": "Unknown",
  "startedAt": "2026-04-20T14:10:30Z",    // right after the 14:10 reboot
  "message": "... shutting down parent after drain"   // Envoy hot-restart
}
```

Three things this proves:

1. The container's 2 restarts track the 2 most recent node reboots on k8s-2 (14:10 and 17:52 UTC) — **restart count = reboot count, not container instability**.
2. The log line `shutting down parent after drain` at 14:25:48 (15 min after first start) is **Envoy hot-restart behaviour** triggered by Cilium operator pushing a config update. Normal.
3. k8s-1 and k8s-3 have `restartCount=0` on their cilium-envoy pods. The k8s-2 restart count is not cluster-wide Cilium churn.

**→ cluster-triage hypothesis 2 (cilium-envoy as reboot trigger) is dismissed.**

## Hypothesis table update

| Hypothesis | Status after Phase 1 steps 3+5 | Why |
|---|---|---|
| Longhorn unmount deadlock → dirty reboot cascade | **Still live** | Not testable from current-boot data alone; need previous-boot kubelet log (gone) or a reproduction. Apr 18 smoking-gun log still stands. |
| Silent hardware/kernel watchdog (iTCO) | **Weakened.** Hardware exists on k8s-1 identically; no Talos process opens /dev/watchdog; should not be ticking. Remains best explanation for 50s silent signature IF a soft CPU hang were somehow arming it pre-boot. | |
| Hardware thermal / NVMe hang / stale BIOS | **Strengthened.** Single-node-exclusive pattern; cmdline config makes soft hangs silent; NVMe self-recovery disabled. 46°C idle is uninformative. | |
| cilium-envoy restart-loop as trigger | **Dismissed.** | Restart count mirrors reboot count; drain-parent is normal Envoy hot-restart. |
| Supervisor automation (kured etc.) | **Dismissed.** | No kured, no system-upgrade-controller installed in the cluster. |

## What to do with this

**For Phase 2 (if we get there):** talos-operator's sysctl recommendations become higher-priority than originally ranked. Specifically:

- `kernel.panic=10` — auto-reboot 10s after a panic, preserves a reboot marker
- `kernel.panic_on_oops=1` — turns BUG()s into panics
- `kernel.hardlockup_panic=1` — turns CPU hard-lockups into panics with dmesg trace
- `kernel.softlockup_panic=1` — turns soft lockups into panics

All four would be set via `machine.sysctls:` in `talos/talconfig.yaml`. They convert today's silent hangs into at-minimum a dmesg trail (preserved via Tier-1 `machine.logging.destinations`) that names the stuck CPU/process.

**Phase 1 remaining:**

- Step 2 — BMC SEL pull: **void.** MS-01 has no BMC/IPMI/Redfish. See [`corrigendum-2026-04-20-no-bmc.md`](corrigendum-2026-04-20-no-bmc.md). The in-band equivalent (Talos `machine.logging.destinations`) is a Phase 2 mutation, not Phase 1.
- Step 4 — Minisforum BIOS version check. Completed — see [`evidence-2026-04-20-bios-matrix.md`](evidence-2026-04-20-bios-matrix.md).

## Files produced this session

- `evidence-2026-04-20-reboot-count.md` — Phase 1 step 1 (partial, Prometheus blocked)
- `evidence-2026-04-20-talos-inspect.md` — this file, Phase 1 steps 3 + 5
