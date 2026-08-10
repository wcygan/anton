---
status: Done
opened: 2026-08-09
closed: 2026-08-10
affects: all
intent: concrete-need
related-adrs: [0027, 0030, 0031]
review-by: null
---

# 0021 — Deepen cluster operation contracts

> Convert the architecture review's repeated Flux, logging, storage, and target-resolution rules into small executable modules with explicit adapters and durable validation.

## Goal

Anton has one enforceable contract for Flux application shape and dependency readiness, one verified Kubernetes logging contract, one shared SeaweedFS bucket-provisioning implementation, and one cluster target/preflight interface. Operator docs and agent skills consume those interfaces instead of carrying divergent copies. The Iceberg acceptance workflow remains behind ADR 0031's retain-or-remove review gate.

## Acceptance criteria

- [x] Codex and Claude hooks use one Flux application-contract module that enforces app shape plus ADR 0027 consumer and provider rules against repository fixtures and the current tree.
- [x] ADR 0030 logging semantics are machine-checked across OTel, Loki, and operator-query adapters, with retention and query guidance agreeing with the accepted decision.
- [x] Ordinary S3 and S3 Tables bucket provisioning share one implementation while retaining explicit workload intent, collision refusal, security posture, and bounded evidence.
- [x] Cluster target resolution and mutation preflight have one executable interface consumed by scripts, task wrappers, hooks, docs, and skills without committed tailnet details.
- [x] Documentation records validation evidence, rollback boundaries, and the ADR 0031 defer/retain gate; every changed surface passes its narrow repository validation.

## Tasks

### Phase 1: Establish executable policy modules

- [x] Extract the Flux application contract from the two hook implementations.
- [x] Add fixtures for Helm/raw app shape, CRD-consumer dependencies, and provider readiness.
- [x] Wire thin Codex and Claude adapters to the shared module.
- [x] Add a repository-wide validation entry point and run it against the current tree.

### Phase 2: Concentrate the logging contract

- [x] Encode ADR 0030 vocabulary, indexed labels, retention, and query invariants once.
- [x] Align Loki retention with the accepted 6-hour debug/trace decision.
- [x] Add representative record fixtures and validate OTel, Loki, and query adapters.
- [x] Replace copied operational facts in the runbook and query skill with contract pointers.

### Phase 3: Deepen storage provisioning

- [x] Extract shared SeaweedFS provisioning behavior with explicit ordinary-S3 and S3-Tables adapters.
- [x] Migrate Harbor, Loki, and lakehouse callers without broadening credential access.
- [x] Add focused idempotency, collision, security, and evidence validation.

### Phase 4: Deepen target and preflight resolution

- [x] Extract live Tailscale discovery and committed fallback inventory behind one target interface.
- [x] Reuse the interface from Talos health, task wrappers, and context guards.
- [x] Align docs and skills on port-forward and debug-resource mutation classification.
- [x] Add redacted evidence fixtures and fail-closed mutation tests.

### Phase 5: Document and close conditional work

- [x] Record the architecture alignment and exact validation commands in operator documentation.
- [x] Keep Iceberg acceptance-module work deferred until ADR 0031's 2026-08-20 retain-or-remove review.
- [x] Run the completion audit against all report candidates and close this plan only when every accepted criterion is evidenced.

## Log

- 2026-08-09: Plan opened from the architecture review; implementation prioritizes the three strong seams, treats shared bucket provisioning as worth exploring through fixtures, and preserves ADR 0031's review gate.
- 2026-08-09: Added shared Flux, logging, storage-provisioning, and target/preflight contracts; migrated their hook, task, manifest, skill, and runbook adapters; and recorded rollout and rollback boundaries in `context/notes/cluster-operation-contracts.md`.
- 2026-08-09: Completion audit passed `mise exec -- task contracts:validate` (four validators, 47 Flux apps, 23 tests), 10 Codex policy-hook tests, Python compilation, shell syntax, `git diff --check`, skill validation, and strict Kustomize/kubeconform checks for the storage and Loki apps. Docusaurus compiled client and server but the global build remains blocked by five pre-existing links outside the changed pages; TypeScript remains blocked by the existing TS6 `baseUrl` deprecation. No live reconcile or cluster mutation was performed.
- 2026-08-10: Pre-commit documentation reconciliation aligned the storage and Loki rollout, moved active Talos guidance onto the shared resolver, wrapped Task commands with Mise, restored Helm/raw app-authoring parity, separated repository work from Git and live-rollout authority, and expanded the four validators; `mise exec -- task contracts:validate` passed with 47 Flux apps and 26 tests before the plan was closed.

## References

- Reconciled operational contract: `context/notes/cluster-operation-contracts.md`
- Flux dependency decision: `context/adrs/0027-platform-dependson-rule.md`
- Logging decision: `context/adrs/0030-adopt-loki-for-kubernetes-logs.md`
- Iceberg learning decision: `context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md`
- Existing Flux rollout: `context/plans/0016-harden-flux-cold-start-ordering.md`
- Existing lakehouse rollout: `context/plans/0020-implement-seaweedfs-iceberg-log-lakehouse.md`
