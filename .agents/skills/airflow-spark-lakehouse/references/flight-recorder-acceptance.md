# Flight Recorder Acceptance

Use this reference for one manual Flight Recorder run and its exact replay.

## Authority

The Workflow Run, `kubectl exec`, and port-forward are separate live mutations.
Obtain approval for each used mutation. Keep repository work separate.

Record the revisions, digests, run ID, window, evidence path, and cleanup owner.

## Dependent image release

The Airflow image embeds the Spark runtime digest. Publish the images in this
dependency order:

1. Build and publish the Spark image for `linux/amd64`.
2. Record the verified remote Spark digest.
3. Update the Spark digest in the Airflow source and Spark History manifest.
4. Build the Airflow image after the Spark digest update.
5. Inspect the Airflow image and record its embedded Spark digest.
6. Require the embedded digest to equal the verified remote Spark digest.
7. Publish the Airflow image and record its verified remote digest.
8. Update the Airflow HelmRelease and foundation contract.
9. Run the focused image contracts and `mise exec -- task contracts:validate`.

Stop before merge when a source pin, embedded pin, or remote digest differs.
Never build both images before the remote Spark digest exists.

## Image preflight

Check the worker repository and tag in the Airflow HelmRelease. Then check the
effective scheduler configuration. Both values must name the same digest.

Resolve the exact scheduler Pod before each `exec` command:

```sh
mise exec -- kubectl -n airflow get pods
```

```sh
mise exec -- kubectl -n airflow exec <exact-scheduler-pod> -c scheduler -- \
  airflow config get-value kubernetes_executor worker_container_repository
mise exec -- kubectl -n airflow exec <exact-scheduler-pod> -c scheduler -- \
  airflow config get-value kubernetes_executor worker_container_tag
mise exec -- kubectl -n airflow exec <exact-scheduler-pod> -c scheduler -- \
  python -c 'from anton_airflow.lakehouse import SPARK_RUNTIME_IMAGE; print(SPARK_RUNTIME_IMAGE)'
```

The evidence command also checks the completed task pod. It compares the pod
request and runtime `imageID` with the committed Airflow digest.

Require the live embedded Spark digest to equal these committed values:

- `SPARK_RUNTIME_IMAGE` in the Airflow source.
- The Spark History Server image digest.

## Source edge cases

Run the focused Airflow and Spark tests before image publication. Require these
cases:

- One empty chunk in a non-empty hour.
- One empty component in a non-empty hour.
- One all-empty hour.
- One query failure that differs from an empty success.
- Equal Airflow and Spark component keys.

A successful empty query produces a canonical zero-byte source object. It does
not produce a query failure.

The focused tests use controlled Spark adapters. They do not prove the packaged
Spark and Hadoop behavior.

After the Spark image build, run one image-level zero-byte source check:

```sh
mise exec -- docker run --rm --platform linux/amd64 \
  --entrypoint /opt/python/bin/python3.12 <local-spark-image> \
  -c 'import importlib.util, sys; from pathlib import Path; from pyspark.sql import SparkSession; source=Path("/tmp/flight-recorder-empty.jsonl"); source.touch(); spec=importlib.util.spec_from_file_location("flight_recorder", "/opt/spark/application/flight_recorder.py"); module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module); spark=SparkSession.builder.master("local[1]").appName("flight-recorder-empty-source-contract").getOrCreate(); payload=module._read_binary(spark, source.as_uri(), module.MAX_RAW_BYTES, minimum=0); spark.stop(); assert payload == b""; print("Flight Recorder real zero-byte Hadoop source: PASS")'
```

Require the final `PASS` line before image publication.

## Evidence mode preflight

Run the table contract and summary checks before the Workflow Run:

```sh
mise exec -- task trino:flight-recorder-contract
mise exec -- task trino:flight-recorder-summary
```

Require the Ticket 02 columns and `component_counts` table before full evidence.
Use approved Trino access to check the exact `source_hour_id` receipt.

Select one evidence mode:

- Use initial evidence only when the source hour has no receipt.
- Use replay evidence only with a complete initial result for that source hour.
- Use rejection evidence after a terminal source-query rejection.

If a receipt exists, stop the initial path. The retained receipt owns the
original Spark Attempt identity.

For manual acceptance only, inspect at most three unwritten closed hours. Check
all twelve Trino chunks with the production selector and entry fence.

Reject a candidate when any chunk reaches the entry fence. Scheduled operation
must retain the rejected hour instead of selecting another hour.

## Initial run

Retain the exact non-Flight Recorder snapshots before the Workflow Run:

```sh
mise exec -- task trino:flight-recorder-namespace-isolation \
  > .scratch/flight-recorder/evidence/<identity>-namespace-before.json
```

Create one new manual run after approval. Use one closed UTC hour boundary.
The source hour is the hour before this boundary.

```sh
mise exec -- kubectl -n airflow exec <exact-scheduler-pod> -c scheduler -- \
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

Start this collector immediately after terminal success. Write its first output
directly to the final run-owned path.

Preserve the original JSON bytes. Do not reserialize Iceberg snapshot identifiers
through JavaScript numbers.

Acceptance requires:

- The task pod uses the committed Airflow digest.
- Spark and Airflow receipts use one attempt identity.
- The authoritative Lease has no holder after completion.
- Spark reached `Succeeded` before `ResourceReleased`.
- The complete manifest matches one closed hour and its checksum.
- The manifest contains four components and 48 ordered source chunks.
- Each component has 12 independent query fences.
- Loki contains Airflow and Spark evidence without error samples.
- History Server returns the completed application within 20 results.
- Trino counts, contracts, snapshots, and the run receipt agree.
- Each component reconciles source, accepted, rejected, deduplicated, and written counts.
- The `logs` namespace has no snapshot commit during the Spark Attempt.

## Exact replay

Create a new run ID with the same source-window end. Do not change the component catalog.
Collect replay evidence against the first result:

```sh
mise exec -- task airflow:flight-recorder-replay-evidence \
  RUN_ID='manual__flight_recorder_<replay-identity>' \
  BASELINE=.scratch/flight-recorder/evidence/<identity>.json \
  > .scratch/flight-recorder/evidence/<replay-identity>.json
```

The baseline result must report `status: complete`. Replay acceptance requires
the same complete manifest, except for the Attempt name. Trino rows and snapshot
metadata must not change. The receipt count and final event count must not increase.

## Rejected hour

A failed component query must emit `flight_recorder_hour_rejection`. The record
must name the hour, component, chunk, Attempt, and completed query count.

Collect incomplete evidence with this command:

```sh
mise exec -- task airflow:flight-recorder-rejection-evidence \
  RUN_ID='manual__flight_recorder_<identity>' \
  > .scratch/flight-recorder/evidence/<identity>-rejected.json
```

Acceptance requires one exact rejection record and no complete manifest receipt.
It also requires no SparkApplication, Spark pod, or active writer Lease.

Collect rejection evidence immediately after the terminal task failure. The
strict validator requires the completed task pod before pod retention removes it.

If the task pod is absent, retain Loki and cluster absence evidence. Report the
strict result as incomplete. Do not accept the ticket.

The rejection collector bypasses Trino when one valid rejection record exists.
A valid rejection result does not require the Flight Recorder table schema.

## Cleanup and report

Retain both JSON results. Report the window, checksum, attempts, counts, and
snapshots. Record the evidence time and any retention limitation. Stop when both
results report `status: complete`.
