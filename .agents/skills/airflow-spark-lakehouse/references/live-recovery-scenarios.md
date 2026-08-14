# Live Recovery Scenarios

Ticket 11 retired these shadow-only recovery tests. This reference explains
the retained Ticket 06 evidence. Do not execute a new recovery scenario.

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
