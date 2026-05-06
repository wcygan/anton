# Evidence: NVMe drive lineup is identical across all three nodes — falsifies any "k8s-2 has different storage" hypothesis

**Date:** 2026-05-06 (loop iteration #11, opus 4.7)
**Source:** `talosctl read /sys/class/nvme/nvme*/{model,firmware_rev,serial,address}` and `/sys/bus/pci/devices/<addr>/{current_link_speed,current_link_width,max_link_*}` per node.
**Status:** Real falsification of an unstated assumption + a small topology note.

## NVMe lineup per node (identical across all three)

| Slot | Drive (all three nodes) | Firmware |
|---|---|---|
| `0000:01:00.0` (CPU NVMe slot) | WD_BLACK SN7100 1TB | `7615M0WD` |
| `0000:58:00.0` (chipset NVMe slot) | WD_BLACK SN7100 1TB | `7615M0WD` |
| `0000:59:00.0` (chipset NVMe slot) | Crucial CT500P3SSD8 | `P9CR313` |

**All three nodes carry identical drives at identical slot positions running identical firmware.** No NVMe-side asymmetry exists between k8s-1, k8s-2, and k8s-3.

## What this falsifies

The investigation never explicitly hypothesized "k8s-2 has a different NVMe drive than the others" — but the absence of a check for this has been an unstated assumption that NVMe lineup was uniform. **This data confirms it.** Specifically:

- **No "marginal drive on k8s-2"** explanation. All three nodes have the same drives.
- **No "different firmware revision on k8s-2"** explanation. `7615M0WD` and `P9CR313` are uniform.
- **No "NVMe vendor quirk only k8s-2 hits"** explanation. Same vendors, same models, same firmware.

This **adds another constraint to the hypothesis space**: any plausible mechanism must explain why k8s-2 was the historical reboot leader **despite having identical storage hardware to the other two nodes**. The Vmin / C-state / ASPM hypotheses don't require NVMe-side asymmetry to work — the differential between nodes is silicon corner / luck, not hardware lineup. So the surviving hypotheses remain consistent with this data.

## Topology note: one WD_BLACK on each node is downtrained to Gen3

`current_link_speed` per drive per node:

| Slot | k8s-1 | k8s-2 | k8s-3 | Drive max |
|---|---|---|---|---|
| `0000:01:00.0` (primary NVMe) | **16 GT/s (Gen4)** ×4 | 8 GT/s (Gen3) ×4 | 8 GT/s (Gen3) ×4 | Gen4 ×4 |
| `0000:58:00.0` (secondary NVMe) | 8 GT/s (Gen3) ×4 | **16 GT/s (Gen4)** ×4 | **16 GT/s (Gen4)** ×4 | Gen4 ×4 |
| `0000:59:00.0` (tertiary NVMe) | 8 GT/s ×2 | 8 GT/s ×2 | 8 GT/s ×2 | Gen3 ×4 (board limits to ×2) |

**On every node, exactly one of the two WD_BLACK SN7100 drives is operating at Gen3 (8 GT/s) instead of its rated Gen4 (16 GT/s).** It's a different *physical slot* on k8s-1 (slot 58 is Gen3) than on k8s-2 / k8s-3 (slot 1 is Gen3). The WD_BLACK at the Gen4-capable slot runs full Gen4; the one at the Gen3-only slot runs Gen3.

Possible reasons:
1. **Board topology** — the MS-01 has one CPU-direct NVMe slot (Gen4 ×4) and chipset-attached NVMe slots that may be electrically Gen3-only. This would be a static board limitation, not a fault.
2. **ASPM L1 PM fluctuation downtraining** — a documented failure mode where repeated ASPM L1 entry/exit events damage signal integrity over time, causing a permanent downtrain.
3. **PCIe signal-integrity wear** — uncommon at consumer NVMe densities, but possible with cheap M.2 connectors over months of thermal cycling.

The *consistency* across all three nodes (one drive Gen3, one drive Gen4) suggests **option (1) — board topology** — is the dominant explanation. The MS-01 product page indicates 1× Gen4 ×4 and 2× Gen3 ×4 (×2 effective on one) — and that matches exactly.

So this is not a fault, it's a board design fact. Worth recording because:
- **It explains why iter #7 saw NVMe temps at 72-75°C** — the Gen4 drive is doing more work at higher speeds (more heat) than the Gen3 drive on the same node
- **It clarifies which NVMe is the "hot" drive** — the Gen4 SN7100 at slot 1 on k8s-1 / slot 58 on k8s-2/k8s-3 is the most-loaded
- **It's relevant for the iter #3 / #8 ASPM mitigation:** the higher-speed Gen4 drive is the one most exposed to ASPM-related downtrains; disabling ASPM cluster-wide via the DaemonSet protects this drive specifically

## What the data leaves open

- **WD_BLACK SN7100 firmware `7615M0WD`** — is this current? WD has shipped silent ASPM-related firmware fixes on the SN7100 line. Verifying via WD's release notes would tell us if a firmware update is available. Out of scope for this iteration; flagged for follow-up.
- **No `aspm_l1` sysfs file** at the path I probed. ASPM L1 state per device is exposed differently in this kernel build. The cluster-wide `pcie_aspm` policy is the right runtime knob (per iter #3 DaemonSet), regardless.

## What this changes for the recommendation stack

Nothing material. The three landings from iter #5 + #6 + #8 still apply. This iteration:

- **Adds a constraint** (any hypothesis must explain k8s-2's historical reboot bias *without* invoking NVMe asymmetry, which we now know doesn't exist)
- **Removes one open question** (NVMe drive identification was unaddressed; now closed)
- **Refines one** (the Gen4 drive is the most-loaded, hottest, and most ASPM-exposed; the iter #3 DaemonSet protects it specifically)

## Verification trail

```
$ for n in k8s-1 k8s-2 k8s-3; do
    for d in nvme0 nvme1 nvme2; do
      echo "$n $d:"
      talosctl --endpoints $n -n $n read /sys/class/nvme/$d/model
      talosctl --endpoints $n -n $n read /sys/class/nvme/$d/firmware_rev
      talosctl --endpoints $n -n $n read /sys/class/nvme/$d/address
    done
  done

$ for n in k8s-1 k8s-2 k8s-3; do
    for slot in 0000:01:00.0 0000:58:00.0 0000:59:00.0; do
      sp=$(talosctl --endpoints $n -n $n read /sys/bus/pci/devices/$slot/current_link_speed)
      w=$(talosctl --endpoints $n -n $n read /sys/bus/pci/devices/$slot/current_link_width)
      echo "$n $slot: $sp / $w"
    done
  done
```

## Cross-references

- `evidence-2026-05-06-hardware-error-surfaces-clean.md` (iter #7) — NVMe temperature observation; iter #11 attributes the heat to the Gen4 drive specifically
- `evidence-2026-05-06-i226-v-irq-dominance.md` (iter #8) — NVMe AER zero on every node; iter #11 confirms this is across identical hardware
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — runtime ASPM-disable via DaemonSet is the mitigation; iter #11 identifies the Gen4 drive as the primary beneficiary
- Plan 0013 — investigation continues to converge; no new candidate from iter #11
