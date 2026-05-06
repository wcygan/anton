# Evidence: the 2026-04-30 web-research kernel-arg mitigations were never applied — and a runtime path exists that wasn't taken

**Date:** 2026-05-06 (loop iteration #3, opus 4.7)
**Source:** Live `/proc/cmdline` on all three nodes via `talosctl --endpoints <n> -n <n> read /proc/cmdline`; cross-read against the comment in `talos/patches/global/machine-kmsg.yaml`.
**Status:** Net-new datapoint about a known recommendation. Closes a hidden gap between the 2026-04-30 evidence note's "Immediate Remote Diagnostics" action list and the cluster's actual configuration.

## Observation

Live kernel command line on each node, 2026-05-06:

| Node | Full `/proc/cmdline` |
|---|---|
| k8s-1 | `talos.platform=metal console=tty0 init_on_alloc=1 slab_nomerge pti=on consoleblank=0 nvme_core.io_timeout=4294967295 printk.devkmsg=on selinux=1 module.sig_enforce=1 proc_mem.force_override=never` |
| k8s-2 | `BOOT_IMAGE=/A/vmlinuz talos.platform=metal …` *(rest identical to k8s-1)* |
| k8s-3 | `talos.platform=metal …` *(rest identical to k8s-1)* |

**None of the four kernel-arg mitigations recommended in `evidence-2026-04-30-web-research.md` are present on any node:**

- ❌ `intel_idle.max_cstate=1`
- ❌ `processor.max_cstate=1`
- ❌ `pcie_aspm=off`
- ❌ `nvme_core.default_ps_max_latency_us=0`

Only the Talos default `nvme_core.io_timeout=4294967295` (NVMe never times out) is set, plus the standard Talos hardening defaults (`init_on_alloc`, `slab_nomerge`, `pti=on`, `selinux=1`, `module.sig_enforce=1`).

## Why they were never applied

The repo already encountered and recorded the constraint, but in a different file's comment block — not in the investigation's evidence/plan tree. From `talos/patches/global/machine-kmsg.yaml` lines 15–19:

> Why a KmsgLogConfig document instead of .machine.install.extraKernelArgs:
> Talos v1.12 boots with `grubUseUKICmdline=true` which seals the kernel
> cmdline in the UKI; `install.extraKernelArgs` is rejected at apply time.

So the 2026-04-30 web-research note's recommendation, marked **"Immediate Remote Diagnostics (No Physical Access)"** with a YAML example using `machine.install.extraKernelArgs`, was **structurally blocked** by Talos v1.12+. The note itself doesn't acknowledge this; the constraint was discovered separately and used to motivate the kmsg sink design (`KmsgLogConfig` as the supported runtime surface) but the kernel-arg mitigations were apparently dropped on the floor.

Result: the cluster has been operating for **>2 weeks** since 2026-04-30 with the Vmin / C-state / ASPM hypotheses live and the corresponding mitigations never deployed. Both the 2026-05-04 BIOS flash on k8s-2/k8s-3 and the iter-#2 finding (bilateral i40e flap 41 s before k8s-3's reboot, fits "fails at idle" Vmin signature) increase the load this gap is bearing.

## Runtime equivalents exist that are **not** blocked

The "kernel cmdline is sealed in the UKI" constraint is real, but every one of the four mitigations has a **runtime-writable** sysfs/dev equivalent that doesn't require touching the cmdline:

| Boot-time arg | Runtime equivalent | Mechanism |
|---|---|---|
| `intel_idle.max_cstate=1` / `processor.max_cstate=1` | Hold `/dev/cpu_dma_latency` open with a write of `0` (32-bit LE) | Linux PM-QoS keeps CPUs out of C-states deeper than the requested latency; `0` µs forces C0/C1 only. Used by `latencytop`, `tuned`'s `latency-performance` profile, etc. |
| `pcie_aspm=off` | `echo performance > /sys/module/pcie_aspm/parameters/policy` | Forces ASPM `performance` policy (no L0s/L1) globally. Effective immediately. |
| `nvme_core.default_ps_max_latency_us=0` | `echo 0 > /sys/class/nvme/nvme*/power/pm_qos_latency_tolerance_us` per device | Disables NVMe APST (autonomous power state transitions) per drive. Effective immediately. |

A small privileged DaemonSet that:
1. Opens `/dev/cpu_dma_latency` with `O_WRONLY`, writes `\x00\x00\x00\x00`, sleeps forever (closing the fd releases the request, so it must stay open)
2. Writes `performance` to `/sys/module/pcie_aspm/parameters/policy`
3. Writes `0` to each `/sys/class/nvme/nvme*/power/pm_qos_latency_tolerance_us`

…would deploy all four mitigations across the cluster without rebooting, without rebuilding the UKI, and without physical access. Total effort: a single DaemonSet manifest in a new app folder under `kubernetes/apps/kube-system/`.

This is the path the 2026-04-30 web-research note should have ended on; it didn't.

## What this changes about plan 0013

Plan 0013 currently has a Phase 3 "controlled cascade-trigger reproduction test" as the highest-signal cheap discriminator. **Applying the runtime mitigations above is cheaper still and tests a different hypothesis.** Specifically:

- If a cluster-wide DaemonSet enforces C0/C1, no ASPM, no NVMe APST, and the cluster runs for ≥14 d with zero unexplained reboots, the Vmin / C-state / ASPM idle hypothesis is supported — converges to plan 0013's terminal state (a) "localized root cause + committed fix". The fix itself is the DaemonSet.
- If a reboot still happens with the DaemonSet live, the hypothesis is materially weakened and we re-cut.
- The DaemonSet is reversible (`kubectl delete ds`), so this is a low-risk experiment.

This sits adjacent to plan 0013's existing Phase 3 cascade-reproduction test rather than replacing it. The two test different things and can run concurrently.

## Side observation: k8s-2 cmdline has a `BOOT_IMAGE=/A/vmlinuz` prefix the others don't

This is a GRUB-passes-this-when-loading-vmlinuz-directly artifact. It can mean:
- k8s-2's GRUB chain is loading the kernel image directly (legacy path)
- k8s-1 / k8s-3's GRUB chain is loading a UKI (Unified Kernel Image), which doesn't add `BOOT_IMAGE`

`talosctl get securitystate` shows SecureBoot **false** on all three, MODULESIGNATUREENFORCED **true** on all three, SELinux **enabled-permissive** on all three, so it isn't a security-policy gap. But the boot path asymmetry is real and not previously recorded. It is consistent with k8s-2 having been the first node bootstrapped or having gone through a slightly different installation flow.

It is **not** a smoking-gun explanation by itself for "k8s-2 is the historical reboot leader" — under iter #2's reading (1) (Vmin glitch hits all three; k8s-2 just gets the lucky brief glitches), the boot path doesn't matter. But it should be on file in case it correlates with anything else later.

## Verification trail

```
$ for n in k8s-1 k8s-2 k8s-3; do echo "=== $n ==="; talosctl --endpoints $n -n $n read /proc/cmdline; done
=== k8s-1 ===
talos.platform=metal console=tty0 init_on_alloc=1 slab_nomerge pti=on consoleblank=0 \
  nvme_core.io_timeout=4294967295 printk.devkmsg=on selinux=1 module.sig_enforce=1 proc_mem.force_override=never
=== k8s-2 ===
BOOT_IMAGE=/A/vmlinuz talos.platform=metal console=tty0 ... (otherwise identical)
=== k8s-3 ===
talos.platform=metal console=tty0 ... (identical to k8s-1)

$ for n in k8s-1 k8s-2 k8s-3; do echo "=== $n ==="; talosctl --endpoints $n -n $n get securitystate; done
NODE    SECUREBOOT   SELINUXSTATE          MODULESIGNATUREENFORCED
k8s-1   false        enabled, permissive   true
k8s-2   false        enabled, permissive   true
k8s-3   false        enabled, permissive   true

$ grep -rE 'extraKernelArgs|kernelArgs' talos/
talos/patches/global/machine-kmsg.yaml: # Why a KmsgLogConfig document instead of .machine.install.extraKernelArgs:
talos/patches/global/machine-kmsg.yaml: # cmdline in the UKI; install.extraKernelArgs is rejected at apply time.
```

## Cross-references

- `evidence-2026-04-30-web-research.md` — proposed the four kernel-arg mitigations as remote-only actions; this evidence note shows none landed
- `evidence-2026-05-06-k8s-2-precursor-nic-flap.md` (iter #2) — bilateral i40e link flap 41 s pre-reboot fits the "fails at idle" Vmin signature; runtime C-state cap would be a direct test
- `talos/patches/global/machine-kmsg.yaml` — already records the `install.extraKernelArgs` rejection in v1.12+, but only as a side note for the kmsg sink decision
- Plan 0013 — Phase 3 already has cheap-and-software-only tests; this one belongs there as a sibling
- `evidence-2026-04-30-web-research.md` ends with: "Three actions can be taken without physical access" — the third (kernel parameter mitigations) was structurally blocked. The first (verify watchdog state) was completed. The second (configure WatchdogTimerConfig) status is not in the current evidence tree

## Suggested next action (not taken — surfacing for operator decision)

Either:

**(a) Apply the runtime mitigations.** Author a small DaemonSet under `kubernetes/apps/kube-system/idle-mitigations/` that holds `/dev/cpu_dma_latency` with `0`, sets `pcie_aspm=performance`, and disables NVMe APST. Deploy to all three nodes. Watch for ≥14 d. Cost: small manifest + Flux reconcile. Reversibility: `kubectl delete ds`.

**(b) Build a custom Talos UKI** with the kernel args baked in via `imager` and rolling-upgrade each node. Higher cost (image build + per-node reinstall), but the canonical path.

(a) is the cheaper experiment and the right next step under plan 0013's test-then-decide framing. (b) is the right durable fix if (a) shows the hypothesis is correct.
