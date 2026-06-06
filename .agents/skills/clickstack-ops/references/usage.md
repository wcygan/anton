# ClickStack Usage

Use this reference for HyperDX UI access, test signals, and Lucene or SQL queries. Keep all telemetry ingestion internal to the cluster.

## Access HyperDX

Current manifests provide two internal access paths:

- Tailnet: `https://hyperdx.<tailnet-name>.ts.net` via `hyperdx-tailscale-ingress`.
- LAN: `https://hyperdx.${SECRET_DOMAIN}` via `envoy-internal`.

Find the live tailnet host at runtime instead of hardcoding it:

```sh
kubectl -n clickstack get ingress hyperdx -o wide
```

Check the LAN route and backend:

```sh
kubectl -n clickstack get httproute hyperdx -o wide
kubectl -n clickstack get deploy clickstack-app
```

First login creates the local HyperDX account stored in bundled MongoDB. HyperDX seeds its own ClickHouse source for this eval because `hyperdx.deployment.useExistingConfigSecret` is `false`. If no source appears under HyperDX Team Settings, add one pointing at the in-cluster ClickHouse Service with the `app` user and the `CLICKHOUSE_APP_PASSWORD` value from 1Password. Do not print the value.

If login redirects to `localhost`, `FRONTEND_URL` is wrong or stale. Read `references/tailscale-access.md` before changing anything.

## Test Signal: Pod Logs

The bundled OTel collector is Deployment-mode and accepts OTLP. It does not tail pod logs by default.

Resolve the collector Service before configuring a client:

```sh
kubectl -n clickstack get svc | rg -i 'otel|collector'
```

Expected endpoint shapes:

```text
http://<collector-service>.clickstack.svc.cluster.local:4318
<collector-service>.clickstack.svc.cluster.local:4317
```

Use one of two paths:

- Filelog receiver: add a `filelog` receiver and logs pipeline through the `otel-collector` values in `kubernetes/apps/clickstack/clickstack-app/app/helmrelease.yaml`. Validate Talos pod-log paths and any required `/var/log/pods` mount. This is a GitOps manifest change; do not `kubectl apply` it.
- App OTLP exporter: point a workload's OTLP log exporter at the collector. For a throwaway debug pod or app config change, present the exact command or diff and wait for approval.

After either path lands, verify in HyperDX search or query ClickHouse directly with the read-only checks in `operations.md`.

## Test Signal: Temporal OTLP Traces

Temporal trace export is an ADR 0028 follow-up, not part of the ClickStack scaffold.

1. Verify Temporal's OTLP config surface in the Temporal manifests before editing.
2. Point the Temporal trace exporter at the collector gRPC endpoint:

   ```text
   <collector-service>.clickstack.svc.cluster.local:4317
   ```

3. Confirm no NetworkPolicy blocks Temporal namespace egress to `clickstack` on 4317.
4. Commit the Temporal-side change separately and let Flux reconcile after approval.
5. Verify traces appear in HyperDX.

Keep this change reversible. Remove it during ClickStack teardown.

## Querying

HyperDX supports two useful query modes:

- Lucene-style search for quick field filters, free text, time ranges, and "show matching events" workflows.
- SQL mode for ClickHouse aggregations, joins, and high-cardinality or wide-event questions.

Tie queries to ADR 0028's four success criteria:

1. Cross-pod and 24h-or-longer wide-event questions: record the query, latency, and whether the UX beats the VictoriaLogs shortlist.
2. ClickHouse cost: pair query evidence with `kubectl -n clickstack top pods` data from `operations.md`.
3. HyperDX UX: record whether the separate logs/traces UI is worth leaving Grafana as the metrics-only front door.
4. Containment: confirm no Prometheus metrics entered ClickHouse.

Record concrete observations as you go; they feed the 2026-08-02 review and the ADR 0008 successor.
