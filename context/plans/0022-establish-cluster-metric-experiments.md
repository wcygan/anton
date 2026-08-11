---
status: In-progress
opened: 2026-08-10
closed: null
affects: all
intent: concrete-need
related-adrs: [0027, 0030]
review-by: null
---

# 0022 — Establish cluster metric experiments

> Define four shared cluster metrics, record authoritative baselines, and run one guarded experiment for each metric.

## Goal

Anton uses separate, repeatable contracts for GitOps escapes, revision convergence, service recovery, and platform stability. Each contract has an owner, evidence source, baseline, target, tolerance, guard, and rollback boundary. Each metric has one completed bounded experiment. No experiment creates unmanaged cluster drift.

## Acceptance criteria

- [ ] Each metric uses the version 1 contract and has an authoritative baseline.
- [x] The known Flux substitution escape has a regression check that fails before the repair and passes after it.
- [x] Revision convergence, recovery, and platform stability retain their separate measures and evidence sources.
- [x] Each metric has one completed experiment with an evidence record, guard result, and decision.
- [ ] Accepted changes pass repository and live verification without unmanaged drift.

## Tasks

### Phase 1: Define measurement contracts

- [x] Define the common metric contract and its version rule.
- [x] Define separate contracts for all four metrics.
- [x] Add read-only observers for convergence and platform stability.
- [x] Record an evidence source, sample count, target, tolerance, guard, and rollback boundary for every metric.

### Phase 2: Record safe baselines

- [x] Record the 2026-08-10 repository and Flux snapshot.
- [ ] Capture the accepted-revision GitOps failure baseline.
- [x] Capture a convergence sample for the critical resource inventory.
- [x] Run one read-only recovery tabletop from an existing incident.
- [x] Capture a 15-day platform restart, OOM, and saturation baseline.

### Phase 3: Repair the known preflight escape

- [x] Obtain repository-change authority for the Flux substitution repair.
- [x] Add a narrow fixture for the `bucket` strict-substitution failure.
- [x] Extend validation until the fixture passes and valid literal shell variables remain accepted.
- [x] Run `mise exec -- task contracts:validate`.
- [ ] Obtain separate Flux reconciliation authority before live verification.

### Phase 4: Run bounded experiments

- [x] Propose one single-lever experiment for each metric.
- [ ] Obtain separate authority for each experiment.
- [x] Record baseline, tolerance, guards, checkpoint, commands, and stop conditions before each experiment.
- [x] Run one causal change at a time and retain rejected or inconclusive evidence.
- [ ] Observe each accepted change through its known recurrence window.

### Phase 5: Close safely

- [ ] Re-measure every metric with its original aggregation and tolerance.
- [ ] Verify accepted changes from committed intent to user-visible outcome.
- [ ] Record residual risk, recurrence windows, and operator-only follow-up.
- [ ] Invoke `planner close 0022 done "<closing note>"` only after every acceptance criterion has evidence.

## Next hill-climb entry point

Start with the metric contract and retained evidence index. Treat retained
observations as historical evidence, not current cluster health.

Run `mise exec -- task contracts:validate` before another experiment. Preserve
the original aggregation, target, tolerance, guards, and rollback boundary.

Use these metric-specific boundaries:

- M1: Do not add another repository-only lifecycle model. First commit and
  reconcile the current repair with separate authority. A later lifecycle
  needs a trusted observer, target resolver, and approved durable store.
- M2: Select an approved absolute ledger path, owner, and fixed schedule. The
  parent must use mode `0700`. The ledger and lock must use mode `0600`.
  Obtain separate read-only cluster and local-write authority before collection.
- M3: Add only a new closed incident or a separately approved drill. Keep each
  scenario family separate. Do not replace missing outcomes with synthetic data.
- M4: Keep the overall result partial. The guarded restart-reason estimator
  does not replace an authoritative OOM event counter. API and storage
  thresholds remain unapproved. Do not convert missing data to zero.

The next live step requires new authority. Repository validation does not grant
commit, push, Flux reconciliation, cluster mutation, or live verification authority.

## Log

- 2026-08-10: Plan opened from the cluster metric experiments handoff. The strict Flux substitution escape shows that repository validation can miss deterministic GitOps failures. Metric contracts precede optimization experiments.
- 2026-08-10: M1-E1 kept the uncommitted repository candidate. The strict failure count changed from 1 at `50f05694` to 0. Five focused tests, the storage validator, and the aggregate guard passed. Live authority was not granted.
- 2026-08-10: Read-only M2, M3, and M4 evidence recorded one failed convergence sample, one sequential-reboot tabletop sample, and one incomplete 15-day platform observation. Historical convergence, recovery, and telemetry gaps remain explicit.
- 2026-08-10: Added read-only M2 and M4 observers. M2 reported 17 current-ready resources and one current failure. M4 kept OOM as no-data and kept coverage partial. The observers are measurement prerequisites, not metric wins.
- 2026-08-10: M2-E1 kept expanded synthetic fixture coverage from 5 of 18 to 18 of 18 inventory items. It improves observer coverage only.
- 2026-08-10: M3-E2 kept a read-only Flux control-plane tabletop. The reliable detection-to-stable duration was 43 minutes and 51 seconds, plus or minus 1 minute.
- 2026-08-10: M4-E1 kept one-hour historical API latency sampling. It removed one query error but can miss between-hour peaks and is not an M4 metric win.
- 2026-08-11: G1-E1 kept verified Anton target binding for both live observers. Coverage changed from zero of two to two of two observers. The final full guard passed 111 tests.
- 2026-08-11: G1-E1 rejected its first self-referential target check after Terra proved a fake operator-style kubeconfig passed. The replacement uses independent Tailscale, explicit override, or committed fallback identity and retains the regression.
- 2026-08-11: M1-E2 kept generic strict postBuild validation. Generated ConfigMap coverage changed from one of two roots to two of two roots.
- 2026-08-11: M3-E3 rejected the k8s-2 thermal incident as a recovery sample because no critical service loss occurred.
- 2026-08-11: M4-E2 retained an inconclusive recurrence result. The PM-QoS canary removed throttling for ten minutes, but the later source chronology conflicts and cannot prove durability.
- 2026-08-11: M4-E3 kept required-source continuity evidence. Four of four jobs passed at one-minute resolution, and M4 coverage reasons changed from two to one.
- 2026-08-11: M2-E2 kept the pure revision-record lifecycle and fixed rolling-30 aggregator. A 30-record golden window produced p50 15 seconds, p95 29 seconds, maximum 30 seconds, and zero incomplete records. It retained immutable initial incomplete evidence and rejected forged complete starts, direct complete starts, source changes, tied source events, unsupported classifications, and window overrides. The focused M2 suite passed 28 tests. The final contract guard passed 125 tests. This is not a live baseline.
- 2026-08-11: M4-E4 kept time-local restart node attribution. The raw and node estimates differed by 0.000000000000001, below the 0.000001 tolerance. Observer instrumentation reasons changed from one to zero. Overall M4 coverage stays partial because OOM and threshold gaps remain. Nineteen focused tests and 128 contract tests passed.
- 2026-08-11: M2-E3 kept the atomic prospective ledger after one rejected candidate. Coverage changed from zero of 25 to 25 of 25 persistence scenarios. The observer rejects source and scope overrides. The ledger requires a private `0700` parent, preserves fractional timestamps, rounds duration bounds up, rejects time overrides, serializes concurrent updates, and reports post-replacement sync uncertainty. The aggregate guard passed 153 tests. No durable path was selected, and no live record was created.
- 2026-08-11: M1-E3 kept full-render strict substitution for every postBuild root after rejecting a slow candidate and a contract-incomplete candidate. Coverage changed from two of 37 to 37 of 37 roots. The final validator verifies Flux type, non-null postBuild configuration, sibling source path, and one restricted command environment. Four bounded workers keep results ordered. Fourteen focused tests and 163 contract tests passed in a 6.164-second aggregate guard. This improves a driver and does not establish the rolling outcome.
- 2026-08-11: M1-E4 rejected and rolled back a pure accepted-revision model. Independent review proved that forged terminal mappings and reduced target sets could create an eligible rolling rate. Multi-target cause selection was also ambiguous. A trusted observer, target resolver, and approved durable store are required before another lifecycle attempt.
- 2026-08-11: Final post-rollback verification passed 163 tests. Three external wall-time samples were 6.45, 6.21, and 6.33 seconds, so the M1-E3 seven-second keep threshold passed in all final samples. The hill-climbing run stopped after M1-E4 at the operator's request.
- 2026-08-11: M4-E5 kept a guarded one-minute OOM restart-reason estimator. It conserved 17.130267 restart increments with zero residual and attributed two OOM restart increments by node and component. The authoritative OOM event counter remains unavailable, so overall M4 coverage stays partial.

## References

- Metric contracts: `context/notes/cluster-metric-contracts.md`
- Retained evidence: `context/notes/cluster-metric-evidence/README.md`
- Flux dependency decision: `context/adrs/0027-platform-dependson-rule.md`
- Logging decision: `context/adrs/0030-adopt-loki-for-kubernetes-logs.md`
- Completed contract initiative: `context/plans/0021-deepen-cluster-operation-contracts.md`
- Flux cold-start initiative: `context/plans/0016-harden-flux-cold-start-ordering.md`
- Reboot investigation: `context/plans/0013-cluster-wide-silent-reboot-localization.md`
- Operation contracts: `context/notes/cluster-operation-contracts.md`
- Contract gate: `Taskfile.yaml`
- Storage validator: `scripts/validate-storage-contract.py`
- Flux validator: `scripts/validate-flux-contract.py`
- Cluster dashboard: `kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`
- Reboot postmortem: `context/postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`
