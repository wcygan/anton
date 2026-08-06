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

The collector uses the official OpenTelemetry chart `0.165.0` and collector
image `0.156.0`. It uses the Kubernetes container-log parser, starts at the
end of files for migration, persists checkpoints under a bounded node-local
hostPath, and excludes collector self-logs. Loki uses chart `18.7.1` with
Loki `3.7.4` in single-binary/monolithic mode. The separate temporary Talos
log sink is not this backend and must remain separate.

## Labels and structured metadata

The intentional indexed labels are:

```text
k8s_namespace_name
k8s_container_name
k8s_deployment_name
k8s_statefulset_name
k8s_daemonset_name
k8s_job_name
k8s_cronjob_name
severity                  # fatal, error, warn, info, debug, or trace
```

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

The configured stream policy is:

| Severity | Target retention |
| --- | --- |
| `fatal`, `error` | 30 days |
| `warn` | 14 days |
| `info`, `unknown` | 24 hours |
| `debug`, `trace` | 24 hours |

The collector maps missing/unrecognized severity to `info`; `unknown` is a
Loki policy fallback for records that arrive without the normalized label.
Loki compactor retention and delete requests are enabled. The Loki StatefulSet
has one 20 GiB Longhorn PVC. Chunks and ruler data use the existing SeaweedFS
S3 service and bucket `loki`; a CronJob verifies the bucket. This gives a
bounded local working set and bounded logical retention, but the current
SeaweedFS source pattern reuses its existing admin identity and does not set a
bucket quota. Treat SeaweedFS free space as a capacity limit.

Watch the Loki ServiceMonitor and collector PodMonitor in Prometheus, Loki
pod restarts/readiness, collector queue drops/export errors, compactor errors,
PVC usage, and SeaweedFS volume/object-store free space. If capacity grows
unexpectedly, reduce low-severity retention or pause rollout before increasing
storage.

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

Use Grafana's absolute time picker for a time range, or use the Loki HTTP API
through a read-only local port-forward:

```sh
kubectl -n observability port-forward svc/loki 3100:3100
curl --get 'http://127.0.0.1:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={severity="error"}' \
  --data-urlencode 'limit=100'
```

The port-forward and query are read-only. Keep the endpoint local; do not
publish Loki or copy sensitive log contents outside the tailnet/internal
network.

## Diagnosis

1. Collector: check DaemonSet scheduling, readiness, and recent logs. Confirm
   `/var/log/pods` is mounted read-only, the checkpoint hostPath is writable by
   the collector, and the collector queue/export metrics show no sustained
   drops. Do not enable collector self-log ingestion.
2. Loki: check the single StatefulSet pod, readiness, ServiceMonitor errors,
   compactor messages, PVC usage, and the `loki-bucket-ensure` CronJob. Confirm
   the in-cluster SeaweedFS S3 endpoint and ESO-generated credential Secret;
   never print the Secret value.
3. Grafana: verify the provisioned datasource is named `Loki`, points to
   `http://loki.observability.svc.cluster.local:3100`, and is not being
   overridden by manual state. Test the same query in Explore and inspect
   Grafana datasource/proxy errors.
4. If only new logs are absent, remember that migration starts at file end;
   old node log history is intentionally not replayed. Check pod restarts and
   the collector's file discovery before changing retention or storage.

## Rollout and ClickStack teardown

The source of truth is prepared for this order, but each live step requires
explicit operator approval:

1. Review the rendered Flux/Kubernetes changes and capacity for the Loki PVC
   and existing SeaweedFS volumes.
2. Reconcile/apply the Loki app and wait for its pod, S3 bucket check, and
   ServiceMonitor to become healthy.
3. Reconcile/apply the OTel Collector app and verify every eligible node has a
   ready DaemonSet pod and fresh logs arrive in Grafana Explore.
4. Verify Grafana datasource provisioning and the retention/queue/compactor
   metrics. Keep the separate Talos sink unchanged.
5. Only after acceptance, remove live ClickStack resources using the approved
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
