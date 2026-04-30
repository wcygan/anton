# Web Research: MS-01 / Raptor Lake / Talos Silent Reboot Patterns

**Date:** 2026-04-30
**Purpose:** Cross-reference k8s-2's silent reboot pattern against community reports for the Minisforum MS-01, Intel Raptor Lake, Talos Linux, and related subsystems (NVMe ASPM, DDR5, hardware watchdog).

## Key Finding: "Passes Stress, Fails at Idle" is a Known Raptor Lake Signature

k8s-2 survived 4 hours of heavy stress-ng (Stage 3.5) then silently rebooted ~5 hours later under idle/light load (R8 at 2026-04-30T02:32:42Z). This exact pattern — **stable under heavy load, crashes at idle** — is a documented Intel Raptor Lake failure mode.

**The mechanism:** The Vmin shift bug causes the CPU's minimum safe operating voltage (Vmin) to drift upward over time due to electromigration damage in the clock tree circuit. Under heavy load, the CPU operates at higher voltages where the degraded silicon still functions. At idle/light load, it transitions to low-voltage C-states where the elevated Vmin threshold is no longer met, causing the clock tree to glitch and the CPU to crash silently.

Intel's 0x12F microcode was specifically created for this scenario — systems "continuously running for multiple days with low-activity and lightly-threaded workloads." This is a textbook description of k8s-2's operating profile.

**Mobile caveat:** Intel officially states mobile processors (i9-13900H, as in the MS-01) are "not affected." However, field reports from game developers and laptop users document identical crashes on mobile Raptor Lake. Nobody has specifically studied the scenario of running a mobile chip 24/7 as a server — a duty cycle the chip was never designed for.

## MS-01 + BIOS 1.22: Widespread Instability Reports

Multiple independent communities report the same symptom on MS-01 hardware:

| Source | Symptom | BIOS | Resolution |
|--------|---------|------|------------|
| Lawrence Systems forum | 3 MS-01s, random reboots every few weeks | 1.22 | BIOS update |
| XCP-ng forum | MS-01 hangs completely every 14d–1mo, black screen, no logs | Various | Hardware-level, not hypervisor |
| Proxmox forum | 1 of 5 MS-01 nodes unstable, nothing in journal | Various | Under investigation |
| Proxmox forum | i9-13th shutdown issue | Various | PL1 was set to 0; fixed by setting PL1=55000 |
| Notebookcheck review | "repeatedly accompanied by unpredictable crashes" during benchmarks | N/A | N/A |

**BIOS changelog (key versions):**

| Version | Date | Key Changes |
|---------|------|-------------|
| **1.22** (k8s-2, k8s-3) | Early 2024 | Older microcode, ASPM enabled, known stability issues |
| 1.24 | 2024/07/05 | Beta — DDR5 clock controls, 96GB stability fix |
| 1.25 | 2024/09/19 | PCIe ASPM disabled, RTD3 disabled, C-State disabled |
| **1.26** (k8s-1) | 2024/10/14 | Updated microcode (Intel voltage fix), C-State re-enabled. Widely confirmed stable |
| 1.27 | 2025/04/03 | Turbo Ratio Limit, PL1/PL2 tuning, GOP update |

Community-maintained BIOS tracker: [rezzorix/minisforum-bios-updates](https://github.com/rezzorix/minisforum-bios-updates).

**Counter-signal from our cluster:** k8s-3 is also on BIOS 1.22 and has never silently rebooted. This weakens the "BIOS 1.22 is sufficient cause" framing but does not eliminate BIOS as a *contributing* factor — different chassis may have different DIMM training behavior, thermal profiles, or silicon quality even at the same BIOS version.

## New Hypothesis: Hardware Watchdog Running Unfed

Talos GitHub issue #10556 documents a scenario where the iTCO_wdt (Intel TCO Watchdog Timer) kernel module loads automatically on Intel hardware. If the BIOS has the TCO watchdog enabled but Talos is not configured to feed it via `WatchdogTimerConfig`, the watchdog times out and reboots the node silently — **zero kernel logs, zero pre-reboot indicators.** This exactly matches k8s-2's signature.

**Status in our cluster:** The earlier investigation (evidence-2026-04-20-talos-inspect.md) found iTCO_wdt loaded identically on k8s-1 and k8s-2 with no `WatchdogTimerConfig` configured on any node. If the watchdog is the cause, it should affect all nodes equally — but only k8s-2 reboots. This weakens the watchdog-only hypothesis unless k8s-2's watchdog has different BIOS-level timeout settings or k8s-2 is the only node experiencing the hangs that trigger the watchdog timeout.

**Action needed:** Verify watchdog BIOS settings per-node and confirm whether watchdog timeout differs. Consider explicitly configuring `WatchdogTimerConfig` on all nodes to ensure Talos feeds the watchdog, or disabling the TCO timer in BIOS.

## NVMe / PCIe ASPM Power State Transitions

Consumer NVMe drives on mini PCs are documented as causing silent reboots when Linux's aggressive power-saving features (APST/ASPM) are enabled. The NVMe controller enters a low-power state, fails to wake in time, and the system resets too fast for kernel logs to be written. This is documented specifically for mini PC form factors.

**Relevant kernel parameters:**

```
nvme_core.default_ps_max_latency_us=0   # Disable NVMe power state transitions
pcie_aspm=off                             # Disable PCIe Active State Power Management
```

**Note:** The MS-01 BIOS 1.25 explicitly disabled ASPM; 1.26 re-enabled it in a managed form. BIOS 1.22 has ASPM enabled with no known mitigations.

## Intel I226-V NIC + ASPM

The Intel I226-V NICs in the MS-01 are independently documented as causing system-level hangs when ASPM is enabled. The NIC drops off the PCIe bus silently — no kernel panic, no MCE. Fix: disable ASPM in BIOS and/or kernel parameter `pcie_aspm=off`, disable EEE.

## C-State Transitions and Idle Crashes

Deep C-states (C6 and deeper) involve aggressive voltage reduction and clock gating. On a Raptor Lake CPU with potential Vmin degradation, transitioning into these states drops the voltage below the minimum threshold. Kernel parameters to mitigate:

```
intel_idle.max_cstate=1    # Prevent deep idle states
processor.max_cstate=1     # ACPI-level C-state limit
```

Multiple Proxmox users report that limiting C-states resolved idle crashes on 13th-gen Intel systems. One user with a 13900 reported the system "consistently crashes if left sitting idle" — resolved by C-state limiting.

## DDR5 Memory Considerations

- The MS-01 BIOS downclocks DDR5 to 4800 MT/s regardless of rated speed (no user-accessible XMP/DOCP). Both Mushkin 5200 and Crucial 5600 sticks are likely running at 4800.
- DDR5 modules contain an on-die PMIC for per-stick voltage regulation. Different vendors may use different PMICs with subtly different voltage behavior and training characteristics.
- DDR5 requires a "training" phase at boot where the memory controller calibrates signal timing. Corrupted training data is documented as causing boot loops and intermittent crashes.
- 96GB configurations (2×48GB) with 13th gen are specifically called out as unstable on older BIOS versions. BIOS 1.24 (beta) introduced DDR5 clock controls to address this.
- Both Mushkin and Crucial use Micron ICs, so the IC manufacturer is not the differentiator. However, SPD timings, voltage profiles, and training characteristics at 5200 vs 5600 could differ.

## Talos Linux Specific Issues

| Issue | Relevance |
|-------|-----------|
| [#10556](https://github.com/siderolabs/talos/issues/10556) — Watchdog not being fed | **High** — iTCO_wdt loaded but unfed → silent reboot with zero logs |
| [#11315](https://github.com/siderolabs/talos/issues/11315) — Node freezes for extended period | **Medium** — random freezes around 4:30 AM, no error logs, all services timeout simultaneously |
| [#8284](https://github.com/siderolabs/talos/issues/8284) — Watchdog timer support | **Context** — feature added in v1.7.0; watchdog may be running even without explicit configuration |
| [#9466](https://github.com/siderolabs/talos/issues/9466) — Node randomly restarts | **Low** — produced kernel panic, unlike our pattern |
| [#8751](https://github.com/siderolabs/talos/issues/8751) — Bare-metal reboot issues | **Low** — different mechanism (kernel reboot parameter) |

## Immediate Remote Diagnostics (No Physical Access)

Based on this research, three actions can be taken without physical access:

1. **Verify watchdog state:** `talosctl -n k8s-2 read /proc/modules | grep iTCO` — confirm module loaded, check if watchdog is being fed
2. **Add kernel parameters to Talos machine config:**
   ```yaml
   machine:
     install:
       extraKernelArgs:
         - nvme_core.default_ps_max_latency_us=0
         - pcie_aspm=off
         - intel_idle.max_cstate=1
         - processor.max_cstate=1
   ```
3. **Configure WatchdogTimerConfig** on all nodes so Talos explicitly feeds the hardware watchdog

## Physical Access Actions (Unchanged Priority)

1. BIOS 1.22 → 1.27 flash (delivers 0x12B microcode + ASPM/power management fixes)
2. DIMM swap (k8s-2 Mushkin ↔ k8s-3 Crucial)
3. Boot-time memtest86+

## Updated Hypothesis Ranking

Incorporating web research, the Stage 3.5 pass, and the R8 idle reboot:

1. **Intel Raptor Lake Vmin shift / C-state voltage drop** — STRENGTHENED. The "passes stress, fails at idle" pattern is the textbook Vmin shift signature. BIOS 1.22 lacks the 0x12B/0x12F microcode mitigations. Even if mobile chips are "officially" unaffected, the 24/7 server duty cycle is outside Intel's tested envelope.
2. **Single-unit k8s-2 hardware defect** — MAINTAINED. k8s-3 shares BIOS 1.22 and is stable, so something is k8s-2-specific (DIMM, thermal, VRM, silicon lottery). Could be Vmin degradation that has already occurred on this specific CPU.
3. **NVMe / PCIe ASPM power state transition** — NEW. Well-documented on mini PCs, produces exactly the "silent reboot, no kernel logs" pattern. Cheap to test via kernel parameters.
4. **Hardware watchdog timeout** — WEAKENED (iTCO_wdt identical on all nodes per earlier evidence), but worth explicitly configuring or disabling as defensive measure.
5. **DDR5 Mushkin training / compatibility** — MAINTAINED. The DIMM is still the strongest k8s-2-unique hardware variable. DIMM swap is the decisive test.

---

## References

### MS-01 Stability

- [Minisforum MS-01 unstable and hangs running XCP-ng 8.3](https://xcp-ng.org/forum/topic/9500/minisforum-ms-01-unstable-and-hangs-running-xcp-ng-8-3) — MS-01 hangs every 14d–1mo, no logs
- [Weird issues with MS-01 and XCP-ng (Lawrence Systems)](https://forums.lawrencesystems.com/t/weird-issues-with-ms-01-and-xcp-ng-scratching-my-head/25244) — 3 MS-01s on firmware 1.22, random reboots
- [1/5 MS-01 Nodes Unstable (Proxmox)](https://forum.proxmox.com/threads/1-5-ms-01-nodes-unstable-not-much-in-journal.151981/) — 1 of 5 unstable, nothing in journal
- [MS-01 i9-13th shutdown issue (Proxmox)](https://forum.proxmox.com/threads/minisforum-ms-01-i9-13th-shutdown-issue.142065/) — PL1 set to 0 causing crashes
- [Proxmox install on MS-01](https://forum.proxmox.com/threads/proxmox-install-on-minisforum-ms-01.154110/) — i9-13900H + 96GB instability
- [Notebookcheck MS-01 review](https://www.notebookcheck.net/Workstation-review-Minisforum-MS-01-debuts-with-Intel-Core-i9-13900H-but-lacks-a-dedicated-graphics-card-ex-works.836742.0.html) — "unpredictable crashes"

### MS-01 BIOS & Firmware

- [rezzorix/minisforum-bios-updates (GitHub)](https://github.com/rezzorix/minisforum-bios-updates) — Community BIOS changelog
- [How to Upgrade the MS-01 BIOS (VirtualizationHowTo)](https://www.virtualizationhowto.com/2024/09/how-to-upgrade-the-minisforum-ms-01-bios/) — Update guide, 1.26 confirmed stable
- [Firmware Update Minisforum Without Windows (Quindorian)](https://blog.quindorian.org/2025/05/firmware-update-minisforum-without-windows.html/) — Non-Windows BIOS flashing
- [State of Proxmox on MS-01 (Medium)](https://medium.com/@PlanB./the-state-of-proxmox-on-minisforum-ms-01-stability-performance-and-insights-for-late-2024-a820c516e6c3) — 1.26 confirmed stable

### Intel I226 NIC / ASPM

- [Intel I226-V randomly disconnecting (Intel Community)](https://community.intel.com/t5/Ethernet-Products/Intel-I226-V-is-still-randomly-disconnecting/td-p/1630534) — NIC drops off bus silently
- [MS-01 NIC performance issues (XCP-ng)](https://xcp-ng.org/forum/topic/9276/ms-01-performance-issues-w-intel-226-nics) — I226 issues on MS-01
- [I226-V ASPM issues (OPNsense)](https://forum.opnsense.org/index.php?topic=42240.0) — ASPM causing system hangs

### Intel Raptor Lake Vmin Shift

- [Intel Root Cause Announcement (official)](https://community.intel.com/t5/Blogs/Tech-Innovation/Client/Intel-Core-13th-and-14th-Gen-Desktop-Instability-Root-Cause/post/1633239) — Elevated voltage → clock tree degradation
- [Intel 0x12F Microcode Update](https://community.intel.com/t5/Mobile-and-Desktop-Processors/Intel-Core-13th-and-14th-Gen-Vmin-Shift-Instabilty-Update-New/m-p/1686948) — Fixes light-load/idle instability
- [Extensive Analysis of the Raptor Lake CPU Bug (machaddr)](https://machaddr.substack.com/p/extensive-analysis-of-the-raptor) — Deep technical breakdown
- [Tom's Hardware: 0x12F update](https://www.tomshardware.com/pc-components/cpus/raptor-lake-instability-saga-continues-as-intel-releases-0x12f-update-to-fix-vmin-instability) — 0x12F details
- [Intel warranty extension](https://community.intel.com/t5/Processors/Additional-Warranty-Updates-on-Intel-Core-13th-14th-Gen-Desktop/m-p/1620853) — 2-year warranty extension

### Mobile Raptor Lake (i9-13900H)

- [Intel confirms mobile chips "not affected" (Notebookcheck)](https://www.notebookcheck.net/Intel-confirms-13th-and-14th-gen-Raptor-Lake-laptop-chips-are-not-affected-by-their-desktop-counterparts-instability-issues.865474.0.html) — Intel's official position
- [Dev reports laptop CPUs also crashing (Tom's Hardware)](https://www.tomshardware.com/pc-components/cpus/dev-reports-that-intels-laptop-cpus-are-also-crashing-several-laptops-have-suffered-similar-crashes-in-testing) — Field reports contradicting Intel
- [Intel says mobile crashing but different bug (Tom's Hardware)](https://www.tomshardware.com/pc-components/cpus/intel-says-13th-and-14th-gen-mobile-cpus-are-crashing-but-not-due-to-the-same-bug-as-desktop-chips-chipmaker-blames-common-software-and-hardware-issues) — Intel's nuanced response
- [i9-13900HX failure after 1 year (Level1Techs)](https://forum.level1techs.com/t/intel-core-i9-13900hx-failure-after-1-year/234514) — Mobile chip failure
- [XMG statement on mobile stability](https://www.xmg.gg/en/news-update-intel-core-cpus-laptops-stability/) — Laptop OEM perspective

### Talos Linux

- [Issue #10556 — Watchdog not being fed](https://github.com/siderolabs/talos/issues/10556) — iTCO_wdt loaded but unfed → silent reboot
- [Issue #8284 — Watchdog timer support](https://github.com/siderolabs/talos/issues/8284) — Feature added in v1.7.0
- [Issue #11315 — Node freezes for extended period](https://github.com/siderolabs/talos/issues/11315) — Random freezes, no error logs
- [Issue #9466 — Node randomly restarts](https://github.com/siderolabs/talos/issues/9466) — Reboots after v1.8.1 upgrade
- [Issue #8751 — Bare-metal reboot issues](https://github.com/siderolabs/talos/issues/8751) — Kernel reboot parameter change
- [Talos Watchdog Documentation](https://www.talos.dev/v1.9/advanced/watchdog/) — Official config reference

### NVMe / Power Management

- [Stabilizing Mini PCs on Linux (ramon.vanraaij.eu)](https://ramon.vanraaij.eu/stabilizing-mini-pcs-on-linux-fixing-random-reboots-nvme-power-issues/) — NVMe ASPM causing silent reboots
- [intel_idle.max_cstate explained (Medium)](https://medium.com/@dibyadas/intel-idle-max-cstate-1-b20281e4b2e2) — C-state limiting

### DDR5 Memory

- [DDR5 RAM Stability Issues (box.co.uk)](https://box.co.uk/blog/ddr5-memory-stability-problems-fix) — General DDR5 stability
- [DDR5 memory training (Crucial)](https://www.crucial.com/support/articles-faq-memory/ddr5-memory-training) — Training process
- [DDR5 RAM training corruption (Linus Tech Tips)](https://linustechtips.com/topic/1592209-ddr5-ram-training-corruption-theory-forcing-retrain-solved-insane-boot-issues/) — Corrupted training → instability
- [MS-01 RAM compatibility (Level1Techs)](https://forum.level1techs.com/t/minisforum-ms-01-compatibility-database/208655?page=4) — Compatibility database
- [Mushkin DDR5 SODIMM review (ServeTheHome)](https://www.servethehome.com/mushkin-redline-96gb-2x-48gb-ddr5-5600-sodimm-non-binary-upgrade-kit/) — Mushkin DDR5 testing

### C-State / Idle Crash Pattern

- [Microcode 0x12F fixes light-load instability (WindowsForum)](https://windowsforum.com/threads/intel-raptor-lake-stability-microcode-0x12f-fixes-light-load-cpu-instability.365498/) — Targets idle/light-load crashes
- [Proxmox: crashing on 13th gen Intel CPU](https://forum.proxmox.com/threads/proxmox-crashing-on-13th-gen-intel-cpu.126360/) — Proxmox + 13th gen
- [Proxmox: random crashes without logs](https://forum.proxmox.com/threads/proxmox-random-crashes-without-logs.174337/) — Same pattern
- [Linux Freezing Intel 13th Gen (Intel Community)](https://community.intel.com/t5/Mobile-and-Desktop-Processors/Linux-Freezing-Intel-13th-Gen-Core-i7-13620H/td-p/1558763) — Linux + mobile 13th gen
