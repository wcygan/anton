# Cooling and Loki WAL incident follow-up

## Historical evidence snapshot — 2026-10-19

The cooling findings below remain an operator follow-up. The Loki investigation
in Plan 0026 completed, and Plan 0028 subsequently retired its custom runtime.
Stock Loki now uses a fresh WAL on the original PVC; see the
[current logging runbook](../../query-kubernetes-logs/references/loki-pipeline.md) and
[stock cutover evidence](https://github.com/wcygan/anton/blob/628e15ba1c9b40b2731240dcfb3a282f013319cc/context/notes/2026-10-20-plan0028-stock-cutover.md).
The old startup counter and diagnostic targets below describe the recorded
incident, not the current process or a pending replay authorization.

As of 2026-10-19 19:34 UTC, the collector returned 2,881 of 2,881 expected
30-second Prometheus range-query evaluation points for each fan1 node series
over 24 hours. These points are not raw scrape counts: Prometheus lookback can
fill evaluations from an earlier scrape, so this does not establish scrape
continuity.
`k8s-2` fan1 was zero in 64.07% of that window; the peer nodes had zero
zero-RPM samples. The separate live alert had already been critical since
October 13, with a 0.65 fraction over its last ten-minute window. The same
channel had an intermittent zero-RPM pattern in the May 6 evidence note. Treat
this as an unresolved cooling fault or tach-signal fault; telemetry alone
cannot tell which. The physical fan, connector, chassis airflow, tach readout,
and sensor mapping need inspection.

At the same observation time, NVMe `temp2` had all expected range-query
evaluation points returned over 24 hours; this does not establish raw scrape
continuity.
Its maximum was 98.85 C on `k8s-2` chip `nvme_nvme2` and 88.85 C on `nvme_nvme0`;
peer `nvme_nvme2` maxima were 73.85 C. The meaning of `temp2`, the mapping to a
physical sensor, and its hardware limit have not been verified. Record this as
a temperature asymmetry; do not call it a threshold breach or a combined
health score. Package-throttle counters had all expected range-query evaluation
points returned and a zero delta on all three nodes over the same window. The
full JSON report is retained locally
at `.private/cluster-improvements/cooling-wal-evidence-20261019.json`.

Loki started at 2026-10-19 18:54:47.582 UTC and logged WAL segment recovery
errors during the 18:54:40–18:56:00 UTC startup interval. The
`loki_ingester_wal_corruptions_total{type="segment"}` counter had value 1 and
did not increase during the observed 15-minute window;
replay was inactive at the observation point, and disk-full and checkpoint
failure indicators remained zero. The canary recorded 504 log records emitted,
502 confirmed, and two fresh records still pending for less than six seconds.
These are record counts, not HTTP status codes; no HTTP 504/502 failure was
established. Historical data loss remains unknown.

The startup logs and counters are evidence to preserve. Do not restart Loki or
clear/recreate the WAL to clear its lifetime alert. The durable follow-up and
approval gates are in `https://github.com/wcygan/anton/blob/628e15ba1c9b40b2731240dcfb3a282f013319cc/context/plans/0026-investigate-loki-wal-replay.md`. Its
offline checks are `scripts/verify-log-durability.py` and
`scripts/verify-log-loss-alerts.py`.

## Rerunnable cooling evidence

Run from the canonical checkout so target preflight and the kubeconfig use the
expected operator context. This performs Prometheus service-proxy GETs only;
it does not create a port-forward or workload:

```sh
cd /Users/wcygan/Development/anton
mise exec -- python3 scripts/collect-cooling-wal-evidence.py --window 24
```

Keep the JSON output with the incident record. It includes observation time,
range, expected and observed query evaluation points, fan zero fraction, NVMe `temp2`
series, and package-throttle counter deltas. Missing series, gaps, or failed
queries remain `no_data`, partial evaluation coverage, or errors; they are not
reported as healthy zero values. Query evaluation points do not prove raw scrape
continuity. The collector explicitly carries the unknown sensor map
and limit into every report. The WAL fields link to the existing follow-up
tools and preserve the historical loss count as `unknown`.

## Operator handoffs

**Physical cooling inspection — target within one day.** Owner: cluster
operator with physical access. Target: the `k8s-2` fan1 channel, its connector
and tach path, plus chassis airflow and the NVMe sensor mapping. Preconditions:
save one fresh collector report and confirm the node identity; record current
hardware/cabling before touching it. Stop immediately if the node is unstable,
if a second node becomes affected, or if inspection would require cluster
maintenance outside the operator's approved window. Acceptance: a full
post-inspection 24-hour collector window contains no fan1 zero-RPM evaluation
points and no package-throttle increments. This is a diagnostic target, not a
claim that the current node has no throttling. The NVMe reading remains unclassified until
the `temp2` channel and drive's supported limit are identified. If a fan or
cable is replaced and the channel worsens or cooling degrades, restore the
recorded original part/cabling and stop for reassessment. Hardware work needs
the operator's explicit maintenance decision; no remote software restart is a
substitute.

**Historical Loki WAL diagnosis — completed under Plan 0026.** Owner:
observability/storage operator. The 18:54:40–18:56:00 UTC startup interval is
the evidence window. Capture and retain any surviving authoritative source and
Loki logs, `loki_ingester_wal_corruptions_total` samples, replay-active,
checkpoint and disk indicators, plus the canary request/response IDs and
timestamps without recording request bodies or credentials. The old replay
segments may already have rotated away; if so, mark the original error as not
reproducible from current data. Do not infer loss from the generic recovery
error, counter name, or canary record counts. Retained snapshots and encrypted
evidence remain historical recovery material. For a new incident, establish a
new window and exact targets through the current logging runbook; do not rerun
the old capture packet. No production restart or WAL repair is authorized by
this handoff.
