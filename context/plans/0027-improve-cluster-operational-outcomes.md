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
- [x] Execute the approved bounded Harbor maintenance/digest-pull exercise and record its failed acceptance and recovery in `context/notes/2026-10-19-harbor-maintenance.md`.
- [x] Resolve the stale-address and proxy-drain findings with approved controlled recovery checks; retain the earlier failed exercise and the node-loss continuity limit.
- [x] Restore stable Seaweed volume DNS with explicit wildcard bind and verify the real operator rollout, master locations, PVCs and unchanged S3 processes (PR 513).
- [x] Deliver the proxy-aware two-phase drain command with bounded identity/eviction semantics and behavioral fixtures (PR 514).
- [x] Complete legacy S3 cache migration, prove fresh authenticated bytes after a controlled volume replacement, and complete the proxy-host drain/runtime recovery/cleanup gate; see `context/notes/2026-10-19-harbor-recovery-hardening.md`.
- [x] Observe post-drain Flux recovery from transient ESO validation-webhook failures; all 86 reconcilers passed after the evidence source revision, with concurrent reconcile requests separately attributed.
- [x] Verify normal workload recovery after the approved private verifier mirror repair and ESO sync; desired replicas, enforcing admission and user-facing HTTP/TLS checks passed.
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

- 2026-10-19: Operator approved temporary private fixture/robot/Secret, three cold-pull Jobs and k8s-2 drain with emptyDir deletion. Baseline and post-recovery pulls passed with four OCI blob hashes; during-maintenance pull hit its 120-second deadline while S3 retained an old volume address. Drain exited 1 on proxy connection reset; uncordoned at 20:45:28 UTC. Harbor, CNPG, SeaweedFS, all 18 Longhorn volumes/36 replicas and Flux recovered; all test resources were removed and source image retained. One private workload remains below desired replicas due to invalid image-verifier auth; separately approved source repair is blocked by local 1Password session setup. See `context/notes/2026-10-19-harbor-maintenance.md`; no continuity pass is claimed.

- 2026-10-19: Local operator authentication unblocked the separately approved verifier repair. The malformed mirror failed registry authentication; the original app credential read the pinned manifest successfully and was restored into its 1Password mirror (version 2 to 3), leaving the original Secret/permissions unchanged. ESO refresh at 21:08:36 UTC updated the verifier Secret. Standard HTTP/TLS checks passed; normal ReplicaSet retry remains pending after repeated prior denials. Private source identities and repair evidence remain private.

- 2026-10-19: Normal controller retry restored the affected private workload to two Ready replicas with zero restarts after the mirror/ESO repair; the image rule remains enforcing and original pull Secret metadata is unchanged. At 21:21 UTC all three nodes were Ready/schedulable, all 72 Deployments/StatefulSets and 86 reconcilers were Ready, and all 18 Longhorn volumes/36 replicas were healthy/running. Both standard HTTP/TLS checks passed again and a fresh browser loaded the storefront. The maintenance exercise remains failed because its during-pull and complete drain acceptance were unmet.

- 2026-10-19: Operator requested S3 stale-address and drain-proxy fixes. Five GPT-6 Luna high-effort agents used separate worktrees for reproduction, volume identity, drain tooling, operational acceptance and independent review. Preserved concurrent main and merged PR 513 (`c040a67c`) and PR 514 (`20842500`); 466 tests (one skipped), the real upstream stream comparison, exact operator generator checks and production docs build passed. Normal Flux rolled all three volumes to stable peer DNS with unchanged PVCs and S3 Pod UIDs. Legacy per-process/per-volume caches then caused two fixture-copy timeouts; backend terminal failures and partial natural invalidations were retained. Both gateways still had other old-address entries. Kept live acceptance open pending an explicit active-Loki writer exception for serial gateway refresh and exact k8s-3/emptyDir drain approval. Cleaned that failed fixture after both backend attempts became terminal.

- 2026-10-19: Operator approved the remaining live plan. Concurrent GitOps S3 metrics/probe changes replaced the exact old gateway UIDs first, so root's guarded Eviction stopped before submission; preserved those changes through `1bf42c06`. A new private fixture and fresh clients verified four OCI blobs/9,200,696 bytes before and after an exact volume-1 replacement, with its PVC/stable DNS retained and the same service-eligible S3 gateway pair inferred from readiness/rollout timestamps during the verification request. The proxy-aware k8s-3 drain exited zero at 22:14:19 UTC, honoring PDB refusals, and uncordon was verified at 22:14:21. The final fresh pull passed at 22:16:37; at 22:16:38 all workloads, 18 Longhorn volumes and 36 replicas were ready/healthy/running. Exact Jobs/Pods, Secret, robot and fixture cleanup was verified at 22:17:51 with the source retained. Combined validation passed 477 tests (one skipped) and the production docs build. Fifteen Flux conditions still reflected the earlier brief ESO webhook absence; its serving endpoint had recovered. Normal reconciliation remains an explicit follow-through gate. See the recovery-hardening note for chronology, limits and rollback.

- 2026-10-19: Published the independently reviewed evidence in PR 515 (`50b547be`, merged 22:24:47 UTC). Flux fetched the exact revision through its normal source path at 22:24:50; at 22:25:36 all 86 reconcilers, 72 workloads, three schedulable nodes, 18 Longhorn volumes and 36 replicas passed. Read-only filer metadata/master lookup ties both fixture layers to IDs 22/23 on the replaced volume-1 server. Retained the readiness-based routing inference and separately attributed concurrent reconcile requests at 22:20:32/22:21:19. Root submitted no force reconcile. The requested S3/proxy maintenance gates are complete; the other operational gates in this plan remain open.

| Increment | Delivered benefit and evidence | Rollback |
| --- | --- | --- |
| Registry resources, PR 505 | Four generated containers now have effective reservations; actual two-replica Deployment matches the chart render. | Revert merge `e56410d6` through GitOps and observe Deployment resources/readiness. |
| Nginx continuity, PR 506 | Nginx replacement served after eviction, but the during-maintenance cold pull timed out and the drain exited with a proxy transport error; the post-recovery cold pull passed. See the maintenance record. | Revert merge `77454e05` through GitOps and observe nginx/Harbor readiness. |
| Internal boundary, PR 507 | Reviewed client/port matrix and inactive policy with rejection tests; no live isolation gain claimed. | Leave staged; any future activation is reverted by its own activation commit. |
| Rebuild audit, PR 508 | Rerunnable source check: 18 source-presence PASS, 8 informational stages, 7 unknowns, expected exit 2. | Revert merge `1c019ed8`; no live state was changed by the audit. |
| Cooling evidence, PR 509 | Bounded passive collector and exact hardware/WAL handoffs; fan/tach fault and historical log completeness remain unresolved. | Revert merge `b2d76f4b`; hardware and WAL operations have separate recovery plans. |
| Private release timing | Outcome-aware CLI and 133 passing private tests; actual push/scan times remain unknown and polling stays unchanged. | Revert its private merge; no application or polling configuration changed. |

## References

- Recovery hardening: `context/notes/2026-10-19-harbor-recovery-hardening.md`.

- Recovery constraint: `context/notes/2026-10-13-disable-longhorn-backups.md`.
- Cooling evidence: `context/notes/k8s-2-instability/evidence-2026-05-06-k8s-2-fan1-intermittent-failure.md`.
- Existing convergence measurement: `context/plans/0022-establish-cluster-metric-experiments.md`.
- Private repository: existing release acceptance observer and October 12–13 rollout records; private identities and evidence remain private.
