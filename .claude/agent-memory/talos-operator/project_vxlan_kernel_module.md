---
name: vxlan module builtin on Talos v1.12.6
description: On Talos v1.12.6 (kernel 6.18.18-talos), vxlan is compiled into the kernel as a builtin — not a loadable .ko — so it never appears in /proc/modules. Presence evidence is /sys/module/vxlan or modules.builtin, not /proc/modules.
type: project
---

2026-04-19. Plan 0004 phase 4c prep: added `machine.kernel.modules: [{name: vxlan}]` via a new global patch `talos/patches/global/machine-kernel.yaml`, rolled no-reboot to all 3 nodes (commit 7f1433e9 on main).

**Key finding — the premise was wrong:** On Talos v1.12.6 (kernel 6.18.18-talos), `vxlan` is a **builtin** kernel feature, not a loadable module. Evidence:
- `talosctl read /lib/modules/6.18.18-talos/modules.builtin | grep vxlan` → `kernel/drivers/net/vxlan/vxlan.ko` (present)
- `talosctl list /sys/module | grep vxlan` → present (with `/sys/module/vxlan/version` = `0.1`)
- `talosctl read /proc/modules | grep vxlan` → empty (builtins don't appear in /proc/modules — only dynamically loaded modules do)

So the task's verification criterion "`/proc/modules | grep vxlan` non-empty" can never be satisfied on v1.12.6 — the correct test is `/sys/module/vxlan`.

The config change is still correct hygiene (declares intent; future-proofs if Talos ever builds vxlan as a .ko). After apply, Talos creates a `KernelModuleSpec` COSI resource and `runtime.KernelModuleSpecController` calls `kmod.Load("vxlan")` — on a builtin this is a silent no-op.

**Implication for storage-vxlan DaemonSet crash-loop (plan 0004 phase 4c):** The `RTNETLINK answers: Not supported` error from the DS is **NOT** a missing-module problem. Triage must look elsewhere: container capabilities (`NET_ADMIN`, `NET_RAW`), netns config, kernel feature flags, whether the `ip link add type vxlan` flags it uses are supported, SELinux (`module.sig_enforce=1` in cmdline — but that's module signing, not runtime capability), etc.

**Rollout details:**
- No reboot on any node (module config + builtin = hot-applicable no-op).
- Etcd stayed 3/3 OK throughout; all 3 nodes stayed Ready.
- Dry-run on k8s-1 showed clean 3-line diff under `machine.features.hostDNS` — no side effects.

**Talhelper trap check (Phase 4b class bug):** talhelper 3.1.7 handled `machine.kernel.modules` correctly — emitted verbatim under `machine:` in rendered `kubernetes-k8s-*.yaml`. No silent drop. Earlier false-positive was caused by ripgrep respecting `.gitignore` (clusterconfig dir is gitignored) — always use `grep -n` directly when verifying rendered output.
