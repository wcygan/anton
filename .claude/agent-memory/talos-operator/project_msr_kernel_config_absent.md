---
name: MSR throttle-reason collector blocked by Talos kernel config
description: 2026-05-06 MSR collector landed, but Talos 1.13.0 kernel has CONFIG_X86_MSR disabled, so /dev/cpu/*/msr cannot appear from machine.kernel.modules alone.
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
