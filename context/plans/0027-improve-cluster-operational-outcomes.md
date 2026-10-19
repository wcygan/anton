---
status: In-progress
opened: 2026-10-19
closed: null
affects: all
intent: concrete-need
related-adrs: []
review-by: null
---

# 0027 — Improve cluster operational outcomes

> Deliver independently verifiable improvements to registry continuity, resource intent, release timing, rebuildability and internal isolation, with explicit live and hardware gates.

## Goal

Make Anton safer and more predictable without expanding its infrastructure footprint. Each increment has a measurable benefit, a reproducible check, an owner and rollback. Repository candidates are integrated independently against current main; operational claims require real downstream evidence. Preserve the October 13 disposable-data policy and unrelated work.

## Acceptance criteria

- [x] Each of the five opportunities has a concrete repository deliverable, measured or explicitly unknown baseline, acceptance check, tradeoff and rollback.
- [x] Every implemented increment passes its focused checks and the combined public/private contract checks applicable to its surface.
- [x] Integrated commits preserve concurrent main changes and have an independent review disposition.
- [x] Cooling and Loki replay findings have bounded evidence-preserving operator handoffs; unperformed live tests and hardware repairs remain explicit.
- [x] Publication, rollout, client-visible verification and remaining authority gates are recorded accurately; repository checks alone are not completion evidence for operational outcomes.

## Tasks

### Isolated implementation

- [x] Harbor continuity: map critical dependencies; prepare nginx continuity change and pinned-chart behavior checks.
- [x] Resource contracts: repair ignored Harbor registry resource values and verify rendered registry/registryctl reservations.
- [x] Release timing (private repository): extend existing release evidence with stage timing and bounded polling experiment gates.
- [x] Rebuildability: verify bootstrap/image/secret inputs and produce a rerunnable prerequisite audit and recovery order.
- [x] Internal isolation: inventory required clients and prepare one dependency's policy candidate with positive/negative acceptance and rollback.
- [x] Incident evidence: preserve cooling/WAL evidence and make hardware/log-completeness follow-ups concrete without a live mutation.

### Integration and verification

- [x] Review each commit; integrate in dependency order and run the narrow check after each unit.
- [x] Reconcile current origin/main without resetting other checkouts or overwriting their work.
- [x] Run combined required checks and independent review; fix findings before delivery.
- [x] Publish concrete review artifacts within authority and record remaining operational gates.

### Operational gates

- [ ] Inspect physical cooling/tach wiring on k8s-2 with the operator; retain the before/after 24-hour evidence in `docs/docs/runbooks/cooling-wal-followup.md`.
- [ ] Approve and perform the bounded Harbor maintenance/digest-pull exercise; normal rollout readiness alone does not establish node-loss continuity.
- [ ] Complete independent bootstrap-image origin/cache-seeding evidence and approve an isolated rebuild drill; source audit remains incomplete.
- [ ] Gather ten comparable ordinary release samples with explicit timestamp coverage before any polling experiment; the current private tool distinguishes its proxy from push timing.
- [ ] Approve the staged PostgreSQL policy's activation and exact positive/negative client checks, or retain it inactive; no isolation gain is claimed before enforcement.
- [ ] Continue existing Loki WAL plan 0026; do not infer historical log loss or repair the production WAL from these telemetry counters.

## Log

- 2026-10-19: Opened after read-only discovery and operator request for GPT-6 Luna high-effort agents in isolated worktrees. Public base `dc04d509`; private base `fead45b1`. Original public checkout remains dirty and untouched. Root owns integration and this record; worker branches own individual artifacts. Shared delegate contract is retained in the integration checkout's ignored `.private/cluster-improvements/SKILL.md`.
- 2026-10-19: Separate Before Serializing Shared State selected one checkout and branch per worker; only root may publish or integrate. Sequence Work into Verifiable Units requires a passing focused check per commit and renewed combined validation. Build the Lever requires reusable checks for operational claims, not another unmeasured dashboard.
- 2026-10-19: Baseline contract validation passed 431 tests (one skipped). Concurrent main advanced to `b703ffd3`; merged it without resetting any checkout and reran the affected logging contract and 12 tests successfully. Main independently allocated plan 0026 for Loki WAL replay; renumbered this unpublished execution record to 0027 and directed the evidence worker to reuse that investigation rather than duplicate it.
- 2026-10-19: Six GPT-6 Luna high-effort workers delivered isolated commits; an additional Luna high-effort reviewer inspected the actual source, rendered artifacts and CLI behavior. Corrected stage-metadata PASS inflation, chart-source binding, rejected timing states, chronology/cohort readiness, canary record-count interpretation and evaluation-point versus scrape coverage before publication.
- 2026-10-19: Each source increment was cherry-picked and its focused check rerun before the next. The combined public contract suite passed 449 tests (one skipped), both actual Harbor chart checks passed, and the Docusaurus production build passed after repairing two source-record links. Private validation passed 133 tests and the eight-application contract; private details remain in its repository.
- 2026-10-19: Merged independently reviewed public PRs [505](https://github.com/wcygan/anton/pull/505) (resource intent), [507](https://github.com/wcygan/anton/pull/507) (inactive PostgreSQL candidate), [508](https://github.com/wcygan/anton/pull/508) (rebuild audit), and [509](https://github.com/wcygan/anton/pull/509) (cooling evidence), plus the private release-timing PR. All applicable public GitHub checks passed; the private change passed local validation and has no configured remote checks. Harbor continuity PR [506](https://github.com/wcygan/anton/pull/506) waits for the first runtime increment's stable acceptance.
- 2026-10-19: At 19:41:21 UTC normal Flux reconciliation completed Harbor HelmRelease generation 10, release v22. Registry Deployment generation 17 became 2/2 ready with effective 100m/256Mi registry and 10m/64Mi registryctl requests. The dependency gate cleared naturally; no force reconcile, restart or other direct cluster mutation was used.
- 2026-10-19: After a second stable resource read, merged continuity PR [506](https://github.com/wcygan/anton/pull/506) as `77454e05`. Normal Flux upgraded Harbor to v23. Nginx Deployment generation 5 has two ready endpoints on distinct nodes and a PDB with minAvailable 1 and one allowed disruption; registry reservations remain effective. Actual node maintenance, uncached authenticated pulls and end-to-end failover remain unperformed operator gates.
- 2026-10-19: Preserved concurrent main's retained-WAL-snapshot-class change `777caa4d` and reran all 449 public tests (one skipped), both pinned-chart checks and the production docs build successfully. Corrected operator handoff commands against actual namespaced Flux objects and documented the activation test change required for the inactive policy. All six implementation PRs are merged; this plan remains In-progress for the explicit operational gates above, rather than claiming the five longer-term outcomes are proven.

| Increment | Delivered benefit and evidence | Rollback |
| --- | --- | --- |
| Registry resources, PR 505 | Four generated containers now have effective reservations; actual two-replica Deployment matches the chart render. | Revert merge `e56410d6` through GitOps and observe Deployment resources/readiness. |
| Nginx continuity, PR 506 | Two serving nginx endpoints and a one-available PDB; planned-maintenance survival remains untested. | Revert merge `77454e05` through GitOps and observe nginx/Harbor readiness. |
| Internal boundary, PR 507 | Reviewed client/port matrix and inactive policy with rejection tests; no live isolation gain claimed. | Leave staged; any future activation is reverted by its own activation commit. |
| Rebuild audit, PR 508 | Rerunnable source check: 18 source-presence PASS, 8 informational stages, 7 unknowns, expected exit 2. | Revert merge `1c019ed8`; no live state was changed by the audit. |
| Cooling evidence, PR 509 | Bounded passive collector and exact hardware/WAL handoffs; fan/tach fault and historical log completeness remain unresolved. | Revert merge `b2d76f4b`; hardware and WAL operations have separate recovery plans. |
| Private release timing | Outcome-aware CLI and 133 passing private tests; actual push/scan times remain unknown and polling stays unchanged. | Revert its private merge; no application or polling configuration changed. |

## References

- Recovery constraint: `context/notes/2026-10-13-disable-longhorn-backups.md`.
- Cooling evidence: `context/notes/k8s-2-instability/evidence-2026-05-06-k8s-2-fan1-intermittent-failure.md`.
- Existing convergence measurement: `context/plans/0022-establish-cluster-metric-experiments.md`.
- Private repository: existing release acceptance observer and October 12–13 rollout records; private identities and evidence remain private.
