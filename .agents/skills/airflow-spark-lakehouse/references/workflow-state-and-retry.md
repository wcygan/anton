# Workflow State and Retry

Use this reference for one Workflow Run and its Spark Attempts.

## Identity contract

One Workflow Run is one Airflow DAG run. One Spark Attempt is one
`SparkApplication` for one Airflow task attempt.

The identity hash uses these fields with NUL separators:

```text
dag_id + run_id + task_id + map_index
```

The try number selects the attempt suffix. The same try must find the same
custom resource. A new try must use a new custom resource.

Logical date is optional metadata. It does not participate in identity.
Manual runs can have no logical date.

## Retired manual trigger

Ticket 11 removed the shadow DAG and its live trigger targets. Use retained
evidence for completed shadow runs. Do not recreate a shadow Workflow Run.

## Historical source-window contract

The Loki-source operator selects its window end in this order:

1. `dag_run.conf.source_window_end`
2. `data_interval_end`
3. `logical_date`
4. `execution_date`
5. `dag_run.run_after`

Use `run_after` as the stable fallback inside one manual run. Use an explicit
`source_window_end` to replay the same window through a new run ID.

An exact-window replay must retain these values:

- Window start and end.
- Source-window hash.
- Raw object key and checksum.
- Entry count and byte count.
- Final normalized and hourly results.

A new run ID changes Spark Attempt identity. It does not permit a different
source window when the operator requested an exact replay.

## Observation contract

Watch `SparkApplication` resources through a name-filtered list operation.
The Kubernetes watch API cannot stream a single-object GET operation.

Use `metadata.name=<attempt-name>` as the field selector. Keep each watch
timeout bounded. Re-read the resource after watch timeout or reconnect.

Use `stateTransitionHistory` for terminal outcome. `ResourceReleased` alone
does not define success or failure.

## Retry decisions

| Observed state | Required action |
|---|---|
| Active exact attempt | Reattach and renew its Lease. |
| Succeeded with valid output | Continue to read-only Trino validation. |
| Failed before commit | Retain diagnostics, then create the next try. |
| Prior output independently valid | Reuse it only through the committed validator. |
| Application absent with no commit proof | Fail closed and collect evidence. |
| Lease expired while prior work remains active | Refuse takeover. |
| Commit or ownership state ambiguous | Stop and request operator review. |

Spark restart policy remains `Never`. Airflow owns bounded retries.

## Execution API ambiguity

Airflow worker requests can time out after the API server commits their effect.
A client timeout does not prove that the server stopped.

Airflow 3.2.2 rendered-field writes are not idempotent. A retry can conflict
with the first request after a late commit.

Anton uses these worker controls:

```text
execution_api_retries = 1
execution_api_timeout = 30.0
```

Before a manual Flight Recorder run, verify the effective scheduler values:

```sh
mise exec -- kubectl -n airflow exec <exact-scheduler-pod> -c scheduler -- \
  airflow config get-value workers execution_api_retries
mise exec -- kubectl -n airflow exec <exact-scheduler-pod> -c scheduler -- \
  airflow config get-value workers execution_api_timeout
```

Require `1` and `30.0`. Review both controls after an Airflow upgrade changes
the rendered-field endpoint or its idempotency contract.

## Cancellation order

1. Record the exact Spark Attempt and current Lease holder.
2. Collect bounded application, event, and driver-tail diagnostics.
3. Delete only the approved custom resource.
4. Verify that its driver and executor work stopped.
5. Release the Lease after stop verification.

Cancellation, deletion, and Lease changes are live mutations. Present the
exact command, timeout, stop condition, and rollback before approval.

## Completion evidence

Retain the full Airflow identity, attempt name, state transitions, Lease
events, source-window receipt, terminal state, and retry decision.

Completion requires one consistent identity chain from Airflow through Spark,
Trino, Loki, and History Server.

Collect the current evidence by exact identity:

```sh
mise exec -- task airflow:attempt-evidence \
  RUN_ID=manual__<bounded-identity> \
  TRY_NUMBER=1
```

Use `airflow:attempt-evidence:complete` with an accepted ledger when retained
Trino and gate artifacts must also pass.
