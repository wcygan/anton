# 07 — Pass the five-run shadow gate

**What to build:** Demonstrate repeated, compatible, read-only validated operation on Anton before any authoritative writer transfer.

**Blocked by:** 06 — Prove failure and recovery paths.

**Status:** resolved

- [x] Five consecutive scheduled or equivalent Workflow Runs pass against the shadow target.
- [x] Every run uses the expected Spark image digest and Apache `SparkApplication` control plane.
- [x] Every run passes Trino schema, count, partition, snapshot, location, and time-travel checks.
- [x] Trino write-denial tests pass for both authoritative and shadow catalogs.
- [x] Authoritative table metadata and data remain unchanged during all shadow runs.
- [x] Kubernetes 1.36 acceptance covers Airflow task pods, custom-resource observation, and Spark workloads.
- [x] Runtime identity, classpath, S3FileIO, S3A, Loki, and History Server evidence remains complete.
- [x] Any unexplained failure resets the consecutive-run count.
- [x] A Spark 4.1.3 blocker follows the documented repair and compatibility ladder before fallback.
- [x] No fallback changes the Apache `SparkApplication` architecture.
- [x] Cutover remains blocked unless every mandatory criterion has retained evidence.

## Comments

- 2026-08-12: Added a read-only shadow-gate ledger validator.
- The validator requires five consecutive passed runs.
- Any failed or invalid run resets the suffix.
- The validator checks Spark image identity and the `SparkApplication` API.
- The validator checks Trino results, write denial, Kubernetes 1.36, runtime evidence, and retained artifacts.
- Fallback evidence must include the compatibility ladder and preserve the `SparkApplication` boundary.
- Live Workflow Runs and cluster evidence remain pending operator approval.
- 2026-08-13: Five consecutive manual Workflow Runs succeeded after the Apache rollout repair.
- Runs `manual__shadow_gate_pass_1_20260813T044600Z` through `manual__shadow_gate_pass_5_20260813T045100Z` used Spark digest `sha256:f76b38d07d0c0b1784e962073c918176f116359f7e3c8e82e0e0efbb939563e7`.
- All five Apache `SparkApplication` histories reached `Succeeded` before `ResourceReleased`.
- The full gate remains blocked because Trino lacks separate read-only authoritative and shadow storage identities.
- Creating those credentials requires separate credential-work approval. Ticket 08 remains blocked.
- 2026-08-13: Created separate authoritative and shadow reader identities in 1Password and SeaweedFS.
- Trino catalogs `iceberg` and `iceberg_shadow` now use separate read-only credentials and `READ_ONLY` connector mode.
- Both catalogs passed `5 / 5 / 5`, schema, partition, location, snapshot, time-travel, and write-denial checks.
- The authoritative snapshot remained unchanged throughout the five-run window.
- Retained evidence passed `scripts/validate-airflow-shadow-gate.py` with five consecutive passes and no errors.
- Evidence is stored under `.scratch/airflow-spark-lakehouse/evidence/shadow-gate-20260813/`.
- A follow-up run proved clean Spark shutdown after adding `deletecollection` to the workload Role.
- 2026-08-13 review: The first ledger mixed pre-catalog Spark runs with post-catalog Trino checks.
- The retained summaries were insufficient as source evidence. The gate remains open until a fixed candidate passes five complete per-run checks.
- The rejected ledger now contains a rejection notice and cannot support cutover.
- The corrected Airflow watcher waits for the Apache operator's initial status without accepting other ambiguous states.
- The exposed shadow credential was rotated before the accepted sequence.
- Runs `manual__rotated_gate_1_20260813T140000Z` through `manual__rotated_gate_5_20260813T140300Z` passed consecutively.
- Each retained artifact contains its command, observation time, and source result.
- The accepted ledger is `.scratch/airflow-spark-lakehouse/evidence/shadow-gate-20260813-rotated/ledger.json`.
