# Query catalog

These are bounded starting points. Add a time range and a small result limit
before widening a query.

## Incident triage

```logql
{severity=~"fatal|error"}
  |~ "(?i)(panic|exception|timeout|failed|oom|out of memory)"
{k8s_namespace_name=~".+", severity="warn"}
  |~ "(?i)(failed|retry|backoff|degraded|unhealthy)"
```

## Workload targeting

```logql
{k8s_namespace_name="food-site", k8s_deployment_name="food-site-server"}
{k8s_namespace_name="observability"}
  | k8s_pod_name=~"otel-collector-.*"
{k8s_namespace_name="registries", k8s_deployment_name="harbor-registry"}
  | json
```

## Pipeline health

```logql
{k8s_namespace_name="observability", k8s_container_name="loki"}
  |~ "(?i)(failed|error|500|writable|compactor|retention)"
{k8s_namespace_name="storage", k8s_container_name="s3"}
  |~ "(?i)(failed|error|500|writable|collection)"
{k8s_namespace_name="flux-system", k8s_deployment_name="helm-controller", severity="error"}
  | json | line_format "{{.msg}} {{.error}}"
```

## JSON bodies

```logql
{k8s_namespace_name="flux-system", k8s_deployment_name="helm-controller"}
  | json | level="error"
```

The `query_range` API returns one or more streams. Each stream has a label
map and `values` pairs of `[nanosecond_timestamp, line]`. For agent output,
report the number of streams and samples, then include only a few redacted
examples.
