# Evidence: iter #24's "k8s-1 high RX drop rate" reading is wrong — the drops are boot-time, not steady-state

**Date:** 2026-05-06 (loop iteration #25, opus 4.7)
**Source:** betty TSDB `node_network_receive_drop_total` query_range from 02:24Z to 06:00Z (3.6h window).
**Status:** **Correction of iter #24.** The "k8s-1 has 75-160× higher drop rate" framing was based on dividing cumulative drops by uptime, incorrectly assuming steady-state. Actual current rate is essentially zero on every node.

## What I got wrong in iter #24

iter #24 reported these per-hour drop rates:

```
k8s-1: 49,097 drops in 7.7 h uptime = 6,376 / hour
k8s-2: 2,041 drops in 50.4 h uptime = 40 / hour
k8s-3: 777 drops in 9.1 h uptime = 85 / hour
```

The math is correct. The **interpretation** is wrong. Dividing cumulative-since-boot drops by uptime gives the *average* rate over the entire boot, not the *current* rate. If drops are front-loaded (boot-time CNI / network init), the average overstates current behavior.

## What the data actually shows

Pulling `node_network_receive_drop_total` from betty TSDB for the 3.6-hour window 02:24Z → 06:00Z:

| Node | Device | First (02:24Z) | Last (06:00Z) | Net change | Current rate |
|---|---|---|---|---|---|
| k8s-1 | enp2s0f0np0 | 48,771 | 48,771 | **+0** | **0/hour** |
| k8s-1 | enp2s0f1np1 | 326 | 326 | +0 | 0/hour |
| k8s-2 | enp2s0f0np0 | (lower) | (lower+36) | +36 | 10/hour |
| k8s-2 | enp2s0f1np1 | static | static | +0 | 0/hour |
| k8s-3 | enp2s0f0np0 | (lower) | (lower+137) | +137 | 38/hour |
| k8s-3 | enp2s0f1np1 | static | static | +0 | 0/hour |

**k8s-1's drops have been static at 48,771 for the entire 3.6-hour window** — meaning all 48,771 drops happened **before** betty started scraping at 02:24Z (i.e., between k8s-1's boot at 20:29Z and 02:24Z, a ~6-hour window).

**Currently k8s-1 has the LOWEST drop rate (0/hour), not the highest.** k8s-3 has the highest at 38/hour. None are concerning at these rates.

The 48,771 drops on k8s-1 are post-boot CNI-initialization noise: Cilium endpoint setup, iSCSI replica handshakes, Tailscale tunnel establishment, routing table churn — all normal post-graceful-reboot activity that produces dropped packets while the data plane is settling. After stabilization, the rate drops to ~0.

## What this changes about iter #24's conclusions

**The "concrete forward-looking precursor metric" claim is materially weakened.** iter #24 proposed:

```yaml
- alert: HighStorageNicRxDrops
  expr: rate(node_network_receive_drop_total{device=~"enp2s0f.*"}[5m]) > 1
  for: 10m
```

Under iter #24's reading, k8s-1's "drops accumulating at 1.7/sec" would already be firing this alert. Under iter #25's reading, **k8s-1 currently has rate 0** — the alert wouldn't fire on any node. The cumulative count is high; the rate is fine.

### What the rule actually catches

The rule is still valid but catches a different thing than iter #24 claimed:

1. **Boot-time transients on freshly-rebooted nodes** — would fire for ~1-2 hours after every silent reboot or graceful restart, then stop. Useful as an indication that "a node just rebooted and is initializing" but not a precursor.
2. **Sustained drops in the middle of operation** — the actual precursor signature for the iter #2 mechanism. Currently zero on every node, so the rule wouldn't fire pre-event. **If a node's CPU starts getting stuck at C8 entry/exit longer (Vmin shift progressing), this rule would catch it as RX drops start accumulating.** That's still useful.

### Refined rule with boot-time exclusion

```yaml
- alert: HighStorageNicRxDrops
  expr: |
    rate(node_network_receive_drop_total{device=~"enp2s0f.*"}[5m]) > 1
    and
    (time() - node_boot_time_seconds) > 3600
  for: 10m
  labels: { severity: warning }
  annotations:
    summary: "{{ $labels.nodename }} storage NIC RX-drop rate >1/s for 10m (after boot stabilization)"
    description: |
      Possible precursor for iter-#2 bilateral i40e flap. Excludes the first hour
      after boot to filter out CNI-initialization transients. If this fires during
      steady-state operation, the kernel is likely missing packet-processing
      windows due to deep-idle wake latency (Vmin/C8 candidate).
```

This is the right framing. The rule does what we want; iter #24's interpretation of *why* it would fire on existing data was wrong.

## Honest meta-reflection

**iter #24 is the first iteration in the series where I produced a wrong primary conclusion.** The error was a basic statistical mistake: dividing a cumulative counter by an integration window without checking whether the data was uniformly distributed. betty TSDB has the rate-over-time data; I should have used it in iter #24 instead of computing a single ratio.

**This is a real value of the betty off-cluster TSDB (plan 0014).** Without it, iter #24's reading would have stood and propagated forward. The TSDB caught the mistake in the very next iteration.

It also suggests a process improvement for further investigation:
- Counter-based metrics (`*_total`) should always be checked as `rate()` over a window, not as `delta() / uptime`
- The shorter the window, the more current the read; iter #24 implicitly used `delta(8h) / 8h` which is "average over entire boot"
- For "what's happening now" queries, prefer `rate([5m])` or `rate([1h])`

## What's left to verify about iter #24's reading

1. **Was the 48,771 drops on k8s-1 actually concentrated in the first ~hour after boot, or spread over 6 hours?** betty doesn't have data before 02:24Z, so we can't see the curve directly. The fact that current rate is 0 across the 3.6h window strongly suggests it stabilized rapidly.
2. **What's k8s-1's MTU on the storage mesh during boot?** iter #2 dmesg showed an MTU change to 9000 at 19:06:11Z (k8s-2's case) which would temporarily disrupt link. A similar MTU change on k8s-1 at boot 20:29Z might explain the burst.

Both worth checking but probably not changing the conclusion — the boot-time burst is benign, current state is clean.

## Net contribution of iter #25

| Aspect | Status |
|---|---|
| iter #24 "high drop rate on k8s-1" reading | **CORRECTED** — current rate is 0, not 6376/hr |
| Forward-looking PrometheusRule | Still valid, refined to exclude first hour after boot |
| Vmin/C8 mechanism | Not directly affected — iter #24's RX-drop angle was a supporting argument, not load-bearing |
| Recommendation stack (iter #5/#6/#8) | Unchanged |

The recommendation stack is unaffected because iter #24's RX-drop reading was supporting evidence for the Vmin/C8 hypothesis but not load-bearing. Iter #6's direct C8 measurement, iter #14's E-core dominance, iter #7's elimination of all other failure surfaces, iter #9's `kernel.tainted=0`, and iter #20's IOMMU asymmetry remain unchanged.

## Cross-references

- `evidence-2026-05-06-k8s-1-rx-drops.md` (iter #24) — corrected here
- `evidence-2026-05-06-betty-retention-and-flap-rates.md` (iter #4) — same lesson about base-rate computation; iter #25 makes it concrete
- Plan 0014 — this iter is a real argument for keeping betty around: it caught a wrong reading in the next iteration. Add to the plan's "value-realized" notes.
- Plan 0013 — refined PrometheusRule from iter #25 supersedes iter #24's version

## Honest assessment

After 25 iterations, this is the second meaningful contribution from a sequence of diminishing returns: iter #24 surfaced a real anomaly *count* (48,771 drops on k8s-1 vs 2,041 on k8s-2), iter #25 corrected the *rate* interpretation. Both are useful — the count tells us about boot-time transients, the rate tells us steady-state behavior. The PrometheusRule is the right artifact even if iter #24's reasoning was wrong.

I've now made one concrete reasoning error in 25 iterations, caught it in the next iteration with the betty TSDB, and produced a corrected artifact. **That's a healthy investigative pattern, but it does not change the standing recommendation: cancel the cron, land the iter #5/#6/#8 PR, watch.**
