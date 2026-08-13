# Live Recovery Scenarios

Use this reference for one approved shadow-only recovery test.

## Guarded command

Plan a test before any live mutation:

```sh
mise exec -- task airflow:recovery-case \
  CASE=<scenario> \
  RUN_ID=manual__<bounded-identity>
```

The plan states the exact attempt, action order, stop condition, rollback, and acceptance checks.

Execute only the reviewed plan:

```sh
mise exec -- task airflow:recovery-case:execute \
  CASE=<scenario> \
  RUN_ID=manual__<bounded-identity>
```

The execute target requires a prompt and an internal approval token. It runs
the read-only gate preflight again before it creates the Workflow Run.

Retain standard output as one JSON artifact in a new evidence directory.

## Scenarios

| Scenario | One causal action | Required result |
|---|---|---|
| `scheduler-restart` | Delete the exact active scheduler pod. | The replacement observes the same successful attempt. |
| `triggerer-restart` | Stop the driver, then replace the exact triggerer pod. | The replacement renews the same Lease before driver resume. |
| `duplicate-delivery` | Submit the same active identity through the production adapter. | One custom resource exists for the Airflow try. |
| `bounded-retry` | Reject prior output through the production retry seam. | Try two uses a distinct identity and succeeds. |
| `cancellation` | Cancel the exact active attempt through the production adapter. | Spark work stops before Lease release. |
| `expired-lease-refusal` | Expire the held Lease and submit a different identity. | Takeover fails while the prior attempt stays active. |
| `precommit-failure` | Kill the exact driver after executor creation. | Logs remain and the shadow snapshot does not change. |

The scenario watcher starts before Workflow Run creation. This prevents missed
short-lived states and late actions against the wrong workload.

## Failure handling

Stop on a failed preflight, ambiguous identity, unexpected terminal state, or timeout.

Resume a stopped driver JVM in the cleanup path. Preserve an unexpected
resource for diagnosis. Report its exact cleanup target instead of broad deletion.

Do not change the authoritative target, writer owner, credential data, or schedule.
