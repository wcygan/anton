# Verify Scrapes — Probe Recipes

After you commit a ServiceMonitor / PodMonitor / PrometheusRule and Flux reconciles, you need to confirm Prometheus actually picked it up. This is the repeatable playbook.

## Why not `kubectl port-forward`?

Backgrounded port-forwards in this repo die unpredictably — the subshell pattern `( kubectl port-forward ... & ); sleep 3` leaves zombie connections, and interactive port-forwards block the conversation. **Prefer `kubectl exec` into the Prometheus pod with `wget`.** It's synchronous, gives clean exit codes, and doesn't linger.

## The one invocation

```sh
# GET-style (simple queries)
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/<endpoint>'

# POST-style (PromQL queries with special chars, labels, etc.)
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- --post-data='query=<PROMQL>' 'http://localhost:9090/api/v1/query'
```

**Always POST for PromQL**. Braces / quotes / spaces get mangled in a GET query string. The 400 Bad Request you'll see is almost always URL-encoding rot.

For large responses (the `/targets` endpoint easily hits hundreds of KB), redirect to a temp file first — `wget` inside the exec truncates piped output above ~200KB:

```sh
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets?state=active' > /tmp/targets.json
mise exec -- jq '.data.activeTargets | length' /tmp/targets.json
```

## Recipe 1 — did my ServiceMonitor/PodMonitor produce a scrape pool?

```sh
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets?state=active' > /tmp/targets.json

mise exec -- jq -r '
  .data.activeTargets
  | group_by(.scrapePool)
  | .[]
  | "\(length)\t\(.[0].scrapePool)\t\(.[0].health)"
' /tmp/targets.json | sort
```

Output shape:

```
4	podMonitor/flux-system/flux-controllers/0	up
1	serviceMonitor/cert-manager/cert-manager/0	up
1	serviceMonitor/storage/longhorn/0	up
```

- The scrape pool is named `<kind>/<ns>/<name>/<endpoint-index>`. If yours doesn't appear, Prometheus didn't load the CR — check the operator log (`kubectl -n observability logs deploy/kube-prometheus-stack-operator --tail=100`).
- If it appears but `health != up`, jump to Recipe 3.

## Recipe 2 — is a specific metric flowing?

```sh
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- --post-data='query=<METRIC_NAME>' 'http://localhost:9090/api/v1/query' \
  | mise exec -- jq '.data.result | length'
```

Zero series means either nothing has been scraped yet or the metric name is wrong. Check the name:

```sh
# list metric names the job exposes
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/label/__name__/values?match[]={job="<job>"}' \
  | mise exec -- jq -r '.data[]' | rg -i '<partial-name>'
```

## Recipe 3 — target is DOWN — why?

```sh
mise exec -- jq -r '
  .data.activeTargets
  | map(select(.health != "up"))
  | .[]
  | "\(.scrapePool)\t\(.labels.instance)\t\(.lastError)"
' /tmp/targets.json
```

Common error fragments:

| `lastError` fragment | Cause | Fix |
| --- | --- | --- |
| `connection refused` | Pod isn't listening on that port, or the port name maps to wrong container port | Check `kubectl -n <ns> exec <pod> -- netstat -tln` (if available) or pod spec `containers[].ports`. |
| `no such host` | Service was deleted / not created | Look at the Service — does the `selector` actually match the pod labels? |
| `tls: bad certificate` / `x509:` | HTTPS endpoint with unexpected cert | Add `scheme: https` + `tlsConfig.insecureSkipVerify: true` (fast), or configure real CA. |
| `server returned HTTP status 404` | Wrong `path:` — exporter uses `/metrics` or a custom path | Confirm the exporter's path by exec'ing into it and curl'ing `localhost:<port>/metrics`. |
| `context deadline exceeded` | Scrape timeout — endpoint is slow | Increase `scrapeTimeout` in the SM/PM (default 10s). For bulky Cilium endpoints, 30s may be needed. |
| `failed to parse textfile` | Exporter returned non-Prometheus output | Sanity-check: what does `curl localhost:<port>/metrics` actually return? |

## Recipe 4 — my PrometheusRule doesn't fire (or doesn't exist)

```sh
# list all loaded rule groups
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/rules' > /tmp/rules.json
mise exec -- jq -r '.data.groups[] | .file + " :: " + .name' /tmp/rules.json | sort -u

# find any rule with an evaluation error
mise exec -- jq -r '
  .data.groups[].rules[]
  | select(.health != "ok")
  | "\(.type)\t\(.name // .query)\t\(.health)\t\(.lastError)"
' /tmp/rules.json
```

If your rule isn't in the groups list at all, the operator didn't pick up the CR. Common causes:
- PrometheusRule is in a namespace Prometheus's selector excludes — on anton the selector is match-all, so this should never happen.
- `spec.groups[].rules[]` is malformed — `kubectl -n <ns> describe prometheusrule <name>` shows the validation error.

## Recipe 5 — Grafana dashboard doesn't appear

```sh
# Is the ConfigMap there and labelled?
kubectl get cm -A -l grafana_dashboard=1 | rg <slug>

# Did the sidecar see it?
kubectl -n observability logs deploy/kube-prometheus-stack-grafana -c grafana-sc-dashboard --tail=200 | rg <slug>

# Is Grafana actually reading the file?
kubectl -n observability exec deploy/kube-prometheus-stack-grafana -c grafana -- ls -la /tmp/dashboards/ | rg <slug>
```

Sequence of failure (most common first):
1. Label misspelled — must be exactly `grafana_dashboard: "1"` (string "1", not number, not "true").
2. ConfigMap's `data` key doesn't end in `.json` — sidecar skips it.
3. JSON doesn't parse — sidecar writes it anyway, Grafana's main container logs a parse error.
4. `datasource.uid` references a UID that doesn't exist (common when dashboard was exported from a different cluster).

## Recipe 6 — dashboard renders but a panel is empty

Every `expr` should return non-empty on a steady-state cluster. Before committing, probe every panel's PromQL:

```sh
# extract all exprs from a committed dashboard ConfigMap
kubectl get cm -n <ns> <cm-name> -o jsonpath='{.data.*}' | \
  mise exec -- jq -r '.panels[] | .targets[]? | .expr' | rg -v '^$'
```

Then feed each into Recipe 2. Any `length 0` response means the panel will show "No data" — fix the expr or accept and document why.
