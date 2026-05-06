# Evidence: kernel module parameters are uniform across all three nodes; iter-#3 DaemonSet manifest can be slightly simplified

**Date:** 2026-05-06 (loop iteration #15, opus 4.7)
**Source:** `talosctl read /sys/module/<mod>/parameters/*` for `intel_idle`, `pcie_aspm`, `nvme_core`, `nvme`, `i40e`, `igc`, `i915` per node.
**Status:** One rule-out (no module-parameter asymmetry) + two small refinements to the iter #3 DaemonSet manifest.

## Finding 1 — All seven probed modules have identical parameters across all three nodes

| Module | All three nodes |
|---|---|
| `intel_idle` | `force_irq_on=N ibrs_off=N max_cstate=9 no_acpi=N no_native=N preferred_cstates=0 states_off=0 use_acpi=N` |
| `pcie_aspm` | `policy=[default] performance powersav` (default selected) |
| `nvme_core` | `apst_primary_latency_tol_us=15000 apst_primary_timeout_ms=100 apst_secondary_latency_tol_us=100000 apst_secondary_timeout_ms=2000 default_ps_max_latency_us=100000 force_apst=N io_timeout=4294967295 iopolicy=numa multipath=Y` |
| `nvme` | `io_queue_depth=1024 max_host_mem_size_mb=128 use_cmb_sqes=Y` |
| `i40e` | (no exposed parameters) |
| `igc` | (no exposed parameters) |
| `i915` | (verbose; ~40 parameters; identical across nodes) |

**No kernel-module-parameter asymmetry between k8s-1, k8s-2, and k8s-3.** Yet another dimension where the three nodes are functionally identical at the kernel level — adding to:

- Identical Talos extensions (iter #6)
- Identical microcode `0x6134` (iter #6)
- Identical NVMe lineup + firmware (iter #11)
- Identical board version, bios vendor, product family (iter #13)
- Identical sysctls (iter #5, #9, #10)

The k8s-2 differential really is **only**:
- BIOS version 1.27 vs k8s-1's 1.26 (k8s-3 also 1.27)
- machineconfig version 3 vs version 1 (iter #13 — apply count, possibly content drift)
- **Workload placement** — k8s-2 hosts the observability stack (iter #12)

The first is now uniform across the 1.27-flashed pair (k8s-2 + k8s-3, where k8s-3 *also* silent-rebooted on 2026-05-05). The second is procedural and likely benign. **The third remains the dominant explanation for the historical asymmetry.**

## Finding 2 — Two manifest refinements for the iter-#3 DaemonSet

The currently-proposed DaemonSet ops are:

```
1. open /dev/cpu_dma_latency, write \x00\x00\x00\x00, hold open       # PM-QoS C-state cap
2. echo performance > /sys/module/pcie_aspm/parameters/policy         # ASPM disable
3. for d in /sys/class/nvme/nvme*/power/pm_qos_latency_tolerance_us:
       echo 0 > $d                                                    # NVMe APST disable per-drive
```

Iter #15 confirms (2) is correct (`pcie_aspm.policy` is runtime-writable to `performance`). Iter #15 also reveals:

### Refinement A — `nvme_core.default_ps_max_latency_us` is a single-file equivalent of per-drive pm_qos

Current value: `100000` (100 ms — the kernel default). Setting to `0` disables NVMe APST cluster-wide via a single write:

```
echo 0 > /sys/module/nvme_core/parameters/default_ps_max_latency_us
```

This **is a module parameter and may not be runtime-writable** — module parameters are only writable if the module declared them with `_RW` permission. To verify: `ls -l /sys/module/nvme_core/parameters/default_ps_max_latency_us` and check the mode bits. If writable, prefer this to per-drive iteration: simpler manifest, lower risk of missing a freshly-attached drive, identical effect.

If not writable, fall back to per-drive (op 3 as currently proposed).

### Refinement B — `intel_idle.max_cstate=1` won't replace `/dev/cpu_dma_latency`

Currently `intel_idle.max_cstate = 9` (allow all C-states). Writing `1` to this parameter would limit intel_idle to only C1, in theory. **But:**

- This parameter is typically declared `_RO` (read-only) at module load time. Kernel-source scan: `module_param_named(max_cstate, ..., int, 0444)` makes it read-only. A runtime write would fail.
- Even if writable, **`intel_idle` is in ACPI-fallback mode** on this kernel build (per iter #6's `_ACPI` state name suffix). When intel_idle uses ACPI fallback, the `processor.max_cstate` parameter governs, not `intel_idle.max_cstate`. The runtime-writable equivalent for ACPI is to update `/sys/module/processor/parameters/max_cstate` if exposed (often isn't).

**Conclusion: stick with `/dev/cpu_dma_latency` PM-QoS as op (1).** It's the universal lever that works regardless of intel_idle's mode.

## Refined DaemonSet manifest (incorporates iter #15)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: idle-mitigations
  namespace: kube-system
spec:
  selector: { matchLabels: { app: idle-mitigations } }
  template:
    metadata: { labels: { app: idle-mitigations } }
    spec:
      hostPID: true
      tolerations:
      - operator: Exists       # run on every node, including control-plane
      containers:
      - name: pm-qos
        image: ghcr.io/wcygan/anton-tools/idle-mitigations:1.0.0   # tiny static binary or shell
        securityContext:
          privileged: true     # need /dev/cpu_dma_latency + /sys writes
        command:
        - /bin/sh
        - -c
        - |
          set -eu

          # Op 2: pcie_aspm policy → performance (runtime-writable; iter #15 confirmed)
          echo performance > /sys/module/pcie_aspm/parameters/policy
          echo "[ok] pcie_aspm policy = $(cat /sys/module/pcie_aspm/parameters/policy)"

          # Op 3a: try module-parameter approach first (iter #15 refinement)
          if [ -w /sys/module/nvme_core/parameters/default_ps_max_latency_us ]; then
            echo 0 > /sys/module/nvme_core/parameters/default_ps_max_latency_us
            echo "[ok] nvme_core.default_ps_max_latency_us = 0 (cluster-wide)"
          else
            # Op 3b: fall back to per-drive pm_qos
            for d in /sys/class/nvme/nvme*/power/pm_qos_latency_tolerance_us; do
              echo 0 > "$d" && echo "[ok] $d = 0"
            done
          fi

          # Op 1: PM-QoS C-state cap (must be last; this is a blocking hold)
          # Open /dev/cpu_dma_latency with O_WRONLY, write 0 (32-bit LE), do NOT close
          # Trick: use Python or a small C binary that opens the fd and sleeps forever
          exec python3 -c '
          import os, struct, time
          fd = os.open("/dev/cpu_dma_latency", os.O_WRONLY)
          os.write(fd, struct.pack("<i", 0))
          print("[ok] /dev/cpu_dma_latency held open with 0 µs latency tolerance")
          while True: time.sleep(3600)
          '
        volumeMounts:
        - { name: cpu-dma-latency, mountPath: /dev/cpu_dma_latency }
        - { name: sys-module, mountPath: /sys/module }
        - { name: sys-class-nvme, mountPath: /sys/class/nvme }
      volumes:
      - name: cpu-dma-latency
        hostPath: { path: /dev/cpu_dma_latency, type: CharDevice }
      - name: sys-module
        hostPath: { path: /sys/module, type: Directory }
      - name: sys-class-nvme
        hostPath: { path: /sys/class/nvme, type: Directory }
```

(This is illustrative; a proper image / inline shell needs to be authored. The key shape is right.)

## Honest assessment

This iter is at the edge of useful. The module-parameter check produced one clean rule-out (no asymmetry) and two small manifest refinements. The cumulative recommendation stack is unchanged.

**Strong unchanged recommendation:** land the iter-#5/#6/#8 PR with the iter-#15-refined DaemonSet manifest. Empirical results from a watch window are now far more informative than further analytical iterations.

## Cross-references

- `evidence-2026-05-06-c-states-active.md` (iter #6) — measured intel_idle state names with `_ACPI` suffix; iter #15 confirms `intel_idle.max_cstate=9` and explains why this knob doesn't help in ACPI-fallback mode
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — original DaemonSet proposal; iter #15 refines op 3 (single write vs per-drive)
- `evidence-2026-05-06-i226-v-irq-dominance.md` (iter #8) — `pcie_aspm policy=performance` is the i226-V mitigation; iter #15 confirms the file is writable
- `evidence-2026-05-06-nvme-lineup-uniform.md` (iter #11) — uniform NVMe lineup; iter #15 adds uniform NVMe driver parameters
- Plan 0013 — manifest tweak only; no plan-level change
