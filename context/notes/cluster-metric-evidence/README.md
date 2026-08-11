# Cluster metric evidence

These files retain sanitized read-only observations for plan 0022.

Each record omits Kubernetes context names, endpoints, addresses, condition
messages, and Secret data. The matching observer verifies the Anton target
before the first cluster read.

Treat each record as one immutable observation. Do not replace it with a later
sample. Add a new timestamped file instead.

## Evidence index

| Record | Scope | Limit |
|---|---|---|
| `2026-08-11T011440Z-m2.json` | One fixed-time critical revision observation | It is incomplete and does not measure convergence time. |
| `2026-08-11T005110Z-m4.json` | One fixed-time platform continuity observation | OOM is `no_data`, thresholds are unapproved, and coverage is partial. |
| `2026-08-11T013927Z-m4-restart-attribution.json` | M4-E4 restart attribution evidence | It does not replace the original restart rate. Overall M4 remains partial. |

M1 and M3 experiment records remain in
`context/notes/cluster-metric-contracts.md`. They do not have separate JSON
evidence files. No approved M2 durable ledger exists.

Use `context/plans/0022-establish-cluster-metric-experiments.md` for the next
bounded step. Use `context/notes/cluster-metric-contracts.md` for metric
definitions, experiment records, guards, and authority boundaries.

These records describe past observations. Run the target-bound observers again
when the task requires current cluster state and has read-only authority.
