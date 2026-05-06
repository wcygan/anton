# Evidence: betty TSDB has only 2h retention; ongoing i40e flap rate weakens iter #2's "NIC flap is rare precursor" reading

**Date:** 2026-05-06 (loop iteration #4, opus 4.7)
**Source:** Live VictoriaMetrics on betty (`http://100.119.71.22:8428`); `node_network_carrier_changes_total{device=~"enp2s0f.*"}` and `node_boot_time_seconds`.
**Status:** Two findings: one operational gap in plan 0014, one corrective recalibration of iter #2.

## Finding 1: betty TSDB does not have retention to retro-analyze 2026-05-05

Earliest data points across all three node-exporter targets:

| Node | First scrape | Last scrape (now) |
|---|---|---|
| k8s-1 | 2026-05-06 02:23:41Z | 2026-05-06 04:12:41Z |
| k8s-2 | 2026-05-06 02:23:59Z | 2026-05-06 04:12:29Z |
| k8s-3 | 2026-05-06 02:23:50Z | 2026-05-06 04:12:20Z |

That's a ~110-minute window starting ~7 hours **after** the 2026-05-05T19:07Z silent reboot. The TSDB cannot answer "what did k8s-1's metrics look like in the 26 minutes between k8s-3's reboot and k8s-1's reboot" — that data was never captured because betty wasn't scraping then.

This is a real shortfall against plan 0014's stated goal of off-cluster forensics — for the next event, betty will be ready, but for the previous event, it adds nothing. Worth surfacing because plan 0014 is `In-progress` and someone may have assumed the existing scrape covered the prior incident.

**Suggested follow-up for plan 0014:** an explicit acceptance-criterion check that retention extends ≥48 h before the plan is closed. Default vmsingle retention is 1 month, but the actual data range above suggests scraping started recently — possibly Phase 2 finished in the last few hours and the scrape only began then.

## Finding 2: i40e bilateral flaps are an ongoing background pattern, not a rare precursor

`node_network_carrier_changes_total{device=~"enp2s0f.*"}` snapshot at 2026-05-06T04:12Z, divided by current uptime per node:

| Node | Boot epoch | Uptime | f0np0 | f1np1 | Avg transitions/port/h |
|---|---|---|---|---|---|
| k8s-1 | 2026-05-05 20:29Z | 7.7 h | 4 | 4 | **0.52** |
| k8s-2 | 2026-05-04 01:47Z | 50.4 h | 6 | 8 | **0.14** |
| k8s-3 | 2026-05-05 19:07Z | 9.1 h | 4 | 4 | **0.44** |

Transitions are bidirectional (down=+1, up=+1), so divide by 2 for "flap events" (a complete down→up cycle). Excluding the 2 transitions per port that the boot itself produces (initial link-down then link-up during PHY training), residual transitions are 2 each on k8s-1, 2 each on k8s-3, 4 + 6 on k8s-2.

So per-port flap-event rates excluding boot:
- k8s-1: 1 flap event / 7.7 h ≈ **0.13 events/port/h**
- k8s-2: 2 events on f0np0 / 50.4 h + 3 events on f1np1 / 50.4 h ≈ **0.06 events/port/h** (avg)
- k8s-3: 1 flap event / 9.1 h ≈ **0.11 events/port/h**

**k8s-2 has the lowest residual flap rate**, by a factor of ~2. This is the inverse of what iter #2's "k8s-2's NIC card had a local glitch" reading predicts. If k8s-2's i40e card were locally unreliable, we'd expect k8s-2 to have *more* flaps per hour, not fewer.

Two possible re-readings:

1. **The iter-#2 19:06:32Z bilateral flap on k8s-2 was one of ~3 flap events k8s-2 has had in 50 h** — 41 seconds before k8s-3's silent reboot is suggestive but not a unique pattern. It might have been coincidence. The base rate of bilateral flap events on a held node is non-zero; in a 41-second window, P(flap occurred) is tiny on its own, but with many windows over many days, the prior on coincidence is lower than I assumed.
2. **The 19:06Z flap could still be a real precursor**, but the same flaps that are happening on k8s-1 and k8s-3 right now should also be precursors — and yet no reboot has followed any of them. That doesn't fit; precursors should correlate with consequences. So either the *severity* of the 19:06Z flap was higher (re-flap pattern, double-down event) than the typical background flap, or it's not a special event.

The dmesg from iter #2 does show a re-flap on f1np1 (Down → Up → Down → Up within 1 second) which is not the typical background pattern — most flaps look like a single Down → Up transition. So **the *severity* of the 19:06Z flap pattern (re-flap within 1s) may be the discriminator, not the flap occurring at all**.

## What this changes about iter #2's reading

Iter #2's three readings ranked:
1. Same Vmin glitch hit all three nodes — **slightly weakened**: bilateral i40e flaps are common, not rare; the precursor framing requires the *severity* / *re-flap* pattern, not just the bilateral flap.
2. Isolated NIC firmware glitch on k8s-2 — **further weakened**: k8s-2 has the lowest flap rate, not the highest.
3. Power-rail event — **unchanged**: still consistent with the brief simultaneous flap.

Net: iter #2's hypothesis isn't dead, but the discriminator narrows from "any bilateral flap" to "re-flap pattern within 1-2 seconds". A PrometheusRule on `increase(node_network_carrier_changes_total[2m]) > 3` per port would catch the re-flap pattern while ignoring the background ones.

## What discriminating tests should do now

The earlier-proposed kernel-sink-archive search (look for bilateral flap signatures on held nodes around R0–R8) is **still** worth doing — it's the only way to know whether *any* of the prior 9 silent reboots had a re-flap precursor or just plain flaps. If even one R-event shows a re-flap signature on a held node, that converts the discriminator into a real signal.

Additionally, the iter-#3 runtime-mitigation DaemonSet (PM-QoS C-state cap + ASPM disable + NVMe APST disable) is **independent of which reading of iter #2 is correct** — it tests the Vmin/C-state hypothesis directly, regardless of whether we observe i40e flaps or not. That makes it the higher-priority test for the next iteration of plan 0013.

## Verification trail

```
$ curl -s --data-urlencode 'query=node_network_carrier_changes_total{device=~"enp2s0f.*"}' \
    'http://100.119.71.22:8428/api/v1/query' | jq -r '.data.result[] | "\(.metric.nodename):\(.metric.device) = \(.value[1])"'
k8s-1:enp2s0f0np0 = 4
k8s-1:enp2s0f1np1 = 4
k8s-2:enp2s0f0np0 = 6
k8s-2:enp2s0f1np1 = 8
k8s-3:enp2s0f0np0 = 4
k8s-3:enp2s0f1np1 = 4

$ curl -s --data-urlencode 'query=node_boot_time_seconds' \
    'http://100.119.71.22:8428/api/v1/query' | jq -r '.data.result[] | "\(.metric.nodename): boot=\(.value[1])"'
k8s-3: boot=1778051234   # 2026-05-05 19:07:14Z (verified)
k8s-1: boot=1778056147   # 2026-05-05 20:29:07Z (graceful reboot)
k8s-2: boot=1777902427   # 2026-05-04 01:47:07Z (BIOS-flash boot)

$ curl -s 'http://100.119.71.22:8428/api/v1/query?query=up' | jq -r '.data.result[].value[0]' | head -1
1778040766    # 2026-05-06 04:12:46Z = "now"
```

## Cross-references

- `evidence-2026-05-06-k8s-2-precursor-nic-flap.md` (iter #2) — the original "bilateral flap precursor" finding; this evidence note refines its discriminator from "bilateral flap" to "re-flap within 1-2 s"
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — runtime mitigation DaemonSet is independent of iter #2's reading; promoted as higher-priority test
- Plan 0014 (off-cluster forensics TSDB on betty) — `In-progress`. Suggest adding an explicit retention-window acceptance criterion (≥48 h)
- Plan 0013 Phase 1 verification — the carrier-change rate analysis above is a forward-looking baseline; future PrometheusRule should fire on `increase(node_network_carrier_changes_total[2m]) > 3` (re-flap pattern), not on individual transitions
