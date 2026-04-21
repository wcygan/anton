# 2026-04-20 — Multi-agent RCA investigation

Five Opus agents reviewed `~/Development/notes/ideas/k8s-2-reboot-issues.md` in parallel, in isolation, each from a distinct lens. This is the synthesis — with emphasis on **where they disagreed**, since that's where the load-bearing insight lives.

## Team composition

| Agent | Lens | Mandate |
|---|---|---|
| `talos-operator` | Talos-layer internals (sequencer, machined, kubelet-as-Talos-service, watchdogs) | Propose Talos-specific RCA hypotheses; critique the five-tier plan from a Talos-correctness angle |
| `cluster-triage` | Cluster-above-OS view (Tailscale, Cilium, kubelet eviction, leader election, zombies) | Find cluster-internal causes and correlated symptoms across all three nodes |
| `observability-advisor` | Signals we're not using (metrics already scraped, missing alerts) | Review the five-tier plan for coverage gaps; propose PromQL alerts |
| `devils-advocate` | Adversarial | Challenge the evidence base, the counting method, the causal chain, and every proposed fix |
| `simplifier` | "Three nodes in an apartment" | Argue for deletion. Find the minimum-viable fix |

All five were read-only. Results below are summaries of their reports; the full agent output lived in this session's history and is preserved in the key findings below.

## Agent findings (summary)

### talos-operator — Talos-layer RCA

**Top hypothesis: hardware / kernel watchdog firing silently.** Talos ships `runtime.WatchdogTimer` plus kernel `softdog` / `iTCO_wdt`. Once armed, expiry emits `Reboot: Restarting system` via kernel `printk` only — exactly the silent, log-less pattern observed at 14:09:27 → 14:10:17 UTC on Apr 20.

**Dismissed:** `runtime.DropUpgradeFallbackController` (that's post-boot housekeeping, not causal — seeing it in the boot log is a red herring).

**Key objections to the original plan:**
- **Bumping `shutdownGracePeriodRequested` to 90s is dangerous.** Talos's own sequencer shutdown deadline is ~60s. Kubelet holding past that triggers machined force-kill → defeats the whole point. **Cap at 55s** and fix Longhorn teardown ordering instead.
- **netconsole `@<src-iface>` on kernel 6.18** will silently fail on bond/VLAN slaves. Pin to primary 2.5G NIC MAC, not the SFP+ storage mesh.
- **UDP Tier-1 to `nc -lku`** will lose the watchdog-trigger frame every time because the stack is already dying. **Tier 2 netconsole is not optional if watchdog is the cause** — it runs below userspace.

**Evidence gaps to close:**
- `talosctl -n k8s-2 get watchdogtimerconfigs watchdogtimerstatuses machineconfig -o yaml | yq .spec.runtime.watchdogTimer`
- `talosctl -n k8s-2 get bootstatuses upgradestatus metakeys`
- `talosctl -n k8s-2 read /var/log/machined.log | rg -i 'MachineService/(Reboot|Shutdown)|sequencer'`
- `talosctl -n k8s-2 dmesg | rg -i 'softdog|iTCO|watchdog|NMI|hardlockup|rcu_sched'` at next reboot
- `talosctl -n k8s-2 get kernelcmdline` — confirm `nowatchdog` / `watchdog_thresh` flags

**Talos-specific protective additions:**
- `machine.sysctls`: `kernel.panic=10`, `kernel.panic_on_oops=1`, `kernel.hardlockup_panic=1` — converts soft hangs into recoverable panics with a dmesg trail
- `machine.install.extraKernelArgs`: `printk.devkmsg=on`, `panic=10`, `sysrq_always_enabled=1` — prerequisites for Tier-2 netconsole on kernel 6.18
- `machine.kernel.modules` pin `iTCO_wdt` with explicit `runtime.watchdogTimer` so the ceiling is known
- Assert `.machine.time.servers` explicitly — clock skew across a shutdown window can look like paired reboots
- `controlplane.apiServer.extraArgs.audit-log-*` for apiserver-level audit of any `MachineService` proxy calls

### cluster-triage — cluster-layer angle

**Observed during review:** a 10th reboot happened during the session (~50 min before review, boot-id `590a8ec0`). 15+ pods on k8s-2 are currently in `Unknown` phase, including `kube-system/spegel-8z2tb` from **36h ago** — proving zombie pods persist across at least one reboot.

**Leader leases:** k8s-2 holds zero. kube-controller-manager → k8s-3, kube-scheduler → k8s-1, cilium-operator → k8s-3, all Flux controllers and `cilium-l2announce` → k8s-1 / k8s-3. **Leader thrash ruled out.**

**Top hypothesis: Longhorn reconcile loop, not just a one-shot shutdown deadlock.** Each reboot leaves Longhorn DS pods Unknown on k8s-2. Longhorn's node controller then marks the node down (`manager pod not running`) and disks `Ready=False`. The paired-within-minutes reboot clusters (1–3, 4–5, 7–8) and the 36h+ zombie persistence fit this pattern.

**Cluster-layer protective controls proposed:**
- **Raise `shutdownGracePeriodRequested` to 90s + `shutdownGracePeriodCriticalPods=30s`** via `machine.kubelet.extraArgs` — must-do, not suggestion. (Note: conflicts with talos-operator's "cap at 55s" — see disagreements below.)
- **Verify Longhorn chart-shipped PodDisruptionBudgets** (`longhorn-manager`, `instance-manager`, `engine-image`) are active with `minAvailable ≥ 2 of 3`.
- **Add PriorityClasses:** `system-cluster-critical` on Longhorn manager / csi-plugin / engine-image; lower priority on anything mounting Longhorn volumes. Today Prometheus/Grafana tie with Longhorn manager so shutdown order is non-deterministic.
- **Anti-affinity for kube-prometheus-stack StatefulSets** (alertmanager, prometheus, grafana) so they stop landing on k8s-2 and becoming zombies after each reboot.
- **Factor in `storage-vxlan`** (plan 0004) as an additional DaemonSet competing for the shutdown-drain window.

### observability-advisor — signals we're not using

**Biggest miss in the original plan:** it leans hard on log capture but ignores Prometheus data **already scraped by kube-prometheus-stack** (ADR 0007).

**Metrics that directly answer current questions:**
- `node_boot_time_seconds` — literal kernel boot epoch. `changes(node_boot_time_seconds[7d])` gives exact reboot count per node, historically, **right now**, without shipping any Tier 1.
- `kube_node_status_condition{condition="Ready"}` — distinguishes "real reboot" from "kubelet hiccup"
- `etcd_server_leader_changes_seen_total` / `etcd_server_has_leader` — quorum-loss events show here first
- `kubelet_graceful_shutdown_start_time_seconds` / `..._end_time_seconds` — directly measures the Apr 18 deadline-exceeded pattern without grepping kubelet.log
- `kubelet_volume_stats_*` going stale — Longhorn unmount signal

**PromQL alerts to add today** (against metrics already scraped):

```yaml
# NodeRebootStorm — would have paged on the 3-in-5-min cluster
alert: NodeRebootStorm
expr: changes(node_boot_time_seconds[6h]) >= 3
for: 5m
severity: critical

# NodeRebootedRecently — quick visibility into any reboot
alert: NodeRebootedRecently
expr: (time() - node_boot_time_seconds) < 600
for: 0m
severity: warning

# EtcdLeaderFlapping — catches control-plane impact
alert: EtcdLeaderFlapping
expr: increase(etcd_server_leader_changes_seen_total[30m]) >= 3
for: 0m
severity: critical

# NodeNotReadyRepeatedly — distinguishes flap from reboot
alert: NodeNotReadyRepeatedly
expr: changes(kube_node_status_condition{condition="Ready",status="true"}[1h]) >= 4
for: 0m
severity: warning
```

Plus a Longhorn CSI unmount-deadline alert (exact PromQL needs verification against Longhorn's actual metric names).

**What the plan is gold-plating:**
- **Tier 2 (netconsole) — defer.** Apr 18 evidence points at userspace (Longhorn/kubelet), not kernel panic. Revisit only if Tier 1 logs show machined going silent with no phase trace.
- **Tier 3 (IPMI SEL) — do once, not as infra.** One `ipmitool sel list` answers the power-event question. Standing up a scraper is gold-plating; ADR 0008 explicitly defers log pipelines of this shape.
- **Tier 4 NPD + `--event-ttl=168h` bump — trim.** Bumping event TTL inflates etcd for the whole cluster to fix one node. Keep default; ship NPD events to the same off-box collector as Tier 1 if you deploy NPD at all.
- **Loki/Vector as Tier 1 collector — no.** `nc -lku` on a stable tailnet host is enough. A Loki stack for one diagnostic is exactly what ADR 0008 said to avoid.

**Single highest-leverage action:** ship the PromQL alerts *before* any Talos config change. They light up the existing data path.

### devils-advocate — attacking every load-bearing claim

**The reboot-counting methodology is wrong.** `Creating node shutdown manager` (`pkg/kubelet/nodeshutdown/nodeshutdown_manager_linux.go`) fires every time kubelet *starts*, not every time the node *boots*. On Talos, kubelet is a supervised service — if it crashes (OOM, containerd socket break, panic, Talos `ContainerdService` restart cascade), the service runner restarts it without a reboot. **True reboot count could be 5, not 9.** Validate against `node_boot_time_seconds` from node-exporter or `uptime -s` per-boot before treating "9" as fact.

**The 50-second silent gap doesn't prove graceful reboot.** A hard power cut plus BIOS POST produces the identical signature. Absence of shutdown log ≠ presence of graceful shutdown. The 30s kubelet drain completed — that proves kubelet got 30s before *something*, not that the reboot itself was graceful.

**Apr 18 Longhorn unmount timeout is correlation, not causation.** That log line fires during *any* kubelet graceful drain where Longhorn pods are on the node. Doesn't establish Longhorn caused the reboot — only that Longhorn is messy on the way down. A reboot 20 min later is weak correlation.

**Paired-reboot pattern has a simpler explanation than "retry loop":** you, at a keyboard, power-cycling a wedged node. Three reboots in 5 min doesn't have automation's hallmark backoff. Check your own shell history, 1Password activity log, `jj op log` before inventing a supervisor.

**Stronger competing hypotheses:**
1. **MS-01 / i9-13900H thermal or VRM fault.** 13th-gen i9 HX in a 1L chassis is thermally marginal under sustained load. Over-temp triggers CPU-initiated shutdown with **zero OS log trail** — identical to the observed signature. Single-unit defect fits "only k8s-2 affected" better than a cluster-wide software bug.
2. **NVMe controller hang → kernel softlock watchdog reset.** Also explains why Longhorn unmount timed out — the block device was already wedged.
3. **BIOS `AHWSA.1.22` (Mar 2024) is two years stale.** Minisforum has shipped multiple MS-01 BIOS updates for exactly this class of spontaneous-reboot bug (ASPM, C-state, Intel ME). Check the changelog.
4. **Single DIMM decaying.** MCEs aren't logged if reboot is fast enough to lose the ring buffer — exactly the stated blind spot. Run `memtester` or swap DIMMs between k8s-2 and k8s-3 and watch where the reboots follow.

**Attacks on the five tiers:**
- **Tier 1 UDP to `nc`** — collector is a SPOF on a laptop. Worse, kernel tears down the network stack *before* userspace finishes flushing, so you miss exactly the last 200ms you care about. Log storm risk on the storage VLAN if you pick the wrong interface.
- **Tier 2 netconsole** — cmdline syntax in the original note is wrong for kernel 6.18. netconsole as a boot param requires the module to be built-in; Talos ships it as a module. Needs `modules-load` extension or `dynamic_netconsole` via configfs post-boot. Not tested on Talos v1.12.
- **Tier 3 IPMI** — **buried the cheapest answer. Should be Tier 1, not Tier 3.** SEL is free, exists, retroactively covers all 9 reboots.
- **Tier 4 NPD + `--event-ttl=168h`** — TTL bump bloats etcd and every apiserver LIST for a 3-node cluster. NPD only surfaces what the current kernel ring buffer contains — same blind spot.
- **Tier 5 grace-period bump** — if trigger is hardware (thermal/NVMe/power), longer grace just means longer dirty windows and more fsck corruption.

**Kill criterion (worth elevating):** "If two weeks of Tier 1 data don't name a cause, the answer is hardware — swap the node, don't keep instrumenting."

### simplifier — "can we cut this in half?"

**Delete from the plan:**
- Loki / Vector as Tier 1 alternatives — keep only `nc -lku`
- Tier 2 netconsole — defer until Tier 1 actually fails to answer
- **Tier 3 IPMI — delete outright**, or do a one-time ad-hoc pull. Don't stand up a BMC-on-LAN exporter for a homelab; new attack surface, new creds to rotate, new thing to babysit. (Disagrees with devils-advocate, who says IPMI should be Tier 1.)
- Tier 4 NPD DaemonSet — delete. `grep "Creating node shutdown manager" kubelet.log | wc -l` is already an exact reboot counter. `--event-ttl` bump is a flag, not a DaemonSet.
- Tier 5 items 2 and 3 — these are "investigate" / "look at", not actions. Drop.

**Minimum viable fix — three actions total:**
1. `machine.logging.destinations` UDP → `nc -lku 6050 > k8s-2.jsonl` on k8s-1 or a stable tailnet host.
2. Bump `shutdownGracePeriodRequested` to 90s / critical to 30s in Talos machine config.
3. Nothing else until the next reboot happens.

(Note: item 2 conflicts with talos-operator's "cap at 55s" warning.)

**Plan is over-thinking:**
- Conflates "capability to diagnose this class" with "diagnosing this incident." You have one pattern with one smoking-gun log line. Instrument for the incident, not for the hypothetical.
- Tier 1 variants (Loki), Tier 3 (BMC on LAN + creds), Tier 4 (NPD DaemonSet + TTL tuning) each add a thing that'll break on a Renovate Tuesday.
- Note's own warning ("instrumenting the instrumentation") contradicts the five-tier plan immediately below it. Trust the warning.
- "Open questions 3 and 4" (BMC SEL, BIOS version) are fishing, not diagnosis.

## Where the agents disagree — the most useful content

### 1. Reboot count

- **Original note:** ≥9 in the past week
- **devils-advocate:** "9" is methodologically unsound — kubelet restarts ≠ node boots; could be 5
- **observability-advisor:** `changes(node_boot_time_seconds[7d])` gives the exact answer right now, no new infra

**Resolution:** run the PromQL query before anything else. This is the tiebreaker that costs ~10 seconds.

### 2. Root cause

Three live narratives with different action implications:

| Narrative | Lead agent | What it implies for action |
|---|---|---|
| Longhorn unmount deadlock → dirty reboot cascade | cluster-triage | Grace-period bump + teardown ordering fix |
| Hardware/kernel watchdog firing silently | talos-operator | Inspect watchdog config; sysctls for `hardlockup_panic`; netconsole is essential not optional |
| Hardware — thermal, NVMe, stale BIOS | devils-advocate | BMC SEL pull, BIOS update, possibly DIMM swap — not a Talos-config fix at all |

None of the five agents confidently rejected the others' hypotheses. That's the key signal: **we don't have enough evidence yet.**

### 3. Grace period — 90s vs 55s

| Agent | Says |
|---|---|
| cluster-triage | 90s / critical 30s — must-do, current 30s demonstrably insufficient |
| simplifier | 90s is fine — minimum viable fix |
| talos-operator | **90s breaks Talos.** Sequencer shutdown deadline is ~60s; machined force-kills kubelet past that. **Cap at 55s** |
| devils-advocate | If root cause is hardware, any bump makes fsck corruption worse |

**Resolution: 55s.** talos-operator's evidence trumps the others unless someone can WebFetch Talos v1.12 docs and prove the sequencer deadline is configurable / different.

### 4. IPMI / BMC

| Agent | Says |
|---|---|
| devils-advocate | Should be **Tier 1**, not Tier 3. Cheapest answer. Retroactively covers all reboots. |
| simplifier | Delete. Never pulled SEL before, new attack surface. |
| observability-advisor | Do once, not as infra. |
| talos-operator | Silent on IPMI specifically, but flags hardware via watchdog diagnosis. |

**Resolution: one-time `ipmitool sel list` now.** Don't build infrastructure around it. Documents outcome either way.

### 5. netconsole

| Agent | Says |
|---|---|
| talos-operator | **Essential if root cause is watchdog** — UDP userspace can't catch that frame |
| simplifier / observability-advisor | Defer until Tier 1 proven insufficient |
| devils-advocate | Syntax in the original note is wrong for kernel 6.18; untested on Talos v1.12 |

**Resolution: defer, but note that this becomes Tier-1-essential if watchdog inspection (talos-operator's `get watchdogtimerconfigs`) finds a watchdog armed.**

## Synthesized action list

### Phase 1 — pre-work (no config changes, no new infra)

Do these before proposing any change. Order matters.

1. `promtool query instant <query> 'changes(node_boot_time_seconds{instance=~".*k8s.*"}[7d])'` — the real reboot count per node. Settles the devils-advocate / observability-advisor point in one shot.
2. `ipmitool -I lanplus -H <bmc-ip> -U <user> -P <pw> sel list` against the MS-01 BMC. Retroactively covers every reboot for power / thermal / watchdog events. If positive, jump straight to the hardware track.
3. `talosctl -n k8s-2 get watchdogtimerconfigs watchdogtimerstatuses kernelcmdline` and `dmesg | rg -i 'softdog|iTCO|watchdog|NMI|hardlockup|rcu_sched'`. Establishes whether a watchdog is armed at all.
4. Check Minisforum for BIOS newer than `AHWSA.1.22` (Mar 2024). Read the changelog.
5. `kubectl -n kube-system get pod cilium-envoy-* -o json | jq '.status.containerStatuses[].lastState,.restartCount'` on k8s-2 specifically — cluster-triage's hypothesis 2 (cilium-envoy as trigger).

Each of these has a clear "positive → pivots the plan" outcome. None of them apply anything.

### Phase 2 — config changes, only after Phase 1 narrows hypotheses

If Phase 1 does **not** name a hardware cause:

6. Add `machine.logging.destinations` UDP to a stable collector. **Not** a laptop — use k8s-1 itself or another always-on tailnet host. Start with `nc -lku 6050 > k8s-2.jsonl`.
7. Bump `shutdownGracePeriodRequested` to **55s** (not 90s), `shutdownGracePeriodCriticalPods=20s`. Per talos-operator's sequencer deadline warning.
8. Ship four PromQL alerts (observability-advisor's list above): `NodeRebootStorm`, `NodeRebootedRecently`, `EtcdLeaderFlapping`, `NodeNotReadyRepeatedly`. Against metrics already scraped. Land in `kubernetes/apps/observability/kube-prometheus-stack/prometheusrules/`.
9. Add `machine.sysctls`: `kernel.panic=10`, `kernel.panic_on_oops=1`, `kernel.hardlockup_panic=1`. Converts soft hangs into dmesg-producing panics.

If Phase 1 finds a watchdog armed or points at kernel-level silent resets:

10. Add netconsole via `machine.install.extraKernelArgs`. Verify 6.18 syntax against kernel.org docs; test carefully because Talos ships netconsole as a module.

### Phase 3 — structural fixes only if the reboot pattern continues

11. Longhorn PriorityClass + anti-affinity for kube-prometheus-stack (cluster-triage's cluster-layer additions).
12. Longhorn teardown ordering investigation — upstream issue search before homebrewing.

### Explicitly cut from the plan

- Loki / Vector as a Tier 1 collector (ADR 0008 says no)
- node-problem-detector DaemonSet
- `--event-ttl=168h` bump
- Tier 3 IPMI as standing infrastructure (do the one-time pull instead)
- Any Grace-period bump to 90s (use 55s)
- "Investigate supervisor" hypothesis (no evidence, no kured, no system-upgrade-controller installed)

## Kill criterion

From devils-advocate: **"If two weeks of Tier 1 data don't name a cause, the answer is hardware — swap the node, don't keep instrumenting."**

This is the strongest single line from the review. Adopting it as the exit condition prevents infinite instrumentation escalation.

## What graduates out of this folder

- PromQL alerts → `kubernetes/apps/observability/kube-prometheus-stack/prometheusrules/node-stability.yaml` (or similar)
- Talos machine-config changes → `talos/talconfig.yaml` via the normal `task talos:apply-node` flow
- Structural commitments (if any) → a new ADR (e.g. "adopt Talos logging.destinations cluster-wide")
- The rollout itself → a new `context/plans/NNNN-k8s-2-stabilization.md`

## References

- Original personal note: `~/Development/notes/ideas/k8s-2-reboot-issues.md`
- ADR 0005 (Longhorn)
- ADR 0007 (kube-prometheus-stack)
- ADR 0008 (OpenTelemetry / logs deferred — constrains Tier 1 choice)
- `context/hardware.md` (MS-01 / i9-13900H inventory; BIOS field to verify)
