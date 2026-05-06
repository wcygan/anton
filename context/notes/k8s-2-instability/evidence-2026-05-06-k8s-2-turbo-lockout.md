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

- nvme-power-collector daemonset.yaml has been edited to add `msr-tools` + `rdmsr -p $cpu 0x64f` decoding for `node_cpu_msr_throttle_reason{cpu, reason}`.
- Edit is **not yet committed** to git at capture time; live pods still on the pre-MSR image.
- `/dev/cpu/0/msr` is **absent** on the Talos host. The `msr` kernel module needs to be loaded via Talos `machine.kernel.modules` before the collector can read it.
- Decision: do not reboot k8s-2 until the MSR collector is reconciled AND `/dev/cpu/0/msr` is present and emitting. The reboot is the discriminator; without the MSR read on the *current* stuck state the discriminator loses half its information.

### NVMe live power state (also caught at capture, separate issue)

| Drive | Model | NPSS state | Expected post-`idle-mitigations` |
|---|---|---:|---|
| nvme0 | WD_BLACK SN7100 | PS4 | PS0 (APST disabled) |
| nvme1 | WD_BLACK SN7100 | PS3 | PS0 (APST disabled) |
| nvme2 | Crucial CT500P3SSD8 | PS0 | PS0 ✓ |

The two SN7100 drives ignore the `nvme_core.default_ps_max_latency_us=0` write and continue entering low-power states. This is independent of the turbo-lockout question but worth recording in the same pre-state because the SN7100 silent-reboot risk path (iter #20/#28) is not closed by the current mitigation.

## Procedure (to be executed)

1. Confirm MSR collector is reconciled and emitting `node_cpu_msr_throttle_reason` on k8s-2. Record the bitfield from at least one stuck-state sample.
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

- [ ] **Outcome A — sticky software/firmware lockout cleared by reboot.** Max core freq returns to ≥4.5 GHz on k8s-2, MSR `0x64F` shows zero bits set. The pre-reboot bitfield names the original mechanism. Mitigation work in plan 0013 Phase 3 / plan 0015 Phase 3 follows the named mechanism.
- [ ] **Outcome B — hardware-side, lockout persists across reboot.** Max core freq stays ≤3 GHz on k8s-2 even after fresh boot, while k8s-1/k8s-3 hit ≥4.5 GHz. Escalates to plan 0015 Phase 1 BIOS profile + physical inspection at next visit. The mechanism is below the OS layer (VRM, EC, sensor).
- [ ] **Outcome C — partial.** Recovery to 3-4.5 GHz, neither cleanly A nor B. Treat as B for risk posture; record mechanism if MSR identified one.

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
  - MSR collector commit (TBD when committed)
