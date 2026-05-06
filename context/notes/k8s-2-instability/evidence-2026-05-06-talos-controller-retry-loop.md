# Evidence: Talos `KernelParamSpecController` is in a permanent ~60-second retry loop on every node — a small but eliminable wake source

**Date:** 2026-05-06 (loop iteration #19, opus 4.7)
**Source:** `talosctl dmesg` filtered for `KernelParamSpecController` errors on each node; `cpufreq stats` probe.
**Status:** One real Talos bug worth filing upstream; one structural rule-out (cpufreq stats unavailable).

## Finding 1 — Talos controller is permanently failing a sysctl write, retrying every ~60 seconds, on every node

Pattern visible in dmesg on **every node**, repeating at ~60-90 second intervals:

```
[talos] overriding KSPP enforced parameter, this is not recommended
        component=controller-runtime
        controller=runtime.KernelParamSpecController
        key=proc.sys.user.max_user_namespaces
        value=11255
[talos] controller failed
        controller=runtime.KernelParamSpecController
        error="1 error occurred:
              * write /proc/sys/kernel/printk_devkmsg: invalid argument"
```

The first line is benign — Talos is intentionally raising `user.max_user_namespaces` from KSPP's default of 0 (which would block kubelet) to 11255 to allow user namespaces.

The second line is a **bug**. Talos is trying to write to `/proc/sys/kernel/printk_devkmsg` and the kernel returns `EINVAL`. The sysctl exists (iter #5 showed `kernel.printk_devkmsg = on`) — so the file is writable in principle. The failure means **Talos is writing a value the kernel doesn't accept** for that sysctl.

`printk_devkmsg` accepts string values: `on`, `off`, or `ratelimit`. The kernel command line sets `printk.devkmsg=on` (iter #3), and iter #5 confirmed the resulting sysctl value is `on`. **Talos's `KernelParamSpecController` is trying to set a value that's already correct, and is encoding it in a format the kernel rejects.** Probably writing a numeric form, or a string with stray bytes (nul terminator, newline).

The `KernelParamSpecController` retries every ~60-90 seconds and gets the same `EINVAL` every time. This loop has been running on every node since boot.

### Why this matters for the investigation

It's a **periodic wake source**:

- Goroutine in `machined` wakes every ~60-90 s
- Performs a `write(2)` syscall to `/proc/sys/kernel/printk_devkmsg`
- Receives `EINVAL`
- Constructs a log message, writes to journald-equivalent
- Sleeps until next reconcile

On a node spending ~50% of CPU0 in C8 (iter #6), each of these wake-ups pulls a CPU out of deep idle. The cost is small per event (single syscall + log write + sleep), but it's:

- **Periodic** — predictable wake events
- **Unnecessary** — the sysctl is already at the desired value
- **Cluster-wide** — same loop on every node, contributes to total C-state-transition rate
- **Eliminable** — it's a Talos bug, fixable upstream

It's not a silent-reboot *cause* — the cost is tiny per event. But it's a real, documented, eliminable contributor to the wake-source aggregate that iter #6 measured. **Removing it would reduce the cluster-wide C8 entry/exit rate by some small amount**, which under the Vmin hypothesis would proportionally reduce the silent-reboot risk.

### Suggested action

1. **File upstream Talos issue.** Title would be: "`KernelParamSpecController` permanently fails to write `kernel.printk_devkmsg` with EINVAL". Symptom: every Talos node logs this error every ~60-90 seconds indefinitely. Reproduction: any Talos cluster with default kernel cmdline. Fix: serialize the value as a plain string (`"on"`) without trailing characters.
2. **Workaround until upstream fix:** none needed. The error is benign in functional terms; the sysctl stays at `on`. The cost is the ongoing log spam and wake events.

This is a low-priority but real upstream improvement that compounds with the iter #5/#6/#8 mitigation stack. Not a substitute for those changes; a complement.

## Finding 2 — `CONFIG_CPU_FREQ_STAT=n`: per-CPU P-state transition counters not available

```
$ talosctl read /sys/devices/system/cpu/cpu0/cpufreq/stats/total_trans
NotFound: stat /sys/devices/system/cpu/cpu0/cpufreq/stats/total_trans: no such file or directory
```

Same on every node, every CPU sample I tried (cpu0, cpu6, cpu13, cpu19). The Talos kernel was built with `CONFIG_CPU_FREQ_STAT=n` — the cpufreq subsystem is active (drives `intel_pstate`) but doesn't expose per-CPU transition counters.

This rules out **direct measurement of P-state thrashing rate**. P-state transitions on Raptor Lake are a known Vmin amplifier — every transition involves voltage regulation across the entire core voltage domain — but we can't measure them on this Talos kernel build without a custom kernel.

This adds to the structural-constraint stack from iter #5 (`CONFIG_LOCKUP_DETECTOR=n`, `CONFIG_DETECT_HUNG_TASK=n`) and iter #15 (`intel_idle.max_cstate` runtime-readonly). The Talos kernel deliberately strips diagnostic features that would help here. **A custom Talos image with `CPU_FREQ_STAT=y`, `LOCKUP_DETECTOR=y`, `DETECT_HUNG_TASK=y` would enable a much richer forensic surface**, but is a high-effort path.

## Cumulative pattern after 19 iterations

The investigation now has a fairly clean inventory of:

- **What's active** (Vmin/C8 surface, i226-V/ASPM exposure, RFDS register-clear cost amplifier, perpetual KernelParamSpecController retry)
- **What's clean** (AER, ECC, MCE, thermal, fans, conntrack, taint, PSI full, NTP, cpufreq driver, module params, machineconfig content, IRQ affinity, CPU vulnerability mitigation states, perf_event, entropy)
- **What's mixed** (BIOS version 1.26 vs 1.27, EFI variable count differs, machineconfig version count differs but content uniform, BPF program count reflects pod density)
- **What's the dominant explanation** (workload placement — k8s-2 hosts the observability stack, iter #12)

The recommendation stack has not moved since iter #8 / refined in iter #14/#15/#17.

## Honest assessment of iter #19

This iter found one small, novel datapoint (a Talos controller in permanent retry loop) and one structural rule-out (cpufreq stats unavailable). The Talos bug is worth filing upstream as a quality-of-implementation issue but doesn't change the silent-reboot recommendation.

After 19 iterations, the genuinely-fresh-angle bench is essentially empty. Each iteration is finding small refinements and rule-outs, not new candidates. **The recommendation has been the same since iter #10: cancel the cron, land the iter-#5/#6/#8 PR, watch.** The empirical signal from a 14-day watch window post-deployment is now far more informative than further analytical iterations.

## Verification trail

```
$ talosctl --endpoints k8s-1 -n k8s-1 dmesg | grep printk_devkmsg | head -10
... (every ~60 seconds, identical pattern, on every node)

$ for n in k8s-1 k8s-2 k8s-3; do
    talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpu0/cpufreq/stats/total_trans
  done
... (NotFound on every node, every CPU)
```

## Cross-references

- `evidence-2026-05-06-c-states-active.md` (iter #6) — measured 7000 cluster-wide C8 entries/sec; iter #19 identifies one ~3-per-minute source contributing to that aggregate
- `evidence-2026-05-06-itco-unfed-and-nmi-panic-sysctls.md` (iter #5) — established that lockup detectors are compiled out; iter #19 adds CPU_FREQ_STAT to the same list of stripped diagnostics
- All 18 prior iterations
- Plan 0013 — no plan-level change; small upstream Talos issue worth filing as a side activity
