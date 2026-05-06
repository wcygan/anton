---
name: MSR throttle-reason collector blocked by Talos kernel config
description: 2026-05-06 stock Talos kernel ships CONFIG_X86_MSR=n by intent (declined upstream as security violation, extensions#620). Image Factory has no kernel-CONFIG knob. Resolution chosen: stay on stock; reframe plan 0013 reboot-discriminator off MSR onto RAPL/coretemp/cpufreq/throttle-counts ensemble.
type: project
---

2026-05-06. Plan 0013 follow-up added MSR throttle-reason collection to
`nvme-power-collector` at commit `14640fb5`.

**What landed:**
- `nvme-power-collector` installs `nvme-cli` and Alpine `edge/testing`
  `msr-tools`, then tries `rdmsr -p $cpu 0x64f` per online CPU.
- It emits `node_cpu_msr_throttle_reason{cpu,reason}` for bits:
  `PROCHOT`, `thermal`, `PL1`, `PL2`, `max-turbo`, `core-power`.
- `talos/patches/global/machine-kernel.yaml` declares `machine.kernel.modules:
  [{name: msr}]`.

**Apply result:**
- Flux reconciled commit `14640fb5`; DaemonSet rolled 3/3 Ready.
- Local workstation could not reach Talos API on `192.168.1.x:50000`, but the
  API was reachable from inside the cluster. Used temporary in-cluster
  `ghcr.io/siderolabs/talosctl:v1.13.0` pods with a Secret containing
  `talos/clusterconfig/talosconfig` and generated node configs.
- Dry-run on all three nodes showed a no-reboot diff adding `- name: msr`.
- `apply-config --mode=auto` on k8s-1, k8s-2, k8s-3 returned
  `Applied configuration without a reboot`.
- Live machineconfig on k8s-2 contains both `vxlan` and `msr`.
- `KernelModuleSpec/runtime/msr` exists with phase `running`.

**Blocking finding:**
- `/dev/cpu/0/msr` remained absent on all three nodes after apply.
- `/sys/module/msr` is absent.
- `LoadedKernelModules` contains `intel_rapl_msr` but not `msr`.
- `/lib/modules/6.18.24-talos/modules.dep` contains `intel_rapl_msr.ko` only;
  no `kernel/arch/x86/kernel/msr.ko`.
- `/lib/modules/6.18.24-talos/modules.builtin` does not contain `msr`.
- `/proc/config.gz` on k8s-2 says `# CONFIG_X86_MSR is not set` while
  `CONFIG_X86_CPUID=y`.

**Conclusion:**
This is not a reconcile or module-load ordering issue. The Talos kernel used by
anton currently lacks the x86 MSR device driver entirely. Rebooting with the
same image should not make `/dev/cpu/*/msr` appear. The next viable path is a
Talos image/kernel path that enables `CONFIG_X86_MSR` (built-in or module), then
the existing collector should begin emitting.

**Cleanup:**
Temporary `talos-apply-msr` Secret and `talos-*` apply/check pods were deleted
after verification.

**Resolution (2026-05-06):**
Stock Talos kernel posture is intentional and upstream has declined to change it:

- `siderolabs/pkgs` `kernel/build/config-amd64` line 458 — `# CONFIG_X86_MSR is not set` on `main` and `release-1.13`. Note the next line is `CONFIG_X86_CPUID=y`, so the choice is selective, not blanket-off.
- `siderolabs/talos#10408` (closed 2025-02-23) and `siderolabs/extensions#620` (closed 2025-02-25, the substantive thread): Andrey Smirnov / smira: *"I think enabling access to MSR is a security violation, and it shouldn't be done. I believe there are other ways to read c-states and processor information in modern Linux (via sysfs)."* Pointed reporters at `intel_pstate` / `amd_pstate` / `pmc_core`. No PR or active issue tracking re-engagement.
- Talos Image Factory schematic schema (`siderolabs/image-factory` `pkg/schematic/schematic.go`) has no kernel-CONFIG field — only `extraKernelArgs`, `meta`, `systemExtensions`, `bootloader`, `secureboot`. Confirmed at `docs/api.md`.
- Out-of-tree `msr.ko` + Talos system extension is not viable: Talos enforces module signing and the build's signing key is discarded (`filter-hardened-check.py` IGNORE_VIOLATIONS comment on `CONFIG_MODULES`), so unsigned out-of-tree modules cannot load. System extensions are precompiled Sidero-signed artifacts; no user-extension surface. The path collapses to forking `siderolabs/pkgs` and rebuilding the kernel.

**Path chosen:** stay on stock Talos. Plan 0013 Phase 3 reboot-discriminator reframed off MSR onto the existing telemetry ensemble (`node_cpu_scaling_frequency_hertz`, `node_rapl_package_joules_total`, `node_hwmon_temp_celsius`, `node_cpu_package_throttles_total`). The binary A/B/C decision works without MSR; mechanism naming inside Outcome A uses the ensemble (RAPL/temp/freq trajectory) instead of `MSR_CORE_PERF_LIMIT_REASONS` bits. Custom-kernel posture rejected on cost/risk: 3-node rolling installer change during active investigation, breaks Renovate `ghcr.io/siderolabs/installer` digest automation, injects a new variable into plan 0013, and every Talos point release thereafter requires a kernel rebuild.

**Collector posture:** `nvme-power-collector` MSR loop and `machine.kernel.modules: [{name: msr}]` are left in place. They cost nothing on stock Talos (the loop logs the missing-MSR warning once per pod start and skips MSR emission; the KernelModuleSpec is a no-op resource), and would Just Work if upstream ever flipped the symbol on. No removal needed.

**Upstream re-engagement (deferred, optional):** PR `siderolabs/pkgs#1409` (merged 2025-12-16) "feat: enable Powercap and Intel RAPL" shows the maintainers accept similar side-channel-class symbols as opt-in modules when the case is well-made (RAPL was the basis for PLATYPUS / CVE-2020-8694). A re-pitch of `CONFIG_X86_MSR=m` (module, not built-in) framed around the 2026-05-06 reproducible turbo-lockout is more credible than `siderolabs/talos#10408`'s framing was, but not blocking — defer until plan 0013 closes.

**Tangent:** `siderolabs/talos#12968` (open, 2026-03-15) "Unexpected software-triggered node reboot. Reason `[0x00080800]`" — silent software 0xCF9 reset, no kernel-side trace, storage-correlated, on Talos 1.12.5 with LINSTOR/DRBD. Different storage stack from anton (Longhorn/Multus), but the *fingerprint* family is uncomfortably close to anton's silent-reboot signature. Watch as part of plan 0013 Phase 4 next-event capture.
