# Flight Recorder Acceptance

Use this reference for one manual Flight Recorder run and its exact replay.

## Authority

The Workflow Run, `kubectl exec`, and port-forward are separate live mutations.
Obtain approval for each used mutation. Keep repository work separate.

Record the revisions, digests, run ID, window, evidence path, and cleanup owner.

## Image preflight

Check the worker repository and tag in the Airflow HelmRelease. Then check the
effective scheduler configuration. Both values must name the same digest.

```sh
mise exec -- kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
  airflow config get-value kubernetes_executor worker_container_repository
mise exec -- kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
  airflow config get-value kubernetes_executor worker_container_tag
```

The evidence command also checks the completed task pod. It compares the pod
request and runtime `imageID` with the committed Airflow digest.

## Initial run

Retain the exact non-Flight Recorder snapshots before the Workflow Run:

```sh
mise exec -- task trino:flight-recorder-namespace-isolation \
  > .scratch/flight-recorder/evidence/<identity>-namespace-before.json
```

Create one new manual run after approval. Use one explicit UTC window end.

```sh
mise exec -- kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
  airflow dags trigger airflow_flight_recorder \
  --run-id 'manual__flight_recorder_<identity>' \
  --conf '{"source_window_end":"<UTC timestamp>"}'
```

Wait for Airflow success and this Spark sequence:

```text
RunningHealthy -> Succeeded -> ResourceReleased
```

Collect one bounded result after approved Trino execution:

```sh
mise exec -- task airflow:flight-recorder-evidence \
  RUN_ID='manual__flight_recorder_<identity>' \
  NAMESPACE_BASELINE=.scratch/flight-recorder/evidence/<identity>-namespace-before.json \
  > .scratch/flight-recorder/evidence/<identity>.json
```

Acceptance requires:

- The task pod uses the committed Airflow digest.
- Spark and Airflow receipts use one attempt identity.
- The authoritative Lease has no holder after completion.
- Spark reached `Succeeded` before `ResourceReleased`.
- The source receipt matches the retained query, window, key, count, bytes, and checksum.
- Loki contains Airflow and Spark evidence without error samples.
- History Server returns the completed application within 20 results.
- Trino counts, contracts, snapshots, and the run receipt agree.
- The `logs` namespace has no snapshot commit during the Spark Attempt.

## Exact replay

Create a new run ID with the same source-window end. Do not change the query.
Collect replay evidence against the first result:

```sh
mise exec -- task airflow:flight-recorder-replay-evidence \
  RUN_ID='manual__flight_recorder_<replay-identity>' \
  BASELINE=.scratch/flight-recorder/evidence/<identity>.json \
  > .scratch/flight-recorder/evidence/<replay-identity>.json
```

The baseline result must report `status: complete`. Replay acceptance requires
the same source receipt, except for the Attempt name. Trino rows and snapshot
metadata must not change. The receipt count and final event count must not increase.

## Cleanup and report

Retain both JSON results. Report the window, checksum, attempts, counts, and
snapshots. Stop when both results report `status: complete`.
