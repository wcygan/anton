---
name: ntfy-alert-triage
description: Triage ntfy.sh-routed alerts in Anton — identify which alert fired, why it fired (or why it didn't deliver), and propose a fix. Use when "got an ntfy alert", "alert just fired", "ntfy not delivering", "AlertmanagerClusterFailedToSendAlerts", "AlertmanagerFailedToSendAlerts", "code 40014", "attachments not allowed", "iOS push missing", "test the ntfy receiver", "send a test alert", "what just paged me", "is ntfy working". Combines kube-prometheus-stack Alertmanager API, the self-hosted ntfy server (ADR 0026), and the ntfy CLI for poll/publish probes. Read-only by default; proposes edits the operator applies.
allowed-tools: Read, Bash, Grep, Edit
---

# ntfy alert triage

Ordered triage for the **anton** alert pipeline: PrometheusRule → Alertmanager → AlertmanagerConfig route → webhook → self-hosted ntfy at `ntfy.<tailnet>.ts.net` → (optionally) ntfy.sh upstream relay → device. The 2026-05-05 cascade where a 40014 from ntfy turned into a 5-minute `AlertmanagerClusterFailedToSendAlerts` loop is the canonical failure mode this skill is built around.

## Pipeline map (memorise this)

```
PrometheusRule                                Helm-managed via kube-prometheus-stack;
   │                                          Anton-authored rules live in
   │                                          kubernetes/apps/observability/kube-prometheus-stack/app/
   ▼
Alertmanager (alertmanager-kube-prometheus-stack-alertmanager-0)
   │  route: severity=critical → observability/ntfy/ntfy receiver
   │  everything else → "null" receiver
   │  (see AlertmanagerConfig at kubernetes/apps/observability/ntfy/app/alertmanagerconfig.yaml)
   ▼
webhook POST to URL from Secret ntfy-topic in observability ns
   │                                          (templated by ESO from 1Password ntfy/topic)
   ▼
self-hosted ntfy (Deployment ntfy in observability)
   │  base-url: https://ntfy.<tailnet>.ts.net
   │  upstream-base-url: https://ntfy.sh   ← iOS push relay (ADR 0026)
   │  attachment-cache-dir set since 2026-05-05 (configmap.yaml)
   ▼
device (browser at https://ntfy.<tailnet>/<topic>, or iOS via ntfy.sh poll trigger)
```

## Decision tree — which question are we answering?

| Symptom | Start at |
|---|---|
| Got an ntfy notification, want to know what it was | [§ Step 1](#step-1--what-just-fired) |
| Expected an alert, didn't get one | [§ Step 2](#step-2--why-didnt-it-deliver) |
| `AlertmanagerClusterFailedToSendAlerts` is firing | [§ Step 3](#step-3--decode-the-delivery-failure) |
| Want to verify the path end-to-end | [§ Step 4](#step-4--probe-the-pipeline-with-the-ntfy-cli) |
| Need to write/tighten a rule or receiver | hand off to `observability-integrate` |

---

## Step 1 — What just fired?

```sh
kubectl exec -n observability alertmanager-kube-prometheus-stack-alertmanager-0 \
  -c alertmanager -- wget -qO- \
  'http://localhost:9093/api/v2/alerts?active=true&silenced=false&inhibited=false' \
  | python3 -c "import json,sys; [print(a['labels'].get('alertname'),'|',a['labels'].get('severity'),'|',a['labels'].get('instance',''),'|','start:',a['startsAt'],'|','rcv:',[r['name'] for r in a['receivers']]) for a in json.load(sys.stdin)]"
```

Sort the active alerts by `startsAt` and find the one that matches the time the user was paged. Only alerts with `rcv:` containing `observability/ntfy/ntfy` actually went to ntfy; everything else routes to `null`.

**Ground-truth check before reacting**: a fresh-looking alert can be a metric/series artifact, not a real event. For `NodeUnexpectedReboot` specifically, check `/proc/uptime` directly via `talosctl`; cross-reference with the cluster-triage agent memory at `.Codex/agent-memory/cluster-triage/reference_reboot_alert_disambiguation.md`.

---

## Step 2 — Why didn't it deliver?

Two failure classes — distinguish by alertmanager behaviour.

**Class A: never reached Alertmanager** — Prometheus didn't fire it, or the rule expression doesn't evaluate to truth, or the rule isn't loaded.

```sh
# Did Prometheus load the rule?
kubectl exec -n observability prometheus-kube-prometheus-stack-prometheus-0 \
  -c prometheus -- wget -qO- http://localhost:9090/api/v1/rules \
  | python3 -c "import json,sys; [print(g['name'],'/',r['name']) for f in json.load(sys.stdin)['data']['groups'] for r in f['rules'] for g in [f]]" \
  | grep -i <alertname>

# Is the expression returning samples right now?
# (Pull the expr from the PrometheusRule yaml and test it via /api/v1/query.)
```

**Class B: reached Alertmanager but didn't deliver** — receiver matchers excluded it, or webhook delivery failed.

```sh
# Receiver matchers — only severity=critical reaches ntfy in anton.
kubectl exec -n observability alertmanager-kube-prometheus-stack-alertmanager-0 \
  -c alertmanager -- wget -qO- http://localhost:9093/api/v2/status \
  | python3 -c "import json,sys,re; print(re.search(r'route:.*?inhibit_rules', json.load(sys.stdin)['config']['original'], re.S).group(0))"
```

If your alert has `severity` warning/info, it routes to `null` by design. To reach ntfy, either bump severity in the rule or broaden the AlertmanagerConfig matcher (see ADR 0026 — "easier to broaden than to silence"; reconsider widening to "everything except info").

---

## Step 3 — Decode the delivery failure

This is the 2026-05-05 cascade flow. When `AlertmanagerClusterFailedToSendAlerts` is firing, the actual error is in the alertmanager pod logs, not the alert payload.

```sh
kubectl logs -n observability alertmanager-kube-prometheus-stack-alertmanager-0 \
  -c alertmanager --tail=200 | grep -iE 'error|fail|notify' | tail -20
```

Match the error to the table:

| Log fragment | Root cause | Fix |
|---|---|---|
| `code":40014,"http":400,"error":"invalid request: attachments not allowed"` | ntfy server has `attachment-cache-dir` unset; AM payload exceeds the ~5 KiB inline cap and ntfy refuses to spill | Add `attachment-cache-dir: /var/cache/ntfy/attachments` + size limits to `kubernetes/apps/observability/ntfy/app/configmap.yaml` (already fixed in main as of 2026-05-05) |
| `unexpected status code 401` | ntfy ACL added without updating the webhook URL secret | Refresh the `ntfy-topic` secret (1Password `ntfy/topic`) — see `rotate-credential` |
| `dial tcp ... no route to host` / `connection refused` | ntfy pod down or service IP changed | `kubectl get pod,svc -n observability -l app.kubernetes.io/name=ntfy` |
| `x509: certificate signed by unknown authority` | TLS chain regression on the cluster_gateway / cert-manager | Hand off to `anton-cluster-health` layer-5 |
| `context deadline exceeded` | ntfy.sh upstream slow; usually transient | Wait one repeat-interval; if persistent, check status.ntfy.sh |
| repeated `notify retry canceled due to unrecoverable error` for the same alert group | ntfy returning 4xx — the alert payload itself is malformed for the receiver | Decode the request body shape (see [§ Step 4](#step-4--probe-the-pipeline-with-the-ntfy-cli)) |

**Inhibit while fixing**: the cluster-failed-to-send alert will keep paging while you work. Silence it via `amtool silence add alertname=AlertmanagerClusterFailedToSendAlerts --duration=30m -c <annotation>`, or accept ~5-15 min of stale alerts after the fix lands.

---

## Step 4 — Probe the pipeline with the ntfy CLI

`ntfy` is preinstalled on the operator workstation. Reference: <https://docs.ntfy.sh/subscribe/cli/>.

The webhook URL — including the secret topic — lives in the `ntfy-topic` Secret in `observability`. **Never echo the URL to stdout or write it to a file** (AGENTS.md hard rule). Pipe it directly:

```sh
# Read the URL into a shell variable WITHOUT printing it.
# (Single command; topic stays out of shell history if HISTCONTROL=ignorespace and you prefix with a space.)
 NTFY_URL=$(kubectl get secret -n observability ntfy-topic -o jsonpath='{.data.url}' | base64 -d)
```

Then split server + topic if you need them separately:

```sh
 NTFY_SERVER="${NTFY_URL%/*}"
 NTFY_TOPIC="${NTFY_URL##*/}"
```

### Read recent deliveries (no long-running connection)

```sh
ntfy subscribe --poll --since 30m "${NTFY_URL}"
```

Use `--since 1h` / `--since 12h` for wider windows (ntfy `cache-duration: 12h` in anton's ConfigMap; older messages are gone). The `--poll` flag fetches and exits — never start a backgrounded `ntfy subscribe` from this skill.

### Send a test publish

```sh
ntfy publish --title "anton triage probe" --priority default --tags test \
  "${NTFY_URL}" "$(date -u +%FT%TZ) probe from ntfy-alert-triage skill"
```

A successful publish prints the message ID and returns 0. A 40014 here means attachments are still disabled (see Step 3). A 401 means ACLs were added without updating the secret. A 404 on the topic means the topic name doesn't match the URL path.

### Reproduce the 40014 (size-spill check)

The original cascade was triggered by Alertmanager grouping 2+ alerts into one webhook body that exceeded ~5 KiB. To verify attachments-cache works end-to-end:

```sh
ntfy publish "${NTFY_URL}" "$(python3 -c 'print("x"*8000)')"
```

Pre-fix this returned 40014; post-fix it succeeds and the message is stored as an attachment (visible in the ntfy web UI, not inline on iOS).

### Verify the iOS upstream relay

iOS push goes via `upstream-base-url: https://ntfy.sh` (ADR 0026 — only message IDs transit; bodies stay on cluster). To check the upstream poll registration:

```sh
kubectl logs -n observability deploy/ntfy --tail=50 | grep -i upstream
```

A healthy line looks like `Successfully forwarded message to upstream`. Errors mean iOS won't get push notifications even when desktop browser delivery works.

---

## Anton-specific reference

| Where it lives | What it is |
|---|---|
| `kubernetes/apps/observability/ntfy/app/alertmanagerconfig.yaml` | The route — currently `severity=critical` only (per ADR 0026 "easier to broaden than silence") |
| `kubernetes/apps/observability/ntfy/app/configmap.yaml` | ntfy server.yml — base-url, upstream-base-url, attachment limits |
| `kubernetes/apps/observability/ntfy/app/externalsecret.yaml` | ESO mapping that fills the `ntfy-topic` Secret from 1Password |
| `kubernetes/apps/observability/ntfy/app/deployment.yaml` | Single-replica ntfy v2.x, RWO cache PVC, Recreate strategy |
| ADR 0026 (`context/adrs/0026-self-hosted-ntfy-as-alertmanager-destination.md`) | Why ntfy, why upstream relay, broadening policy |
| Postmortem 2026-05-05 (alert cascade) | Captured as commit `084babaa` body — three coordinated fixes |

## Hard rules (carry-overs from AGENTS.md)

- **Never** echo, log, or write the topic URL or secret value. Always pipe `kubectl get secret ... -o jsonpath` directly into the consuming command.
- **Never** edit `*.sops.*` files in plaintext; use `sops <file>` for round-trip.
- **Never** restart the alertmanager StatefulSet to "fix" a delivery problem — the failure is upstream of AM in 99% of cases. Restart ntfy if the ntfy pod is the suspect; restart AM only if its own logs say so.
- The Vector kernel sink (`talos-log-sink`) and its 30Gi PVC are unrelated to ntfy alerting; if both are firing alerts, treat them independently.

## Hand-offs

- Rule expression is wrong / missing → `observability-integrate`
- ntfy pod itself is broken (CrashLoop, OOM, image pull) → `anton-cluster-health` layer 5, then `debug-flux-reconciliation` if it's a Flux apply problem
- Topic / token compromised or suspected leaked → `rotate-credential`
- Need to add a new alert that should reach ntfy → `observability-integrate` for the rule, then verify with [§ Step 4](#step-4--probe-the-pipeline-with-the-ntfy-cli) here
