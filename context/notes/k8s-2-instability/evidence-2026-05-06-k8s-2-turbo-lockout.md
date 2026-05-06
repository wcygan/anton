# 2026-05-06 k8s-2 turbo lockout — pre/post evidence

## Summary

Following the 2026-05-06 02:30-04:30 CDT k8s-2 throttle episode (18,041 package-throttle events, freq cliff to 0.47 GHz at 52 °C with peer-identical PL1), k8s-2 entered a sustained sub-turbo state: the package would not burst above ~2.76 GHz max core frequency for hours after the throttle counter rate returned to zero. This note captures the pre-state for a discriminating reboot test under plan 0013 Phase 3, and is intended to be filled in with the post-state after the reboot.

The reboot test answers a single binary question:

- **If max core frequency returns to ~5 GHz post-reboot** → the lockout was a sticky software/firmware state (PROCHOT latch, ME turbo-disable, PL1 hysteresis, thermal cooldown counter) that a fresh boot clears. The MSR `0x64F` bit identified by the in-flight throttle-reason collector names the specific mechanism.
- **If max core frequency stays ≤ ~3 GHz post-reboot** → hardware-side (VRM in degraded mode, stuck thermal sensor, EC asserting BD_PROCHOT for board-protection reasons, PSU brick voltage sag). Escalates to physical inspection; plan 0015 Phase 1 BIOS profile becomes near-term.

## Pre-state (captured 2026-05-06 ~09:45 CDT, before any reboot)

### Identity and uptime

| Field | k8s-2 |
|---|---:|
| LAN IP | `192.168.1.99` |
| Tailnet hostname | `k8s-2` |
| BIOS version | `1.27` (`04/03/2025`) |
| Boot time (`node_boot_time_seconds`) | `1777859227` (2026-05-03 15:47 CDT) |
| Uptime at capture | 61.2 hours (~2.55 days) |
| Cumulative `node_cpu_package_throttles_total` | 18,041 |

### CPU state at capture

| Metric | k8s-1 (control) | **k8s-2** | k8s-3 (control) |
|---|---:|---:|---:|
| `avg(node_cpu_scaling_frequency_hertz)` | 2.91 GHz | **2.47 GHz** | 2.89 GHz |
| `max(node_cpu_scaling_frequency_hertz)` | (not captured) | **3.78 GHz** | (not captured) |
| Cores at >2.5 GHz | 12 of 20 | **9 of 20** | 12 of 20 |
| Cores at <1 GHz | 0 | **2 of 20** | 0 |
| `rate(node_rapl_package_joules_total[2m])` | 29.7 W | **16.0 W** | 22.3 W |
| `node_hwmon_temp_celsius` (coretemp_0 temp1) | 69 °C | **55 °C** | 68 °C |
| Throttle rate over last 30 min | 0/s | 0/s | 0/s |

Recovery is in progress at capture time — earlier in this session (~07:00 CDT) max freq was 2.76 GHz with only 1 of 20 cores above 2.5 GHz. By 09:45 CDT max freq has climbed to 3.78 GHz with 9 cores at >2.5 GHz. The lockout is dissolving, but the package still cannot reach the i9-13900H/12900H expected ~5 GHz turbo ceiling on a single core.

### `idle-mitigations` PM-QoS configuration (asymmetric per `f7b8cafc`)

| Node | `/dev/cpu_dma_latency` value | Allowed C-states |
|---|---:|---|
| k8s-1 | 0 µs | C0 only (active) |
| **k8s-2** | **1 µs** | C0 + C1_ACPI / MWAIT 0x0 |
| k8s-3 | 0 µs | C0 only (active) |

The 1 µs relaxation on k8s-2 explains *some* of the asymmetric package power (16 W vs ~25-30 W) — k8s-2's cores can park in C1 when idle, while k8s-1/k8s-3 are stuck active in C0. It does **not** explain the 3.78 GHz max-core-freq cap. C1 idle parking does not constrain turbo on a busy core.

### MSR `0x64F` (throttle reason bitfield) — collector status at capture

- `nvme-power-collector` was extended at commit `14640fb5` to install `msr-tools` and emit `node_cpu_msr_throttle_reason{cpu, reason}` from `rdmsr -p $cpu 0x64f`. The MSR loop runs only when `/dev/cpu/0/msr` exists, otherwise it logs the missing-MSR warning once per pod start.
- Talos kernel module `msr` was added to `machine.kernel.modules` at commit `459628a9` and applied no-reboot to all three nodes; the COSI `KernelModuleSpec/runtime/msr` resource is `running`.
- `/dev/cpu/*/msr` is **still absent** post-apply. Investigation 2026-05-06: stock Talos kernel ships `# CONFIG_X86_MSR is not set` (verified in `siderolabs/pkgs` `kernel/build/config-amd64` line 458 on `main` and `release-1.13`); the `msr.ko` module is not built, so declaring it in `machine.kernel.modules` is a no-op.
- Upstream resolution: `siderolabs/talos#10408` and `siderolabs/extensions#620` (closed 2025-02-25) declined the request as a security violation, pointing at `intel_pstate` / `pmc_core` sysfs alternatives. Talos Image Factory has no kernel-CONFIG knob (schematic schema is `extraKernelArgs` + `meta` + `systemExtensions` + `bootloader` + `secureboot`). The only escape is forking `siderolabs/pkgs`, declined here while plan 0013 is in flight.
- **Decision (revised):** the reboot test proceeds on the telemetry ensemble — `node_cpu_scaling_frequency_hertz` (max + per-core), `node_rapl_package_joules_total` (RAPL package watts), `node_hwmon_temp_celsius` (coretemp), `node_cpu_package_throttles_total` (sysfs cumulative). MSR `0x64F` is **best-effort** — left deployed, will emit if/when CONFIG_X86_MSR ever flips upstream, currently silent.

### NVMe live power state (also caught at capture, separate issue)

| Drive | Model | NPSS state | Expected post-`idle-mitigations` |
|---|---|---:|---|
| nvme0 | WD_BLACK SN7100 | PS4 | PS0 (APST disabled) |
| nvme1 | WD_BLACK SN7100 | PS3 | PS0 (APST disabled) |
| nvme2 | Crucial CT500P3SSD8 | PS0 | PS0 ✓ |

The two SN7100 drives ignore the `nvme_core.default_ps_max_latency_us=0` write and continue entering low-power states. This is independent of the turbo-lockout question but worth recording in the same pre-state because the SN7100 silent-reboot risk path (iter #20/#28) is not closed by the current mitigation.

### Fan1 intermittent failure (the leading hypothesis after 2026-05-06 ~14:00 CDT)

This is the finding that reframes the test. Fan1 on k8s-2 (`node_hwmon_fan_rpm{instance="192.168.1.99:9100",chip="platform_nct6775_2592",sensor="fan1"}`) is **intermittently dropping to 0 RPM** — 16 of 145 samples (≈11 %) over the last 12 h. Fan1 on k8s-1 and k8s-3 over the same window: **0 of 145** zero-readings each. Fan2 on k8s-2 is healthy (0 zeros over 12 h, 2106-2854 RPM).

Onset: clean 2400-2700 RPM continuous through 17:45 CDT 2026-05-05 → 02:35 CDT 2026-05-06. First zero observed at **02:55 CDT 2026-05-06** — *within the package-throttle window* (02:34 first throttle increment, peak at 03:34). The fan dropouts and the throttle events are co-temporal.

Sample trajectory excerpt:

```
02:35 CDT  2738 RPM
02:45 CDT  2678 RPM
02:55 CDT     0 RPM  ← first zero, throttle counter starts
03:05 CDT  2766 RPM
03:15-03:35  0 0 0     ← three consecutive zeros
03:45 CDT  2347 RPM
03:55 CDT  2523 RPM
04:05-04:15  0 0       ← two consecutive zeros
…
```

Currently (capture time): fan1 = 1928 RPM, fan2 = 2250 RPM on k8s-2 vs fan1 = 2415 / 2789 RPM and fan2 = 2606 / 2727 RPM on k8s-1 / k8s-3. Even when fan1 *is* spinning on k8s-2 it's running ~20 % slower than the same fan on the peer nodes — consistent with bearing wear or partial obstruction.

Downstream evidence — NVMe sensor 2 (composite) right now:

| | nvme0 | nvme1 | nvme2 |
|---|---:|---:|---:|
| k8s-1 | 73 °C | 61 °C | 46 °C |
| **k8s-2** | **77 °C** | **87 °C** | 56 °C |
| k8s-3 | 61 °C | 73 °C | 47 °C |

k8s-2's nvme1 is 14-26 °C hotter than the same M.2 slot on either peer. Same hardware, same workload, same chassis design — the only differential is airflow.

**Hypothesis (revised after the fan finding):** the recurring k8s-2 throttle events are **firmware-side thermal protection** triggered by fan1 stalls. When fan1 stalls, airflow over the VRM and the M.2 slots collapses; the EC's VRM thermal sensor (separate from the CPU coretemp the kernel sees) crosses its threshold; the EC asserts BD_PROCHOT; the CPU drops to base or below-base frequency *while CPU coretemp reads room temp because the heatsink is bonded directly to the package and is well-served by even a stalled fan*. When fan1 spins back up, throttle eases but firmware thermal hysteresis keeps freq capped for minutes-to-hours. Repeats across the 02:30-04:30 CDT window producing the 18,041 throttle events. Fits the "silent reboot, no kernel trace" pattern the parent plan is investigating: a hard fan stall under heavier sustained load could cross the EC's *protection-reset* threshold rather than just PROCHOT, and the resulting reset would be firmware-initiated with zero kernel logging — exactly the signature plan 0013 has been chasing.

**Implication for this test:** the reboot discriminator is no longer the highest-signal action. A reboot does not fix a flaky fan bearing; the next fan stall reproduces the throttle. **Outcome B is now the leading prior before the test runs.** The reboot is still worth running for two narrow reasons: (1) confirms the ensemble's pre-vs-post-reboot freq trajectory matches Outcome B, strengthening the fan-as-cause story; (2) gives a clean uptime baseline against which a fan replacement's effectiveness can be measured. But the **actionable conclusion is physical inspection / fan replacement on k8s-2**, not OS-level remediation.

## Procedure (to be executed)

1. Confirm the telemetry ensemble has captured at least one full stuck-state window on k8s-2: `node_cpu_scaling_frequency_hertz` (max + per-core distribution), `node_rapl_package_joules_total` (rate over the window), `node_hwmon_temp_celsius` (coretemp_0 temp1 trajectory), `node_cpu_package_throttles_total` (cumulative count + delta). Record values on k8s-1 and k8s-3 over the same window as negative controls. (MSR `0x64F` collector is best-effort — record any non-zero `node_cpu_msr_throttle_reason{cpu,reason}` as a bonus, but do not block on emission; collector cannot work on stock Talos kernel — see status block above.)
2. Drain k8s-2: `kubectl drain k8s-2 --ignore-daemonsets --delete-emptydir-data --timeout=10m`. Watch etcd quorum stays at 3/3 throughout (k8s-2 is a control-plane node — drain does not remove the etcd member, only evicts workload pods).
3. Graceful reboot: `talosctl reboot --nodes k8s-2 --mode=default`. Mode `default` allows graceful etcd member rejoin; do not use `staged` or `powercycle`.
4. Wait for `kubectl get node k8s-2` → `Ready` and Flux to settle. Record new `node_boot_time_seconds`.
5. `kubectl uncordon k8s-2`.
6. Capture post-state immediately (within 5-10 minutes of Ready) and again after a 30-minute settle.

## Post-state (to be filled in)

### Identity post-reboot

| Field | Value |
|---|---:|
| New `node_boot_time_seconds` | _TBD_ |
| New cumulative `node_cpu_package_throttles_total` | _TBD_ (expect to start at 0 after fresh boot) |

### CPU state at +5-10 min post-Ready

| Metric | k8s-1 (control) | k8s-2 (post) | k8s-3 (control) |
|---|---:|---:|---:|
| `avg(node_cpu_scaling_frequency_hertz)` | _TBD_ | _TBD_ | _TBD_ |
| `max(node_cpu_scaling_frequency_hertz)` | _TBD_ | _TBD_ | _TBD_ |
| Cores at >2.5 GHz | _TBD_ | _TBD_ | _TBD_ |
| `rate(node_rapl_package_joules_total[2m])` | _TBD_ | _TBD_ | _TBD_ |
| `node_hwmon_temp_celsius` (coretemp_0 temp1) | _TBD_ | _TBD_ | _TBD_ |
| MSR `0x64F` bits set on any core | _TBD_ | _TBD_ | _TBD_ |

### CPU state at +30 min post-Ready

(same table)

## Decision

- [ ] **Outcome A — sticky software/firmware lockout cleared by reboot.** Max core freq on k8s-2 returns to ≥4.5 GHz post-reboot. Naming the mechanism (PROCHOT vs thermal vs PL1 vs PL2 vs max-turbo vs core-power) requires the telemetry ensemble across the pre-reboot stuck window: a RAPL Watt step *without* a corresponding coretemp rise points at a power-budget mechanism (PL1/PL2); a coretemp rise that crests TCC pre-throttle points at thermal; a freq cap that holds while neither watts nor temp budge points at PROCHOT or a turbo-ratio cap; an MSR `0x64F` non-zero bit (if captured — unlikely on stock Talos) confirms in one read. Mitigation work in plan 0013 Phase 3 / plan 0015 Phase 3 follows whatever mechanism the ensemble identifies; if ambiguous, take the BIOS-profile branch.
- [ ] **Outcome B — hardware-side, lockout persists across reboot.** Max core freq stays ≤3 GHz on k8s-2 even after fresh boot, while k8s-1/k8s-3 hit ≥4.5 GHz. Escalates to plan 0015 Phase 1 BIOS profile + physical inspection at next visit. The mechanism is below the OS layer (VRM, EC, sensor) — MSR would not have been informative anyway.
- [ ] **Outcome C — partial.** Recovery to 3-4.5 GHz, neither cleanly A nor B. Treat as B for risk posture; record any ensemble signal that points at a specific mechanism.

## References

- Plan: `context/plans/0013-cluster-wide-silent-reboot-localization.md` — Phase 3 task line for this test
- Related plan: `context/plans/0015-ms-01-firmware-power-stability-profile.md` — Phase 1 BIOS profile, becomes near-term on Outcome B
- Prior 2026-05-06 entries:
  - `context/incidents/2026-05-06-k8s-2-thermal-throttle.md`
  - `context/postmortems/2026-05-06-k8s-2-thermal-throttle.md`
  - `evidence-2026-05-06-ms-01-bios-amt-baseline.md` (this directory)
- Relevant commits:
  - `de801143` — initial idle-mitigations DaemonSet
  - `f7b8cafc` — k8s-2 PM-QoS relaxation 0us → 1us (asymmetric)
  - `5ae7595d` — plan 0013 log entry capturing this incident
  - `14640fb5` — MSR throttle-reason collector added to nvme-power-collector
  - `459628a9` — `msr` declared in `machine.kernel.modules` (no-op on stock kernel; recorded in talos-operator memory)
- Upstream MSR posture (2026-05-06 investigation): stock Talos kernel ships `# CONFIG_X86_MSR is not set` intentionally; the request was filed and declined as a security violation in [`siderolabs/extensions#620`](https://github.com/siderolabs/extensions/issues/620) (closed 2025-02-25, smira pointed at sysfs alternatives) with sister issue [`siderolabs/talos#10408`](https://github.com/siderolabs/talos/issues/10408). Image Factory schematic schema does not accept kernel-CONFIG overrides ([`pkg/schematic/schematic.go`](https://github.com/siderolabs/image-factory/blob/main/pkg/schematic/schematic.go)). Custom-kernel posture rejected in this investigation; details in `.claude/agent-memory/talos-operator/project_msr_kernel_config_absent.md`.
