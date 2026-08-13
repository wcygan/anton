# Shadow-Gate Evidence

Use this reference before accepting or replacing a five-run evidence ledger.

## Gate invariant

Five consecutive complete runs must pass against one candidate. A failed or
invalid run resets the accepted suffix.

The current ledger schema is version 2. Retained run artifacts and credential
receipts use their own version 1 envelopes.

One candidate contains:

- One source revision.
- One Airflow image digest.
- One Spark image digest.
- One Spark API version.
- One credential owner, version, and epoch.
- One nonsecret credential rotation receipt with source output.

Every run must name the same credential epoch. The receipt must identify the
first ledger run. Its observed rotation time must precede that run.

## Required per-run evidence

Each passed run must retain these JSON artifacts:

- Workflow Run.
- SparkApplication.
- Trino validation.
- Authoritative state before and after.
- Runtime identity and classpath.
- Kubernetes version and object checks.
- Loki markers after container exit.
- History Server application identity.

Each artifact needs an observation time, source command, retained result, and
details object. An assertion without source output fails the gate.

Host commands that start `kubectl`, `flux`, `docker`, or `task` must use
`mise exec --`. In-container Airflow or Trino command descriptions stay valid.
Prefixes, paths, subshells, and environment assignments do not bypass this rule.

## Trino boundary

Both catalogs must use read-only connector mode and separate read-only storage
credentials. Retain write-denial results for authoritative and shadow catalogs.

Retain schema, counts, partitions, snapshots, locations, and time travel.
Retain authoritative state before and after every shadow run.

## Validation

Run the read-only live preflight before creating a candidate run:

```sh
mise exec -- task airflow:gate-preflight
```

The preflight checks repository convergence, immutable images, Flux readiness,
read-only Trino access, evidence services, active Spark work, and the shadow Lease.

It reports queued Airflow-run visibility as a limitation. The command does not
read credentials or use pod execution to bypass that boundary.

```sh
mise exec -- task airflow:shadow-gate \
  LEDGER=.scratch/airflow-spark-lakehouse/evidence/shadow-gate-20260813-rotated/ledger.json
```

Acceptance requires `eligible=true`, five consecutive passes, and no errors.
The validator also binds the candidate Spark digest to the current DAG source.

## Evidence replacement

Mark a rejected evidence set as rejected. Preserve its historical content.
Create a new directory for a new candidate or credential epoch.

Start the count again after these changes:

- Candidate revision or image digest.
- Credential rotation.
- Mandatory validation behavior.
- Unexplained workflow failure.
- Mixed precondition and postcondition evidence.

Repository validation does not prove a live run. Retained summaries do not
replace raw bounded results.

## Cutover handoff

Cutover remains blocked until the accepted ledger and all failure-path tests
pass. Read `cutover-and-cleanup.md` before any writer ownership change.
