---
name: printk_devkmsg=on triggers harmless KernelParamSpecController error loop
description: Setting kernel.printk_devkmsg=on via machine-sysctls causes recurring "invalid argument" controller-failed events even though the value is correctly applied
type: project
---

After applying `kernel.printk_devkmsg: "on"` via `talos/patches/global/machine-sysctls.yaml` on Talos v1.12.6, the kernel sysctl read-back is correct (`on`) but `runtime.KernelParamSpecController` continues to log a recurring error:

```
controller failed
error: 1 error occurred:
  * write /proc/sys/kernel/printk_devkmsg: invalid argument
```

The controller restarts itself every ~1.6s and re-fails. This generated visible log noise during the 2026-04-28 plan-0009 Phase 1 follow-up rollout (most heavily on k8s-2, which was already in some kind of reconcile churn).

**Why:** Likely because once a process has called `prctl(PR_TASK_PERF_EVENTS_*)` or once `printk_devkmsg` has been written once with a non-default value, subsequent identical writes can return EINVAL on certain kernels. The desired state is achieved (read returns `on`), but the controller re-attempts the write each reconcile and the kernel rejects it. Talos has no deduplication for already-correct sysctl values here.

**How to apply:**
- The error is COSMETIC, not functional. `read /proc/sys/kernel/printk_devkmsg` returning `on` is the source of truth.
- Do NOT escalate as an apply failure when verifying a rollout that includes `printk_devkmsg`.
- On k8s-2 specifically the error loop generates roughly 2x the normal kernel-record volume into the kmsg log sink — when comparing UDP-vs-TCP delivery rates between nodes, account for this skew.
- If/when Sidero fixes the controller to skip rewrites when current==desired, the noise will disappear; until then, treat the controller-failed events on this key as expected.
