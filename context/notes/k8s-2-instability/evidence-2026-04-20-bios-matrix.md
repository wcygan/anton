# 2026-04-20 — BIOS version matrix + Minisforum MS-01 BIOS changelog

Phase 1 step 4 from the synthesis action list. Verify whether MS-01 BIOS `AHWSA.1.22` (Mar 2024) is current, and whether BIOS drift is a distinguishing factor for k8s-2's instability.

## BIOS versions across the fleet

Pulled from `/sys/class/dmi/id/bios_version` and `bios_date` on each node via `talosctl read`:

| Node | Product / Serial | BIOS | Date | Uptime at capture |
|---|---|---|---|---|
| k8s-1 | Venus Series / ...00181 | **1.26** | **2024-10-14** | 94h 39m ✅ |
| **k8s-2** | Venus Series / ...00277 | **AHWSA.1.22** | **2024-03-12** | **36m ❌ (11th reboot today)** |
| k8s-3 | Venus Series / ...00077 | **AHWSA.1.22** | **2024-03-12** | 96h 50m ✅ |

Two things this matrix establishes:

1. **BIOS drift alone is not the distinguishing factor.** k8s-3 shares the exact same 1.22 BIOS as k8s-2 and has been up 96h. If 1.22 itself were the cause, k8s-3 would also be rebooting.
2. **`context/hardware.md` is stale** — it implies all three nodes are on 1.22, but k8s-1 was upgraded to 1.26 at some prior point. This is the third stale-data finding (after the tailnet IPs and the longhorn-2 status noted earlier). Deferred, not fixed in this pass.

→ **devils-advocate's hypothesis 3 (stale BIOS) is not confirmed as the root cause.** But BIOS upgrade to 1.26 is still a reasonable prophylactic for k8s-2 because it brings it in line with the already-stable k8s-1.

## Minisforum MS-01 BIOS release history (post-1.22)

Compiled from [virtualizationhowto.com](https://www.virtualizationhowto.com/2024/09/how-to-upgrade-the-minisforum-ms-01-bios/) and WebFetch of the Minisforum support page. Official Minisforum changelogs are terse; the community article has more detail.

| Version | Released | Changelog highlights |
|---|---|---|
| 1.22 | 2024-03-12 | (installed on k8s-2 and k8s-3) |
| 1.23 | 2024-04-12 | Temperature display correction (cosmetic) |
| 1.24 | 2024-07-05 | Audio codec verb table |
| 1.25 | 2024-09-19 | **PCIE ASPM, RTD3, and C-State explicitly "unsupported" in this version** — i.e. Minisforum pulled them |
| 1.26 | 2024-10-14 | **Microcode updates; C-State support restored.** **Installed on k8s-1.** |
| 1.27 | 2025-04-03 | Turbo Ratio Limit options; UEFI storage Option ROM disabled by default; PCIe slot speed control; PL1=55/60W, PL2=80W (varies by CPU); GOP 21.0.1066 |

Patterns that matter for a 13th-gen i9 HX in a 1L chassis:

- **Version 1.25 temporarily disabled C-State, ASPM, RTD3.** Those are the power-management features most commonly implicated in spontaneous reboots on Raptor Lake mobile. That Minisforum shipped a version with them OFF is direct evidence they had stability issues in 1.24 and earlier.
- **Version 1.26 contains microcode updates.** Intel shipped microcode addressing Raptor Lake "VMin Shift" / voltage-creep instability during 2024. Whether this specific BIOS bundles that patch is not explicit, but any microcode update on a 13th-gen CPU is worth absorbing.
- **Version 1.27's PL2=80W cap** reflects Minisforum's own acknowledgement that the 1L chassis cannot sustain stock Raptor Lake HX power targets. If k8s-2 is hitting sustained CPU load (Longhorn replication, Cilium envoy, kube-prometheus evaluation), a power-capped BIOS could prevent thermal trips entirely.

## Implications for the active hypotheses

| Hypothesis | Evidence shift after BIOS matrix |
|---|---|
| Longhorn unmount deadlock | Unchanged — Longhorn runs on all three identically, doesn't explain single-node. |
| Silent hardware/kernel watchdog (iTCO) | Unchanged — identical hardware on k8s-1 means iTCO driver, microcode, etc. are the same modulo BIOS. BIOS 1.26 contains a microcode update; if microcode fixes stabilize k8s-1, it'd also stabilize k8s-2 post-upgrade. Worth testing. |
| Hardware unit-level defect (devils-advocate H1) | **Strengthened.** k8s-3 on 1.22 is stable → the 1.22 BIOS is not the variable. The remaining differences between k8s-2 and k8s-3 are: serial number, and whatever individual-unit differences exist (DIMMs, NVMe units, thermal paste, PCH variance). |
| BIOS AHWSA.1.22 stale | **Partially relevant.** 1.26 is a real upgrade; brings microcode + restored C-State. Not the root cause (k8s-3 counter-example) but a reasonable preventive step once we decide to act. |

## Recommendation for Phase 2 planning (not applied here)

If Phase 2 goes ahead:

- **Upgrade k8s-2 and k8s-3 to BIOS 1.26** (not 1.27 — 1.27 changes power limits significantly and should be done cluster-wide with awareness, not as a single-node fix). This is a single-variable change that aligns k8s-2 with k8s-1's already-stable configuration.
- **BIOS upgrade is a physical action** — MS-01 flashing requires UEFI shell + USB stick, done at the console. This is not a `talosctl` operation. Plan accordingly.
- **If BIOS upgrade does not stop the reboots**, the next diagnostic move is the devils-advocate DIMM swap — trade RAM between k8s-2 and k8s-3 and watch whether reboots follow the DIMM or stay with the chassis. Cheap, decisive for "is this a single failing DIMM?".
- **Update `context/hardware.md`** with actual current BIOS versions per node (currently stale — shows `AHWSA.1.22` uniformly).

## Why not flash now

Per the Phase 1 read-only mandate and the top-of-session constraints:

> Absolutely no cluster mutation yet.

BIOS flashing is the most impactful mutation there is — unrecoverable on failure. It also requires physical console access (USB stick in the MS-01 front port — MS-01 has no BMC/IPMI/Redfish, see [`corrigendum-2026-04-20-no-bmc.md`](corrigendum-2026-04-20-no-bmc.md)). It belongs to Phase 2 at the earliest, after explicit user approval and ideally after the next-reboot evidence captured by Phase 2's in-band logging destinations has landed.

## Sources

- [How to upgrade the Minisforum MS-01 BIOS — virtualizationhowto.com](https://www.virtualizationhowto.com/2024/09/how-to-upgrade-the-minisforum-ms-01-bios/)
- [Minisforum support page (MS-01)](https://support.minisforum.com/pages/product-info?lang=en)
