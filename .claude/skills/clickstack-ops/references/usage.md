# ClickStack — USAGE

Accessing HyperDX, sending a test signal, and querying. See `SKILL.md` for the containment rules these recipes must respect.

## Access the HyperDX UI

HyperDX is exposed on `envoy-internal` only (ADR 0028 — no Cloudflare tunnel):

```
https://hyperdx.${SECRET_DOMAIN}
```

`${SECRET_DOMAIN}` is the cluster's internal domain, substituted by Flux from the `cluster-secrets` Secret. Resolve the literal value from your environment, never hardcode it. Off-LAN access goes through Tailscale MagicDNS — see the `anton-remote-access` skill.

First login creates a **local HyperDX account** (HyperDX stores its own users/dashboards in the bundled MongoDB). The ClickHouse data source is seeded by HyperDX itself for this eval — the chart's `deployment.useExistingConfigSecret` is `false`, so we do **not** pre-load `connections.json` / `sources.json`. Confirm a source exists under HyperDX → Team Settings → Sources after first login; if not, add one pointing at the in-cluster ClickHouse Service with the `app` user (password = `CLICKHOUSE_APP_PASSWORD` from 1Password).

If the page does not load, check the HTTPRoute is Accepted and the backend is healthy:

```sh
kubectl -n clickstack get httproute hyperdx -o wide
kubectl -n clickstack get deploy clickstack-app
```

## Test signal — pod logs via the OTel collector

The bundled collector runs in **Deployment mode** and receives OTLP; it does **not** tail pod logs by default. There are two ways to feed it the test signal ADR 0028 calls for (pod logs):

**In-cluster OTLP endpoints** (collector Service in the `clickstack` namespace):

```
http://<collector-service>.clickstack.svc.cluster.local:4318   # OTLP/HTTP
<collector-service>.clickstack.svc.cluster.local:4317          # OTLP/gRPC
```

Resolve the exact Service name (it is release-name-derived) before using it:

```sh
kubectl -n clickstack get svc | grep -i otel
```

**Option A — filelog receiver (collector tails node pod logs).** Add a `filelog` receiver + a logs pipeline to the collector config via the chart's `otel-collector` values (in `kubernetes/apps/clickstack/clickstack-app/app/helmrelease.yaml`). This usually requires the collector to run as a DaemonSet with `/var/log/pods` mounted, or to mount that path on the Deployment. Validate the receiver's `include` glob against Talos pod-log paths before committing. This is a values-only change to the existing HelmRelease — commit, push, let Flux reconcile; do not `kubectl apply`.

**Option B — point an app's OTLP log exporter at the collector.** Set the app's `OTEL_EXPORTER_OTLP_ENDPOINT` to the collector endpoint above. Lower-footprint than filelog and closer to how Temporal traces will flow. Good first test: a throwaway debug pod that emits OTLP logs.

After either, confirm logs land in ClickHouse via HyperDX search (below) or by querying ClickHouse directly (see `operations.md`).

## Test signal — Temporal OTLP traces

This is the ADR 0028 operational follow-up: point Temporal's server OTLP trace exporter at the ClickStack collector. **Do NOT edit the Temporal app manifests as part of scaffolding this skill** — this is a deliberate, separately-reviewed change to the Temporal app, made when you actively run the eval.

1. Verify the Temporal server's OTLP config surface (Temporal exports traces via OpenTelemetry; check the Temporal HelmRelease / server config for an OTLP exporter block).
2. Set the trace exporter OTLP endpoint to the ClickStack collector gRPC endpoint:
   ```
   <collector-service>.clickstack.svc.cluster.local:4317
   ```
   Use the cluster-internal Service DNS (cross-namespace: Temporal namespace → `clickstack` namespace). No HTTPRoute / external exposure for telemetry ingestion — it stays in-cluster.
3. Confirm no NetworkPolicy blocks Temporal-namespace → `clickstack`-namespace egress on 4317.
4. Commit the Temporal-side change, push, reconcile. Then verify traces appear in HyperDX (Traces view).

Keep this change reversible and small — it is part of the throwaway eval, removed at teardown.

## Querying — Lucene and SQL

HyperDX offers two query modes against ClickHouse:

- **Lucene-style search** — the default search bar. Field-scoped terms (`level:error service:temporal`), free text, time-range chips. Fast for "show me everything matching X in the last N hours."
- **SQL mode** — direct ClickHouse SQL against the events tables. Use for aggregations, joins, and the high-cardinality / wide-events questions ADR 0028's success criteria target.

Aim the queries at producing **falsifiable answers** to ADR 0028's four success criteria:

1. **Cross-pod / ≥24h wide-events** (vs VictoriaLogs) — run a query spanning many pods over ≥24h (e.g. group errors by service+pod over a day) and note latency + UX vs what VictoriaLogs would give.
2. **"ClickHouse too heavy" at homelab scale** — pair query work with the resource measurements in `operations.md` (CPU/RAM of ClickHouse + Keeper + MongoDB + HyperDX).
3. **HyperDX UX worth abandoning Grafana** — judge the wide-events UX against the cost of running two front-doors.
4. **Containment** — confirm you never reached for a Prometheus-metric query inside HyperDX; metrics stay on Grafana.

Record observations against the criteria as you go — they feed the 2026-08-02 review and the ADR 0008 successor.
