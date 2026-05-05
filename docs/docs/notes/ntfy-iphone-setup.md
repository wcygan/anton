# Subscribing the iPhone to anton's ntfy server

This is the operator-side setup for receiving Alertmanager push notifications on iPhone via the self-hosted ntfy server in the cluster. It does **not** describe how the cluster-side ntfy was deployed — that's covered by ADR 0026 and the manifests at `kubernetes/apps/observability/ntfy/`.

## What you're wiring up

```
[Alertmanager in cluster]
     │ POST /<topic>
     ▼
[self-hosted ntfy on cluster]
     │ poll-request (message ID only)
     ▼
[ntfy.sh]              ← APNs/Firebase relay
     │ silent push
     ▼
[ntfy iOS app on iPhone]
     │ on receipt, fetches body from
     ▼
[https://ntfy.<tailnet-name>.ts.net/<topic>/<message-id>]
     ↑
   requires Tailscale on
```

Push notifications transit ntfy.sh as a "wake-up" signal containing only the message ID. The actual alert body never leaves the cluster — the iOS app fetches it directly from your server over Tailscale.

## Prerequisites

1. **iPhone is on Tailscale, with always-on enabled.** Tailscale > VPN settings > "Connect on Demand" or always-on. The body-fetch leg fails without Tailscale, and a failed body fetch yields a degraded or missing notification. There is no architectural fallback for this — it is the trade-off of self-hosting ntfy with iOS.
2. **You can resolve `ntfy.<tailnet-name>.ts.net` from the iPhone.** Open Safari with Tailscale on and visit it; you should get a ntfy welcome page. If DNS doesn't resolve, MagicDNS isn't on for this device — fix that first.
3. **The 1Password `anton` vault item `ntfy` exists with field `topic`.** Created via the operator's CLI before scaffolding (see ADR 0026 Follow-up #1).

## Setup

### 1. Install the ntfy iOS app

[App Store: ntfy](https://apps.apple.com/us/app/ntfy/id1625396347). Free, no account required.

### 2. Retrieve the topic from 1Password

On a machine with the 1Password CLI signed in:

```sh
op item get ntfy --vault anton --field topic --reveal
```

Or from the 1Password macOS / iOS app: open vault `anton` → item `ntfy` → reveal the `topic` field.

**Do not paste the topic value into shared notes, screenshots, or this document.** Topic-as-secret is the only access control on the publish/subscribe surface — anyone with the topic name can read every alert sent to it.

### 3. Subscribe in the ntfy app

Open the app → tap the **+** button → "Subscribe to topic":

- **Topic name**: paste the value from step 2
- **Use another server**: toggle on
- **Server URL**: `https://ntfy.<tailnet-name>.ts.net`

Replace `<tailnet-name>.ts.net` with your actual tailnet's MagicDNS suffix. You can find it via `tailscale status --json | jq -r .MagicDNSSuffix` from any Tailscale-connected machine.

Save. The app immediately tests connectivity by fetching `/<topic>/json`. If it fails, see Troubleshooting below.

### 4. Verify end-to-end

Send a test notification from the cluster:

```sh
TOPIC=$(op item get ntfy --vault anton --field topic --reveal)
kubectl -n observability exec deploy/ntfy -- \
  wget -qO- --post-data='Test from operator' \
  --header 'Title: ntfy iPhone smoke test' \
  --header 'Priority: high' \
  http://localhost/$TOPIC
unset TOPIC
```

Within a few seconds the iPhone should buzz with a "ntfy iPhone smoke test" notification. If it doesn't, check Tailscale on the phone, then Troubleshooting.

To test the full Alertmanager path, send a synthetic critical alert directly to the in-cluster Alertmanager API:

```sh
AM_POD=$(kubectl -n observability get pod -l app.kubernetes.io/name=alertmanager -o jsonpath='{.items[0].metadata.name}')
kubectl -n observability exec "$AM_POD" -c alertmanager -- /bin/sh -c \
  "wget -qO- --post-data='[{\"labels\":{\"alertname\":\"NtfySmokeTest\",\"severity\":\"critical\",\"namespace\":\"observability\"},\"annotations\":{\"summary\":\"end-to-end test\"},\"startsAt\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}]' \
   --header 'Content-Type: application/json' \
   http://127.0.0.1:9093/api/v2/alerts"
```

Alertmanager waits ~30 s (`groupWait`) before firing. The notification arrives with a JSON-shaped body — verbose, but it confirms every leg works.

## Operational notes

- **What's actually delivered**: today's setup forwards Alertmanager's raw webhook JSON to ntfy. The iPhone notification will show "Alertmanager" or similar as the title and the JSON as the body. This is functional but not pretty. A future improvement (not yet built) is to template the alert into something like `{{ alertname }}: {{ summary }}` before publishing.
- **What gets routed**: only `severity: critical` alerts at the moment, per ADR 0026's conservative initial route shape. Re-evaluate after a week of operation; widen by editing `kubernetes/apps/observability/ntfy/app/alertmanagerconfig.yaml`.
- **Retention**: cluster-side ntfy holds 12 hours of message history. If you tap a notification older than 12 h, the body fetch returns 404. The notification still arrived; it's just no longer fetchable.
- **Multiple devices**: subscribing from a second device (iPad, another phone) just means repeating step 3 with the same topic. Topic-as-secret is shared.

## Rotating the topic

If you suspect the topic leaked, rotate it:

```sh
NEW_TOPIC=$(openssl rand -hex 16)
op item edit ntfy --vault anton "topic=$NEW_TOPIC"
unset NEW_TOPIC
```

Then:

1. Wait ~1 h for ESO to refresh the in-cluster Secret, or force it: `kubectl -n observability annotate externalsecret ntfy-topic force-sync=$(date +%s) --overwrite`
2. Re-subscribe on the iPhone with the new topic value (the old subscription will silently stop receiving messages).

Alertmanager's webhook URL is built from the `urlSecret` reference in the AlertmanagerConfig, so it picks up the rotated value automatically once the Secret refreshes — no manifest edit needed.

## Troubleshooting

### The iPhone never gets the test notification

In order, check:

1. **Tailscale on?** Open the Tailscale iOS app and confirm the connection is up. If "Connect on Demand" is off, this is the most likely cause.
2. **Can you reach the server?** Open Safari (with Tailscale on) and visit `https://ntfy.<tailnet-name>.ts.net`. You should get the ntfy landing page.
3. **App configured correctly?** Open the topic in the app → tap the topic name → "Send test notification". This bypasses Alertmanager and tests just the iOS-app-to-server path. If this fails, the subscription URL or topic is wrong.
4. **Cluster path working?** From a shell with kubectl access, run the smoke test from "Verify end-to-end" above. If it succeeds (the message ID returned in JSON proves ntfy accepted it) but the phone doesn't notify, the issue is downstream of the cluster — APNs propagation lag (rare, but ntfy.sh occasionally has windows where iOS push is delayed by a few minutes).
5. **AlertmanagerConfig wired?** `kubectl -n observability get alertmanagerconfig ntfy -o yaml` should show the CR; `kubectl -n observability exec alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager -- wget -qO- http://127.0.0.1:9093/api/v2/status | grep ntfy` should show the route.

### The notification arrives but the body is missing or shows "Cannot load message"

That's the body-fetch leg failing — Tailscale isn't reaching the server. Re-check step 1 in this list.

### The cluster-side ntfy pod is in CrashLoopBackOff

The cache PVC is throwaway state per ADR 0026. If something has corrupted the SQLite cache:

```sh
kubectl -n observability scale deploy ntfy --replicas=0
kubectl -n observability delete pvc ntfy-cache
# Flux will recreate both on next reconcile
flux reconcile ks ntfy -n observability
```

In-flight messages are lost (worst case 12 h of unread history). Subsequent messages flow normally.

## References

- [ADR 0026](../../../context/adrs/0026-adopt-self-hosted-ntfy-for-alerts.md) — adoption rationale, alternatives considered, follow-ups
- [ADR 0007](../../../context/adrs/0007-adopt-kube-prometheus-stack.md) — kube-prometheus-stack adoption; Trigger 4 authorised this destination
- [ADR 0012](../../../context/adrs/0012-tailscale-for-internal-remote-workload-access.md) — Tailscale operator pattern for internal HTTP exposure
- [ntfy iOS push docs](https://docs.ntfy.sh/config/#ios-instant-notifications) — upstream explanation of why iOS needs the APNs relay
- Cluster manifests: `kubernetes/apps/observability/ntfy/`
- Postmortem that motivated this work: `context/postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md`
