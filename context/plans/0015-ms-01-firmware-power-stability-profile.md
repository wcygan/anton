---
status: In-progress
opened: 2026-05-06
closed: null
affects: compute
intent: concrete-need
related-adrs: []
related-plans: [0013]
related-postmortems: [2026-05-05-k8s-1-k8s-3-dual-silent-reboot]
review-by: 2026-05-20
---

# 0015 — Stabilize MS-01 firmware and CPU power profile

> Apply a conservative, repeatable Minisforum MS-01 stability profile before escalating to Talos/Linux runtime power mitigations.

## Goal

Reduce the probability of MS-01 silent reboots / hard hangs by normalizing all three nodes onto a conservative firmware and power-management baseline: BIOS 1.27 where available, lower DDR5 speed, capped turbo ratios, fixed PCIe speed for the X710 storage fabric, unused radios/buses disabled, and Thunderbolt treated as out-of-scope unless it is actually enabled or appears in live inventory. If the BIOS profile does not stop the failure class, add a repeatable Talos-managed runtime CPU power cap (`balance_power` + 90% max frequency) as the next mitigation layer.

## Acceptance criteria

- [ ] All three MS-01 nodes have their BIOS version, memory speed, CPU turbo limits, X710 PCIe slot speed, Wi-Fi/CNVi state, and Thunderbolt/USB4 state recorded in `context/hardware.md` or a linked evidence note
- [ ] All three nodes run the same conservative BIOS profile, or any intentional node-specific exception is documented with rationale
- [ ] After the BIOS profile is applied, the cluster completes a 7-day watch window with zero unexplained reboots, OR the next unexplained reboot is captured by plan 0013's forensic surfaces and this plan moves to the runtime-mitigation phase
- [ ] The runtime CPU cap is either implemented as a repeatable Talos/Kubernetes artifact and verified on all nodes, or explicitly deferred because the BIOS profile was sufficient
- [ ] Thunderbolt-specific mitigation (`thunderbolt.host_reset=0`) is either not used because Thunderbolt is disabled/unused, or is justified by live Thunderbolt symptoms and captured in the Talos boot-argument strategy

## Tasks

### Phase 1 — BIOS stability profile

- [ ] Confirm and record current BIOS version on k8s-1, k8s-2, and k8s-3 before changes
- [ ] Upgrade the remaining BIOS 1.26 node to BIOS 1.27 unless a concrete regression or recovery-risk reason blocks normalization
- [ ] Set DDR5 memory speed to 4400 MT/s on all three nodes if the BIOS exposes the option
- [ ] Disable `Overclocking Lock`, then cap turbo ratios: P-core ratio0/ratio1 = 51/51, E-core ratio0/ratio1/ratio2/ratio3 = 40/40/40/40
- [ ] Set the PCIe slot containing the Intel X710 SFP+ adapter to fixed Gen3 instead of Auto/Gen4, if the BIOS exposes the option
- [ ] Disable unused Wi-Fi/CNVi; leave RJ45 management and X710 SFP+ storage mesh unchanged
- [ ] Disable Thunderbolt/USB4 in BIOS if exposed and confirmed unused; otherwise record that it remains enabled-but-unused
- [ ] Save BIOS settings, boot Talos, re-enter BIOS once on each node, and confirm the settings persisted

### Phase 2 — Post-change verification and watch

- [ ] Capture post-change boot IDs and uptime for all three nodes
- [ ] Verify all nodes are `Ready`, Flux kustomizations and Helm releases are healthy, and no non-running pods remain unexplained
- [ ] Verify Talos core services are healthy on all three nodes
- [ ] Verify X710 links remain up on all six SFP+ ports and `vxlan-storage` / `lhnet1-host` are present
- [ ] Verify Vector kernel sink and plan 0013 reboot/Unknown-pod alerts are still live before starting the watch window
- [ ] Run a 48-hour checkpoint and a 7-day checkpoint; record any boot-ID changes, alerts, or link instability

### Phase 3 — Runtime CPU power mitigation if BIOS profile is insufficient

- [ ] If an unexplained reboot occurs after Phase 1, capture the event under plan 0013 first; do not mask the failure before collecting evidence
- [ ] Record current cpufreq state on all nodes: `scaling_governor`, `energy_performance_preference`, `scaling_max_freq`, and `cpuinfo_max_freq` for every policy
- [ ] Design a repeatable privileged DaemonSet or Talos-compatible mechanism that writes `balance_power` to `policy*/energy_performance_preference` and caps `policy*/scaling_max_freq` to 90% of `policy*/cpuinfo_max_freq`
- [ ] Roll the runtime cap to one node first during a maintenance window, verify sysfs values stick, then expand to all three nodes if stable
- [ ] Decide whether the runtime cap becomes permanent, remains an experiment, or is removed after evidence review

### Phase 4 — Thunderbolt boundary

- [ ] Keep Thunderbolt out of the primary hypothesis unless live inventory shows Thunderbolt/USB4 interfaces, the Thunderbolt kernel module is loaded, or reboot/link symptoms implicate it
- [ ] If Thunderbolt remains enabled in BIOS, periodically verify it is not part of the active network/storage topology (`talosctl get links`, `/sys/module/thunderbolt`)
- [ ] Only evaluate `thunderbolt.host_reset=0` if Thunderbolt symptoms appear; Talos boot-argument handling must be planned carefully because the current UKI path does not make kernel-arg changes a normal live config tweak
- [ ] If a Thunderbolt ring is introduced later, open a separate topology plan rather than folding it into this MS-01 SFP+ stability profile

### Phase 5 — Close-out

- [ ] Update `context/hardware.md` with final BIOS and stability-profile state
- [ ] Update plan 0013 with whether this mitigation changed the reboot behavior or simply reduced risk
- [ ] If the BIOS/runtime profile becomes a durable cluster requirement, consider an ADR documenting the accepted MS-01 stability baseline
- [ ] Close this plan as Done if the stability profile holds through the watch window; close as Abandoned if plan 0013 localizes a different root cause and these mitigations are no longer load-bearing

## Log

- 2026-05-06: Plan opened after web/community research showed MS-01 instability reports clustering around BIOS 1.26/1.27, 96 GiB DDR5 configurations, idle/light-load hangs, PCIe power-management edge cases, and vendor/community guidance to lower memory speed and cap turbo ratios.
- 2026-05-06: Live cluster inventory confirmed the active topology is RJ45 management plus Intel X710 SFP+ full mesh; no Thunderbolt network links are used. Current kernel cmdline has no `pcie_aspm`, C-state, cpufreq, or `thunderbolt.host_reset` mitigations. Representative cpufreq state on k8s-1 is `scaling_governor=powersave`, `energy_performance_preference=balance_performance`, and `scaling_max_freq=cpuinfo_max_freq=5200000`.
- 2026-05-06: Remote baseline from gertrude recorded in `../notes/k8s-2-instability/evidence-2026-05-06-ms-01-bios-amt-baseline.md`: k8s-1 is BIOS 1.26 (`10/14/2024`), k8s-2 and k8s-3 are BIOS 1.27 (`04/03/2025`), and AMT/KVM was not reachable from the LAN bastion during this check.

## References

- Related plan: [0013](0013-cluster-wide-silent-reboot-localization.md) — root-cause localization and forensic capture remain the parent investigation
- Hardware inventory: [`../hardware.md`](../hardware.md)
- Postmortem: [`../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md)
- Incident: [`../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`](../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md)
- Evidence: [`../notes/k8s-2-instability/evidence-2026-05-06-ms-01-bios-amt-baseline.md`](../notes/k8s-2-instability/evidence-2026-05-06-ms-01-bios-amt-baseline.md)
- MS-01 BIOS notes: <https://www.virtualizationhowto.com/2024/09/how-to-upgrade-the-minisforum-ms-01-bios/>
- Linux Thunderbolt `host_reset` source: <https://codebrowser.dev/linux/linux/drivers/thunderbolt/nhi.c.html>
- Linux kernel parameter reference: <https://www.kernel.org/doc/html/v6.0/admin-guide/kernel-parameters.html>
- Operator-provided community inputs: Discord excerpts about `balance_power` + 90% max frequency, Thunderbolt ring removal, and `thunderbolt.host_reset=0`
- Live checks used to open this plan: `talosctl get links`, `talosctl read /proc/cmdline`, `talosctl read /sys/devices/system/cpu/cpufreq/policy*/...`
