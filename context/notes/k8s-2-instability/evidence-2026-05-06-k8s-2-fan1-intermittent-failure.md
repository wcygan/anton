# 2026-05-06 k8s-2 fan1 intermittent failure

## Summary

Chassis fan1 on k8s-2 (the `nct6775` Super-I/O `fan1` channel) is intermittently dropping to 0 RPM. fan1 on k8s-1 / k8s-3 spin continuously; fan2 on k8s-2 is healthy.

**This is a long-running fault, not a new one.** Initial framing of this note (drafted ~10:00 CDT today) said the dropouts began 2026-05-06 02:55 CDT — that was an artifact of in-cluster Prometheus's 14h retention window. Off-cluster betty vmsingle (plan 0014) holds 24h+ of raw samples and surfaces a much longer history. Cross-checked against in-cluster Prom subqueries, fan1=0 readings on k8s-2 occur every day going back at least to **2026-04-29** (the limit of in-cluster retention; betty cannot reach further); k8s-1 and k8s-3 had **zero** zero-readings over the same window. Even when fan1 *is* spinning, k8s-2 runs ~20 % slower than the same fan on peers (1928 RPM vs 2415-2789 RPM). Downstream evidence: k8s-2's `nvme1` runs 14-26 °C hotter than the equivalent M.2 slot on either peer. Same hardware, same workload, same chassis design — the only differential is airflow.

The 2026-05-06 02:30-04:30 CDT package-throttle episode (~18,041 events) IS co-temporal with a burst of fan zeros (~448 in the 11h spanning the morning), but it isn't the *onset* of the fault — it's a more severe day in a week-plus pattern. The amplification hypothesis (NVMe-heat-coupling causing the marginal fan to stall harder) was tested 2026-05-06 ~11:45 CDT and **invalidated by the precondition check**: per-drive `pm_qos_latency_tolerance_us` on k8s-2's three NVMes is the kernel default (100,000 µs), so APST is effectively enabled despite the cluster-wide module-param of 0, and the SN7100s are already naturally entering PS3/PS4 (80 % PS3, 20 % PS4 over a 2h sample). Whatever is making nvme1 hot is not steady-state APST-disabled draw — see `## Open question` at the bottom for the remaining mechanism candidates.

The actionable conclusion is unchanged: **physical fan replacement on k8s-2** is the durable fix. Until then, the fault is intermittent and survivable; the cluster has run with it for at least 8 days.

This note is a self-contained reference for whoever picks the issue back up: hard numbers, the PromQL to re-run, the corrected hypothesis chain, and the three repair-or-replace options.

## Hard numbers

### Per-day fan1=0 history on k8s-2 (in-cluster Prom 7-day retention)

| CDT day | k8s-2 fan1=0 samples | k8s-1 fan1=0 | k8s-3 fan1=0 |
|---|---:|---:|---:|
| 2026-04-29 | 8 | 0 | 0 |
| 2026-04-30 | 12 | 0 | 0 |
| 2026-05-01 | 104 | 0 | 0 |
| 2026-05-02 | 36 | 0 | 0 |
| 2026-05-03 | 4 | 0 | 0 |
| 2026-05-04 | 26 | 0 | 0 |
| 2026-05-05 | 76 | 0 | 0 |
| 2026-05-06 (partial, ~12h) | ~448 | 0 | 0 |

Today is the most severe day in the window, but the pattern starts at retention's leading edge (the 04-29 zeros may not be the actual first occurrence — that's the limit of what we can see). Plan 0014's off-cluster betty vmsingle was load-bearing for this finding: in-cluster Prom has severe scrape gaps for k8s-2 (5 fan-RPM samples vs betty's 3400 over the same 2h window).

### Fan zero-readings over the last 12 h (capture 2026-05-06 ~14:00 CDT)

| Node | Fan | Total samples | Zero-reading samples | Healthy? |
|---|---|---:|---:|---|
| k8s-1 | fan1 | 145 | **0** | ✓ |
| k8s-1 | fan2 | 145 | 0 | ✓ |
| **k8s-2** | **fan1** | 145 | **16 (≈11 %)** | **✗ failing** |
| k8s-2 | fan2 | 145 | 0 | ✓ |
| k8s-3 | fan1 | 145 | **0** | ✓ |
| k8s-3 | fan2 | 145 | 0 | ✓ |

### Fan RPM right now

| Node | fan1 | fan2 | sum |
|---|---:|---:|---:|
| k8s-1 | 2415 | 2606 | 5021 |
| **k8s-2** | **1928** | 2250 | **4178** (-17 % vs k8s-3) |
| k8s-3 | 2789 | 2727 | 5516 |

### Fan1 trajectory excerpt around the throttle window (k8s-2)

```
02:35 CDT   2738 RPM
02:45 CDT   2678 RPM
02:55 CDT      0 RPM   ← first zero, throttle counter starts
03:05 CDT   2766 RPM
03:15 CDT      0 RPM
03:25 CDT      0 RPM
03:35 CDT      0 RPM
03:45 CDT   2347 RPM
03:55 CDT   2523 RPM
04:05 CDT      0 RPM
04:15 CDT      0 RPM
04:25 CDT   2551 RPM
04:35 CDT      0 RPM
04:45 CDT   1056 RPM   ← partial-spin restart
…
```

### Downstream airflow evidence — NVMe sensor 2 (composite)

| | nvme0 | nvme1 | nvme2 |
|---|---:|---:|---:|
| k8s-1 | 73 °C | 61 °C | 46 °C |
| **k8s-2** | **77 °C** | **87 °C** | 56 °C |
| k8s-3 | 61 °C | 73 °C | 47 °C |

k8s-2 nvme1 is 14-26 °C hotter than the same physical M.2 slot on either peer.

## How to verify the fan in the future

### Quick "is fan1 still misbehaving?" query

In Grafana Explore, in-cluster Prom, or against betty's vmsingle (`100.119.71.22:8428`):

```promql
# Zero-reading count over the last 12 h, per node, per fan
count_over_time(
  (node_hwmon_fan_rpm{chip="platform_nct6775_2592"} == 0)[12h:5m]
)
```

Expected output: 0 for healthy fans, >0 for failing ones. k8s-2 fan1 fired 16 zeros in the data above; anything ≥1 on a connected fan is suspicious.

### Live RPM compare across all 3 nodes

```promql
node_hwmon_fan_rpm{chip="platform_nct6775_2592",sensor=~"fan1|fan2"}
```

Sustained ~20 %+ delta on the same fan slot between nodes is a degraded-fan signal even without zero readings.

### Co-temporal throttle correlation (what made this the leading hypothesis)

Open Grafana → Cluster Health Glance → "Hardware Health — plan 0009" row:
- Panel **805** (Fan RPM per Node) — overlay with
- Panel **802** (CPU Throttle Events 5 m) — and
- Panel **807** (CPU Package Power per Node — RAPL)

Fan stalls visually align with throttle spikes and watts collapses. If the alignment vanishes after a fan repair / replace, the hypothesis is closed. If it persists, there's a second cause.

### Drive-side downstream signal

```promql
node_hwmon_temp_celsius{chip=~"nvme_.*",sensor="temp2"}
```

Same M.2 slot across nodes should run within ~5 °C. A persistent 10 °C+ delta on one node points at airflow on that chassis.

### Bonus: check that fan2 stays healthy

A second fan failure on k8s-2 would push thermal protection into a different regime (NVMe-side instead of CPU-side). The query above covers fan2 too — watch the zero count.

## Hypothesis chain (1 line each)

The chain below explains how a fan-bearing fault produces the package-throttle pattern. It does **not** explain *why the fault rate spiked today* — see "Open question" below.

1. fan1 stalls → airflow over VRM and M.2 slots collapses
2. EC's VRM thermal sensor (separate from CPU coretemp) crosses threshold
3. EC asserts BD_PROCHOT
4. CPU drops to base or below-base frequency *while CPU coretemp reads room temp* because the heatsink is bonded directly to the package and is well-served by even a stalled fan
5. When fan1 spins back up, throttle eases but firmware thermal hysteresis keeps freq capped for minutes-to-hours
6. Repeated stalls produce the 18,041 throttle events observed across 02:30-04:30 CDT

### Why is today's rate so much higher than yesterday's? (open question)

Today's ~448 zeros in 12h vs ~76 across all of yesterday. The fan didn't suddenly fail — but the rate stepped up sharply. The remote experiment to test "idle-mitigations rollout amplifies via NVMe thermal coupling" was invalidated at the precondition check: per-drive `pm_qos_latency_tolerance_us` on k8s-2's three NVMes is at kernel default (100,000 µs), so the cluster-wide `default_ps_max_latency_us=0` mitigation is **a no-op on already-bound drives**. The SN7100s are naturally APST-sleeping (80 % PS3 / 20 % PS4 over a 2h sample), so steady-state NVMe heat is not the amplifier. Remaining candidates:

- **Workload concentration on k8s-2.** k8s-2 hosts the observability stack and saw heavier sustained NVMe activity around the 02:30-04:30 CDT window (active workload bursts, not idle leakage). Active-state heat is real even with APST working. Burst NVMe activity could dump enough heat into the M.2 region during bursts to ramp fan duty and stall the marginal bearing.
- **Bearing degradation accelerated this week.** Per-day zero counts are not monotonic (8 → 12 → 104 → 36 → 4 → 26 → 76 → 448), but the trend over 8 days is upward. The bearing may simply be in late-stage failure.
- **Ambient temperature.** Higher room temp → higher chassis baseline → marginal bearing closer to its stall threshold. Worth checking if any thermostat / HVAC change happened.
- **Co-tenant chassis fan2 wear.** fan2 is healthy in our metrics but if it's spinning slightly slower than spec, fan1 would get a higher PWM share to compensate, stressing the marginal bearing.

7. **Silent-reboot link** — under heavier sustained load, can a fan stall cross the EC's *protection-reset* threshold rather than just PROCHOT? If yes, that's a firmware-initiated reset with zero kernel logging — exactly the silent-reboot signature plan 0013 has been chasing. The 2026-05-05 k8s-1 + k8s-3 dual silent reboot fits if both nodes had marginal fan health unobserved at the time (fan-RPM telemetry only became routinely watched after this incident).

## Repair or replace — three options

**Caveat on which physical fan**: nct6775 `fan1` is conventionally the primary header on motherboards using that Super-I/O, which on the MS-01 should be the larger CPU fan above the RAM. Without opening the chassis this isn't 100 % verified. The two fans have different specs and different SKUs (see below) — verify by reading the voltage label on the failing fan before ordering a replacement.

| Voltage variant | Sold as | Cools | Position |
|---|---|---|---|
| DC12V 0.40A 4-pin Molex PicoBlade | "Fan One" / CPU Fan | CPU heatsink | Top, above the RAM, removed first to access heatsink |
| DC5V 0.40A 4-pin Molex PicoBlade | "Fan Two" / NVMe Fan | M.2 slots | Bottom |

(Some listings invert these voltages — Linda Parts lists Fan One as DC5V; Amazon lists it as DC12V. Verify physically before ordering.)

### 1. Repair — clean and re-seat (free, ~15 min)

If the bearing has dust contamination or a wire is intermittent, a clean and re-seat fixes it. Worth attempting first because you have to open the chassis anyway to identify which physical fan is failing. Standard procedure on the MS-01: remove the top cover, the CPU fan sits above the RAM and is removed first. While in there, repaste the CPU — Minisforum's stock thermal compound is widely reported as poor (Servethehome thread).

### 2. Like-for-like OEM replacement (~$15-25, ~30 min)

Drop-in replacement parts are commercially available:
- Amazon: [Replacement MS-01 CPU Fan, Fan One, DC12V 0.40A 4-pin](https://www.amazon.com/Replacement-Minisforum-MS-01-AU-MS-01-S1390-MS-01-S1260/dp/B0FD8BVQXN)
- Linda Parts (cdrtd.com): [Fan One DC5V](https://www.cdrtd.com/products/replacement-mini-pc-cpu-fan-for-minisforum-ms-01-ms-01-s1390-dc5v-0-40a-4pin-fan1-new.html) / [Fan Two DC12V](https://www.cdrtd.com/products/replacement-mini-pc-cpu-fan-for-minisforum-ms-01-ms-01-au-ms-01-s1390-ms-01-s1260-dc12v-0-40a-4pin-fan-two.html)
- eBay: multiple [Fan One](https://www.ebay.com/itm/235964738158) and [Fan Two](https://www.ebay.com/itm/236014094976) listings

Restoration to baseline. No airflow geometry change. Best choice if the goal is "stop the throttle events" without scope creep.

### 3. Noctua mod (~$25-40 + 3D-printed bracket, longer)

Community-preferred upgrade per the [Level1Techs MS-01 cooling mod thread](https://forum.level1techs.com/t/minisforum-ms-01-cooling-mod-idea/226255): Noctua NF-A12x15 12V 4-pin with a USB-to-12V adapter, mounted via the [3D-printed sandwich mod](https://www.thingiverse.com/thing:6660321) or a [140mm fan cover replacement bottom plate](https://www.printables.com/model/980783-minisforum-ms-01-140mm-fan-cover). Better bearings, longer rated life, much quieter. Changes the chassis airflow profile, so save it for a planned upgrade window — not under-incident.

### Recommendation

Open the chassis, **try option 1 first** (you're already there), photograph any visible damage, read the voltage off the fan label. Fall back to **option 2** if the bearing is shot — that's the right risk posture during plan 0013, where the goal is "stop the throttle events" not "improve airflow profile." Save **option 3** for a separate planned-upgrade window.

The dropouts are intermittent rather than steady-state, so this can wait long enough to ship a replacement (1-2 weeks). Do not drag it out beyond that — each stall is one closer to the EC protection-reset edge.

## References

- Plan: [`../plans/0013-cluster-wide-silent-reboot-localization.md`](../../plans/0013-cluster-wide-silent-reboot-localization.md) — log entry "k8s-2 fan1 intermittent failure" (2026-05-06)
- Related plan: [`../plans/0015-ms-01-firmware-power-stability-profile.md`](../../plans/0015-ms-01-firmware-power-stability-profile.md) — Phase 1 BIOS profile, should land in the same physical visit
- Sibling note: [`evidence-2026-05-06-k8s-2-turbo-lockout.md`](evidence-2026-05-06-k8s-2-turbo-lockout.md) — broader pre/post evidence for the reboot discriminator (now downgraded; fan replacement is the higher-priority action)
- Earlier 2026-05-06 entries: `incidents/2026-05-06-k8s-2-thermal-throttle.md`, `postmortems/2026-05-06-k8s-2-thermal-throttle.md`
- Servethehome MS-01 heating discussion: <https://forums.servethehome.com/index.php?threads/minisforum-ms-01-heating-problem.43519/page-3=>
- Level1Techs MS-01 cooling mod thread (Noctua, 5V-to-12V adapter, mounting): <https://forum.level1techs.com/t/minisforum-ms-01-cooling-mod-idea/226255>
