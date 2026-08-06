---
name: query-kubernetes-logs
description: >-
  Query and troubleshoot Anton Kubernetes logs through the OTel DaemonSet to
  Loki pipeline. Use for incident investigation, workload debugging, recent
  warning or error searches, Grafana Explore or LogQL queries, checking log
  collection, or explaining why a pod's logs are missing.
---

# Query Kubernetes Logs

Use this skill to turn a log question into a bounded, evidence-backed Loki
query. The normal result is a short report containing the exact time range,
LogQL selector, stream count, sample count, relevant labels, and redacted
examples or a clear explanation of why no logs were found.

## Read first

1. Read the repository `AGENTS.md` and use the repository's `mise exec --`
   wrapper for cluster commands.
2. Read the [Kubernetes logs runbook](../../../docs/docs/runbooks/kubernetes-logs-loki.md)
   when the question involves retention, storage, Grafana access, or a
   missing-log investigation.
3. Read the [query catalog](references/query-catalog.md) for starting queries.
4. Read the [Loki HelmRelease](../../../kubernetes/apps/observability/loki/app/helmrelease.yaml)
   or [OTel HelmRelease](../../../kubernetes/apps/observability/otel-collector/app/helmrelease.yaml)
   when a query result conflicts with the configured pipeline.

Treat live command output as current evidence and repository files as the
source of truth for intended configuration. Do not claim that a log was
collected merely because the manifest looks correct.

## Safety and privacy

- Verify the Kubernetes context before querying:
  `mise exec -- kubectl config current-context`.
- Read-only commands are the default: `kubectl get`, `describe`, `logs`,
  `port-forward`, `flux get`, and HTTP GETs to Loki's local port-forward.
- Do not run `apply`, `delete`, `reconcile`, `suspend`, `rollout restart`,
  `scale`, or storage changes from this skill. Hand proposed mutations to the
  operator for approval.
- Use a local port-forward. Never expose Loki publicly and never print S3,
  Grafana, or Kubernetes Secret values.
- Logs can contain credentials, cookies, tokens, personal data, and request
  bodies. Redact those fields in the report and keep samples short.
- Start with a narrow time range and `limit`; widen only when the evidence
  justifies it.

## Pipeline facts

The production path is:

```text
node /var/log/pods
  -> OTel Collector DaemonSet (observability)
  -> Loki monolithic StatefulSet :3100 (observability)
  -> SeaweedFS S3 bucket loki (storage)
  -> existing Grafana Loki datasource
```

Important names and behavior:

- Loki service: `loki.observability.svc.cluster.local:3100`.
- Grafana datasource: `Loki`, UID `loki`.
- OTel DaemonSet: `otel-collector-opentelemetry-collector-agent`.
- The collector tails `/var/log/pods/*/*/*.log`, starts at file end, and uses
  a host checkpoint directory. A newly installed collector intentionally does
  not replay old file history.
- Indexed labels are deliberately low-cardinality:
  `k8s_namespace_name`, `k8s_container_name`, `k8s_deployment_name`,
  `k8s_statefulset_name`, `k8s_daemonset_name`, `k8s_job_name`,
  `k8s_cronjob_name`, and `severity`.
- Pod name, UID, node, image, container ID, and file path are structured
  metadata, not indexed labels. Filter them with a structured metadata
  expression such as `| k8s_pod_name="loki-0"`, or use a line filter.
- Retention targets are `fatal`/`error`: 30 days; `warn`: 14 days; and
  `info`, `unknown`, `debug`, and `trace`: 24 hours. Missing severity is
  normalized to `info`.
- Loki has one 20 GiB Longhorn PVC. Chunks and ruler data use the existing
  SeaweedFS S3 service and `loki` bucket. SeaweedFS's 10,000 MB volume limit
  creates more logical volume slots; it is not a Loki retention quota.

## Standard workflow

### 1. Check the path

Run a small health pulse before interpreting an empty query:

```sh
mise exec -- kubectl config current-context
mise exec -- flux get ks -A | rg 'cluster-apps|loki|otel-collector'
mise exec -- flux get hr -A | rg 'loki|otel-collector|kube-prometheus-stack'
mise exec -- kubectl get pods -n observability -o wide | rg 'loki|otel-collector|grafana|NAME'
```

For a missing-log question, also inspect the collector and Loki's recent
errors without dumping an unbounded log:

```sh
mise exec -- kubectl get ds otel-collector-opentelemetry-collector-agent -n observability
mise exec -- kubectl logs -n observability ds/otel-collector-opentelemetry-collector-agent --since=10m
mise exec -- kubectl logs -n observability loki-0 -c loki --since=10m
```

### 2. Query through a local port-forward

In one terminal:

```sh
mise exec -- kubectl -n observability port-forward svc/loki 3100:3100
```

In another:

```sh
curl -fsS http://127.0.0.1:3100/ready
curl -fsS http://127.0.0.1:3100/loki/api/v1/labels | jq
```

Use Grafana Explore when a human needs to browse context. Use Loki's HTTP
API when an agent needs deterministic, scriptable evidence:

```sh
curl -fsS --get http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={severity=~"fatal|error"}' \
  --data-urlencode 'since=24h' \
  --data-urlencode 'limit=100' | jq
```

The response contains streams with a `stream` label map and `values` as
`[nanosecond_timestamp, line]` pairs. Count streams and samples before
selecting a small number of redacted examples.

### 3. Build the query in two stages

First select indexed labels. Then narrow with structured metadata or content:

```logql
{k8s_namespace_name="observability", severity=~"fatal|error"}
| k8s_pod_name="loki-0"
|~ "(?i)(timeout|failed|panic)"
```

Do not begin with an unbounded regex over every stream. Do not assume a pod
name is an indexed label. Use `| json` only when the log body is JSON; parse
fields for filtering or formatting instead of promoting high-cardinality
values to labels.

Useful starting queries:

```logql
{severity=~"fatal|error"}
{severity=~"fatal|error|warn", k8s_namespace_name="observability"}
{k8s_namespace_name="observability", k8s_deployment_name="loki"}
{k8s_namespace_name="default", k8s_container_name="api"}
  |~ "(?i)(error|panic|exception|timeout)"
{k8s_namespace_name="flux-system", k8s_deployment_name="helm-controller", severity="error"}
  | json
{k8s_namespace_name="observability", severity="warn"} |= "failed"
```

Always include `since=...` or explicit `start`/`end` in API requests. Report
the query, range, limits, stream/sample counts, and whether the result came
from labels, structured metadata, or content matching.

## Missing-log diagnosis

If a query is empty, follow this order:

1. Confirm Loki is Ready, its Service has endpoints, and the query time range
   includes the expected event.
2. Confirm the OTel DaemonSet has one Ready pod per eligible node.
3. Inspect recent collector logs for file discovery, parser failures,
   checkpoint, queue, retry, export, or HTTP 5xx errors.
4. Inspect the rendered collector ConfigMap for exactly one `file_log`
   receiver, a read-only `/var/log/pods` mount, checkpoint storage, and the
   `groupbyattrs/severity` processor before batching.
5. Query indexed labels first. Then use structured metadata for pod name or
   a line filter for content.
6. Remember `start_at: end`: logs written before the collector began tailing
   are not expected to appear unless the file later receives new lines.
7. If Loki reports object-store or writable-volume errors, inspect SeaweedFS
   S3 health and free capacity without printing credentials:

```sh
mise exec -- kubectl logs -n storage -l app.kubernetes.io/component=s3 --since=10m
mise exec -- kubectl get pvc storage-loki-0 -n observability
```

Do not “fix” a missing-log result by increasing retention or storage before
establishing whether ingestion, querying, or object storage is the failing
stage.

## Agent report format

Return this compact structure:

```text
Status: found | no matching logs | pipeline issue | blocked
Context: <verified Kubernetes context and workload/time window>
Query: <exact LogQL selector and filters>
Range/limit: <time range and limit>
Evidence: <stream count, sample count, key labels, health checks>
Examples: <short, redacted lines with timestamps>
Next step: <one safe follow-up, or the explicitly approved mutation needed>
```

If no logs match, distinguish “no matching records in this range” from “the
pipeline is unhealthy” and from “the collector never replayed the old file.”
