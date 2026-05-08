---
name: apply-config does not re-flash a schematic-only change
description: Switching `talosImageURL` to a new schematic and running `task talos:apply-node MODE=auto` does NOT write the new boot entry — must use `task talos:upgrade-node` (talosctl upgrade --image)
type: feedback
---

When the only change in talconfig.yaml is the schematic ID inside `talosImageURL` (same `talosVersion`, same extensions list semantics, only kernel-cmdline / extension-set diff), `talosctl apply-config --mode=auto` returns "Applied configuration without a reboot." It does NOT re-run the installer to write a new bootloader entry, because the running machineconfig diff is hot-reloadable.

To actually flash a new schematic and reboot into the new kernel cmdline you must use `talosctl upgrade --image=<new-installer-url>:<version>` (or `task talos:upgrade-node IP=<ip>`). That runs the installer, writes the new GRUB/sd-boot UKI entry, and stages the boot change.

**Why:** verified 2026-05-06 during plan-0013 schematic switch (adding `nvme_core.default_ps_max_latency_us=0`). On all 3 nodes, `apply-config --mode=auto` succeeded silently with no reboot, and `/proc/cmdline` was unchanged. Switching to `talosctl upgrade --image` wrote the new boot entry as expected.

**Second gotcha:** `talosctl upgrade` itself only auto-reboots when the *Talos version* differs. When old and new images are both at the same `vX.Y.Z`, the installer writes the new boot files but does NOT trigger a reboot — you have to call `talosctl reboot --wait=false` explicitly to switch onto the new boot entry. Same-version schematic swap = upgrade + manual reboot, two steps.

**How to apply:** for any rolling change that flips `talosImageURL` (extensions added/removed, `extraKernelArgs` changed) but keeps `talosVersion` the same:
1. `task talos:upgrade-node IP=<ip>` (or direct talosctl upgrade) — writes new boot entry, no reboot
2. `talosctl reboot --wait=false -n <hostname>` — switches onto it
3. Verify `/proc/cmdline` and any per-driver sysfs reflects the new schematic

If the procedure document says "use apply-node MODE=auto for an installer-image change" — that's wrong, it will silently no-op the reboot and the verification step will fail. Suggest the user replace with `upgrade-node` plus explicit reboot.
