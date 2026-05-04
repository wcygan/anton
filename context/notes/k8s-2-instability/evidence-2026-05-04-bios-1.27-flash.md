# Physical Intervention: BIOS 1.27 Flash on k8s-2 and k8s-3

**Date:** 2026-05-04
**Operator:** wcygan (physical access)
**Scope:** Flash BIOS 1.27 on k8s-2 and k8s-3. k8s-1 left on 1.26 as the stable anchor.
**Decision deferral:** DIMM swap **deferred**. The plan-0009 followup originally scheduled DIMM swap + BIOS flash in the same session. Operator chose BIOS-only first to keep variables separable: if reboots continue post-1.27, DIMM swap is the next physical step.

## Pre-flash state

Captured before draining each node.

| Node | BIOS pre | BIOS date pre | Boot ID pre | Uptime pre |
|------|----------|---------------|-------------|------------|
| k8s-1 (anchor, untouched) | 1.26 | 2024-10-14 | (not captured this session) | — |
| k8s-2 | AHWSA.1.22 (reported as `Default string` via systeminformation; sysfs resolved to `1.22`) | — | `c7ba7730-512f-4641-9af1-cd21d0381e4f` | ~62.16 h (boot ~2026-04-30T23:51Z) |
| k8s-3 | AHWSA.1.22 | 2024-03-12 | `2ff53666-b943-4fad-8149-b22babd25c19` | (not measured; node was Ready and serving) |

**R9 silent reboot detected at session start.** Plan-0009 handoff recorded post-R8 boot ID `7ce1b3bb-77e7-4677-850a-84be8b7f6a7c`. Pre-flash sample showed `c7ba7730-512f-4641-9af1-cd21d0381e4f` with uptime 62.16 h, implying a reboot at ~2026-04-30T23:51Z — about 21 h after R8 (R8 was 2026-04-30T02:32:42Z). This is the 9th silent reboot in the investigation window. Counted forward in plan-0009 as **R9**.

## Procedure executed

Per node, in sequence (k8s-2 first, k8s-3 second). k8s-1 + the not-yet-flashed peer held etcd quorum during each step.

1. `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` (gated by `ANTON_DESTRUCTIVE_OK=1` per repo guard)
2. Operator: power off, USB boot via F11 / BBS menu (Minisforum boot menu)
3. UEFI shell from USB → `map -r` → `FS0:` → `ls` → `AfuEfiFlash.nsh`
4. AFU-driven flash, auto-reboot
5. Post-flash: SMBIOS read of `/sys/class/dmi/id/bios_version` to confirm 1.27
6. `kubectl uncordon` after both nodes verified

### k8s-2 quirk: built-in UEFI Shell rejected

Selecting the built-in UEFI Shell from the Minisforum F11 boot menu kicked the operator straight back to the menu — interpreted as a Secure-Boot block on the firmware-embedded shell. Workaround: use the **BBS menu** to boot the USB stick directly. The USB-resident UEFI Shell loaded fine. Recorded so the next operator skips the dead-end.

### k8s-3 quirk: returned to USB shell after flash

After `AfuEfiFlash.nsh` completed and the system auto-rebooted, k8s-3 came back to the USB UEFI Shell rather than booting the internal NVMe — boot order on a freshly-flashed BIOS defaults to whatever it finds first (the USB). Workaround: `exit` from the shell to drop into Setup, pull the USB, **F10 Save & Exit**, normal Talos boot. Recorded so the next operator does this without panic.

## Post-flash state

Captured after both flashes succeeded and both nodes were uncordoned.

| Node | BIOS post | BIOS date post | Boot ID post (final, after uncordon) | Uptime at final read |
|------|-----------|----------------|--------------------------------------|----------------------|
| k8s-1 | 1.26 | 2024-10-14 | `374d7bdd-530f-4e88-8194-8f66554b9ca8` | ~79.36 h (untouched, expected) |
| k8s-2 | **1.27** | 2025-04-03 | `28688229-2d15-4216-b028-8b558a5530fe` | ~10.15 h |
| k8s-3 | **1.27** | 2025-04-03 | `7cc9ced8-a46a-459f-b860-674df340d23b` | ~10.18 h |

Etcd: 3/3 healthy (`50beb6304d05dae3` k8s-2, `114ce46a139b1a91` k8s-3, `8626e6c4157f9b39` k8s-1). All nodes Ready, no `SchedulingDisabled`.

Note that BIOS version field naming changed across the upgrade: k8s-3 pre-flash reported `AHWSA.1.22` (platform-prefixed). Both nodes now report just `1.27`. Cosmetic only — same chip family.

## Open flag (resolved): k8s-2 boot ID transition during the inter-flash gap

Post-flash sample taken ~31 s after k8s-2 came up was `07787445-fee7-4245-84f6-7fd68a1868f4`. The end-of-session sample (after uncordon, ~10.15 h later) was `28688229-2d15-4216-b028-8b558a5530fe`. The boot ID changed in between, raising the question of whether a silent reboot had landed post-1.27.

**Resolved 2026-05-04 by operator confirmation:** the boot ID transition was an **operator-initiated manual power cycle** during BIOS-settings debugging between the k8s-2 and k8s-3 flashes. Not a silent reboot.

The final post-flash watch window therefore starts at the **second** post-flash boot, `28688229-2d15-4216-b028-8b558a5530fe` at ~2026-05-04T01:46Z. As of 2026-05-04T12:17Z (~10.5 h later), Prometheus `changes(node_boot_time_seconds[12h]) = 0` across all node-exporter series for all three nodes; no `K8s2UnexpectedReboot` alert; zero container terminations on k8s-2 or k8s-3 since boot; kernel sink shows only the known-cosmetic `KernelParamSpecController` retries documented in plan-0009 line 145.

**48-72 h watch window stands.** If k8s-2 remains stable through 2026-05-06 → 2026-05-07, the BIOS-fix hypothesis carries. If a reboot lands inside that window, hypothesis #1 (single-unit hardware defect on k8s-2's chassis) is back on top and the next physical step is the deferred DIMM swap.

## Tooling notes for the next session

- `talosctl read /sys/class/dmi/id/bios_version` is the cleanest BIOS-version source from a running Talos node. The Talos `systeminformation` resource shows `Default string` for the BIOS field on this hardware — SMBIOS exposes the version through `dmi/id/bios_version` only.
- `talosctl read /proc/sys/kernel/random/boot_id` + `/proc/uptime` is the boot-tracking pair we have been using; same as before.
- The `guard_destructive.py` PreToolUse hook will block `kubectl drain --delete-emptydir-data`. Prefix with `ANTON_DESTRUCTIVE_OK=1 ` to authorize. Documented here so a future operator doesn't waste a cycle on it.

## Cross-references

- Plan 0009 — k8s-2 / k8s-3 silent-reboot followup. **This evidence note is the closing artifact for the BIOS-flash branch of plan-0009 Stage 4 (physical intervention).** Append a Log entry to plan-0009 pointing here, then keep plan-0009 in-progress for the 48-72 h watch window.
- ADR 0017 (Multus storage-network), ADR 0020/0021/0022 (cilium memory) — unaffected by this work.
- Evidence file `evidence-2026-04-30-web-research.md` — community reports of MS-01 + BIOS 1.22 instability that motivated this flash, plus the Raptor Lake "passes stress, fails at idle" Vmin-shift signature. The 1.27 flash carries the Intel voltage-fix microcode introduced at 1.26 plus 1.27's PL1/PL2/turbo tuning — both are independently plausible mitigations for the observed pattern.
