# Kubernetes logs: OTel Collector to Loki

This is the canonical runbook for the durable Kubernetes pod-log path. The
deprecated [ClickStack experiment](../notes/clickstack-experiment.md) is
historical; its live teardown remains an operator-approved step.

## Architecture and data path

```text
node /var/log/pods (read-only)
  -> OTel Collector DaemonSet (filelog + Kubernetes metadata)
  -> Loki OTLP/HTTP :3100/otlp
  -> SeaweedFS S3 bucket `loki`
  -> kube-prometheus-stack Grafana Explore
```

The collector uses the official OpenTelemetry chart `0.173.1` and collector
image `0.161.0`. Every reader resumes known files from persistent checkpoints
and starts unseen files at the beginning. General, workflow, and SeaweedFS
volume receivers use non-overlapping paths and the Kubernetes container-log
parser. State lives on the existing node-local `/var/lib/otelcol` host path.
Loki uses chart `18.13.5` with Loki `3.7.8` in monolithic mode. The
separate Talos log sink is not this backend and must remain separate.

## Executable contract

### Reader and exporter durability

File offsets and the OTLP export queue share the existing `file_storage`
extension. Its writes use fsync, and each component database is capped at
256 MiB. The export queue admits at most 64 MiB of serialized requests. Online
capacity also includes in-flight requests, storage overhead, and file offsets;
the queue limit is not a total process-memory or filesystem quota. Storage is
compacted on collector startup. Never delete its databases to clear a backlog.

The pinned collector enables `stanza.synchronousLogEmitter` (an alpha feature
gate in 0.161.0) to remove the reader adapter's in-memory batching gap. Without
it, a hard kill can lose already-checkpointed records before they reach the
disk queue. The restart check reproduced that loss with checkpoints and a
persistent queue alone. Revalidate this gate when upgrading the collector.

The pipeline normalizes and groups severity synchronously, then persists the
export request. Batching happens inside the exporter queue (256 to 512 records,
two-second flush), after persistence. An asynchronous batch processor before
the queue would acknowledge records before they were durable and is prohibited
by the logging contract.

Receiver and exporter retries do not expire on a timer. A full queue or storage
error backpressures the reader instead of intentionally skipping a batch.
Delivery is at least once: after a crash, duplicates can occur between queue
persistence and checkpoint persistence. Source-log rotation/deletion, node/disk
loss, permanent backend rejection, and Loki's independent WAL behavior remain
limits. The SeaweedFS reader's existing one-hour timestamp filter is unchanged.
General and workflow readers have no age filter.

### First checkpoint bootstrap

Before the first deployment of the durable general reader, keep the old
collector and Loki healthy and render the temporary offset seeder:

```sh
mise exec -- python3 scripts/verify-log-durability.py --render-seed /tmp/otel-log-seed.json
```

The rendered ConfigMap and `observability/otel-log-checkpoint-seed` DaemonSet
require approved live creation and cleanup. They use the same general receiver
ID and storage directory, but start at file end and export only counts to the
debug exporter. They do not send application logs to another backend. Confirm
the applied general reader still has no `storage` setting before running the
seeder; never run two processes against the same receiver database.

Observe one seeder per node, allow complete discovery/polling, then stop and
remove the seeder before publishing the collector change. Verify its general
reader database exists on every node. Publishing after seeding leaves a small
overlap of already-delivered records, which is preferable to skipping unread
records. New records written after seeding and new files are read by the durable
collector from their saved offset or beginning. Existing workflow and SeaweedFS
receiver IDs and state remain intact. After this one-time migration, ordinary
collector rollouts need no seeder.

Rollback through Git while preserving node-local databases. Reverting to a
memory queue or stateless reader reintroduces restart loss; first let the durable
queue drain while Loki is healthy. Do not restart Loki solely to clear its WAL
recovery counter or delete its WAL/PVC for this migration.

### Repeatable restart check

```sh
mise exec -- python3 scripts/verify-log-durability.py --baseline-ref d6ffc31b --output /tmp/log-durability.json
```

This local Docker check runs the pinned collector and Loki with a continuously
written, fsynced record ledger. It overlaps a graceful Loki restart with two
collector SIGKILLs and a graceful collector restart, retains queue/checkpoint
files, and creates a new log file
while the reader is down. The baseline must lose records; the fixed configuration
must make every ledger record queryable. It also checks first-bootstrap offsets
without replaying old history. No Kubernetes access or live notification occurs.
Loki is stopped gracefully with its existing flush-on-shutdown policy; this does
not claim to fix upstream Loki crash-replay bugs.

For an approved live check, use a temporary per-node stdout ledger, restart only
`observability/statefulset/loki` and
`observability/daemonset/otel-collector-opentelemetry-collector-agent`, then
compare every emitted ledger ID with Loki after all queues drain. Record the
source/Flux/Helm revisions, pod UIDs, queue metrics, WAL counters, and missing or
duplicate IDs. Remove the temporary ledger workload after saving evidence.

ADR 0032's severity vocabulary, indexed-label allowlist, and retention policy
live in one executable contract. Display the current values instead of copying
them into another operator document:

```sh
python3 scripts/validate-log-contract.py --show
```

Run `mise exec -- task contracts:validate` before committing a change to OTel, Loki,
Grafana's Loki datasource, or the query catalog. The validator checks those
adapters against golden log records and the accepted contract.

## Labels and structured metadata

Use `scripts/validate-log-contract.py --show` for the intentional indexed
labels and severity vocabulary.

The dots in Kubernetes resource attribute names become underscores in Loki
label names. Workload labels are sparse: only the applicable workload-kind
label is present. Loki may add its normal service-discovery label when enough
service attributes exist; no application-specific high-cardinality labels are
requested.

Pod name/UID, node name, ReplicaSet and controller UIDs, container ID, image
details, file path, severity text, and other Kubernetes/resource attributes
are structured metadata or log content. Do not turn request IDs, trace IDs,
user IDs, IP addresses, or pod UIDs into labels.

## Retention, storage, and monitoring

Use `scripts/validate-log-contract.py --show` for the configured default and
per-stream retention. The collector's fallback behavior and Loki's selectors
are checked together, so a policy change fails validation until every adapter
agrees.
Loki compactor retention and delete requests are enabled. The Loki StatefulSet
has one 20 GiB Longhorn PVC. Chunks and ruler data use the existing SeaweedFS
S3 service and bucket `loki`; the storage-owned `seaweedfs-buckets-ensure`
CronJob verifies the bucket. This gives a
bounded local working set and bounded logical retention, but the current
SeaweedFS source pattern reuses its existing admin identity and does not set a
bucket quota. Treat SeaweedFS free space as a capacity limit.

Watch the Loki ServiceMonitor and collector PodMonitor in Prometheus, Loki
pod restarts/readiness, collector queue drops/export errors, compactor errors,
PVC usage, and SeaweedFS volume/object-store free space. If capacity grows
unexpectedly, reduce low-severity retention or pause rollout before increasing
storage.

## Spark Application History

Loki stores Spark driver and executor standard streams. Spark Application
History is a separate path. Spark writes compressed rolling event files to
`s3a://spark-events/events/`. A one-replica History Server reads those files.

The History Server uses the pinned Spark runtime image and an S3 reader
identity. It has no Kubernetes API token. Its S3 identity can read and list
`spark-events`, but it cannot write or delete objects. The History Server
cleaner is disabled. A storage-owned `BucketLifecyclePolicy` expires objects
under `events/` after 30 days.

Use these read-only checks before interpreting an empty History Server view:

```sh
mise exec -- flux get ks -A | rg 'spark-history-server|seaweedfs-config'
mise exec -- kubectl -n lakehouse get deploy,pods -l app.kubernetes.io/name=spark-history-server
mise exec -- kubectl -n lakehouse get sparkapplications
mise exec -- kubectl -n storage get bucket spark-events
mise exec -- kubectl -n storage get bucketlifecyclepolicy spark-events-30d
```

An approved localhost port-forward exposes the read-only History Server API:

```sh
mise exec -- kubectl -n lakehouse port-forward --address 127.0.0.1 \
  svc/spark-history-server 18080:18080
curl -fsS http://127.0.0.1:18080/api/v1/applications | jq
```

Stop the port-forward after the check. If applications are absent, inspect the
Spark event-log configuration, the `spark-events` prefix, History Server logs,
and External Secret conditions in that order. Do not use Loki output as proof
that Spark event history exists.

## Queries

In Grafana, open Explore, select `Loki`, choose the time range, and paste one
of these queries:

```logql
{severity=~"fatal|error"} |~ "(?i)(error|fatal|panic|exception)"
```

```logql
{severity="warn"}
```

```logql
{k8s_namespace_name="observability", k8s_deployment_name="loki"}
```

```logql
{k8s_namespace_name="default", k8s_container_name="api"} | json
```

Use Grafana's absolute time picker for a time range. If an operator explicitly
approves a temporary local port-forward, the Loki HTTP API is also available:

```sh
mise exec -- kubectl -n observability port-forward --address 127.0.0.1 svc/loki 3100:3100
curl --get 'http://127.0.0.1:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={severity="error"}' \
  --data-urlencode 'limit=100'
```

The HTTP query is read-only, but the port-forward is a live networking mutation
with a cleanup obligation. Bind it to localhost, keep the endpoint internal,
and stop the process immediately after collecting bounded evidence.

## Diagnosis

1. Collector: check DaemonSet scheduling, readiness, and recent logs. Confirm
   `/var/log/pods` is read-only. Confirm the workflow receiver uses the writable
   checkpoint host path. Confirm the receiver path sets do not overlap. Check
   queue and export metrics for sustained drops.
2. Loki: check the single StatefulSet pod, readiness, ServiceMonitor errors,
   compactor messages, PVC usage, and the storage-owned
   `seaweedfs-buckets-ensure` CronJob. Confirm the in-cluster SeaweedFS S3
   endpoint and ESO-generated credential Secret; never print the Secret value.
3. Grafana: verify the provisioned datasource is named `Loki`, points to
   `http://loki.observability.svc.cluster.local:3100`, and is not being
   overridden by manual state. Test the same query in Explore and inspect
   Grafana datasource/proxy errors.
4. If only new logs are absent, identify the owning receiver. All readers start
   new files at the beginning and resume known files from persistent checkpoints.
   Check file discovery, queue/backpressure, and storage errors
   before changing retention or storage.

## Rollout and ClickStack teardown

The source of truth is prepared for this order, but each live step requires
explicit operator approval:

1. Review the rendered Flux/Kubernetes changes and capacity for the Loki PVC
   and existing SeaweedFS volumes.
2. Reconcile/apply the storage `seaweedfs-config` app and wait for the
   `seaweedfs-buckets-ensure` CronJob to report the `loki` bucket present.
3. Reconcile/apply the Loki app and wait for its pod and ServiceMonitor to
   become healthy.
4. Reconcile/apply the OTel Collector app and verify every eligible node has a
   ready DaemonSet pod and fresh logs arrive in Grafana Explore.
5. Verify Grafana datasource provisioning and the retention/queue/compactor
   metrics. Keep the separate Talos sink unchanged.
6. Only after acceptance, remove live ClickStack resources using the approved
   operator procedure: suspend or remove its Flux ownership as appropriate,
   delete ClickStack workloads and namespace only after confirming exact
   targets, and remove obsolete ClickStack PVCs/Longhorn recurring jobs through
   the storage operator's documented process. Do not run this teardown as part
   of source-of-truth review, and do not delete the Talos sink.

The old ClickStack manifests and ClickStack-specific Longhorn helper
resources are no longer managed by this repository. Any live ClickStack PVC
or volume cleanup remains operator-only and requires a separate, explicit
cleanup decision.

## Security boundary

Application logs may contain credentials, tokens, personal data, request
payloads, or other sensitive information. Loki, Grafana, the collector, and
any port-forward must stay tailnet/internal. Do not add a public route or
commit log samples containing secrets.

Future extensions may add a gateway collector or trace backend, but neither is
part of this first-cut contract.
