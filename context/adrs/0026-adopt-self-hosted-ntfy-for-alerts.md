---
status: Accepted
date: 2026-05-04
deciders: ['@wcygan']
affects: observability
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0026 — Adopt self-hosted ntfy as Alertmanager's notification destination

> Anton runs a single self-hosted `ntfy` server in the `observability` namespace as Alertmanager's only push-notification destination. Alertmanager → ntfy is a cluster-internal POST to the in-cluster Service; iPhone push delivery uses ntfy.sh as an APNs relay (only the message ID transits ntfy.sh — the message body stays on the cluster and is fetched over Tailscale on tap). Topic-as-secret authentication only; long random topic name held in 1Password and pulled via ExternalSecret.

## Status

Accepted

## Context

ADR 0007 installed kube-prometheus-stack with `Alertmanager` enabled and **no routes configured** — every alert routes to receiver `"null"` and is discarded. ADR 0007's Follow-up Trigger 4 explicitly authorised adding a real destination "when the operator decides which destination alerts should flow to (Discord, email, PagerDuty, ntfy, etc.)" and noted that no new ADR is required "unless the destination adds a Tier-0 dependency."

The gap from "Alertmanager exists" to "alerts are visible" was theoretical until the **2026-05-04 flux-operator postmortem** turned it into evidence. A pod sat in `CrashLoopBackOff` for **3 days 14 hours**. The upstream `KubePodCrashLooping` rule fired correctly for the entire window. The alert routed to `null`. Nobody saw it. The root cause was unrelated to alerting (a chart NetworkPolicy missing port 8081 — see [`context/postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md`](../postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md)) but the detection failure converted what could have been a one-hour reliability incident into a 3.5-day one. A new `ClusterPodCrashLoopBackOffCritical` rule landed in commit `6ba53610` (severity=critical, for=2m). Without a real receiver, that rule is also dead on arrival.

`cluster-intake-gatekeeper` evaluated this adoption end-to-end and returned **Add (concrete need)** with score 52/58 across the strict rubric: zero hard-gate failures, no removal-graveyard hit, do-nothing strictly dominated. Operator intent declared as concrete-need (not learning-intake). The gatekeeper's hand-off chain is `adr` (this ADR) → `flux-app-author` (manifest scaffold) → `anton-cluster-health` (post-install verification + synthetic-alert end-to-end test).

ntfy ([github.com/binwiederhier/ntfy](https://github.com/binwiederhier/ntfy)) is a single Go binary, Apache-2.0, very actively maintained, with a strong fit for a homelab alert-fan-out: trivial REST `POST` interface, no external infrastructure, message persistence via SQLite. The iOS push delivery path has one structural quirk that anchors several decisions in this ADR: **iOS background processing is restricted enough that direct push from a self-hosted ntfy is not possible without an Apple Developer account + APNs cert**. The standard workaround, recommended by ntfy's own documentation and used by the homelab community, is `upstream-base-url: https://ntfy.sh` — the cluster's ntfy forwards a poll-request (containing only the message ID) to ntfy.sh, which dispatches via APNs to the iOS app; the app then fetches the actual message body from the cluster's ntfy server over Tailscale. Privacy posture: only message IDs transit ntfy.sh; bodies stay on cluster.

## Decision

Anton adopts a single self-hosted `ntfy` server with the following shape:

- **Namespace**: `observability`. Co-located with `kube-prometheus-stack` and `kube-prometheus-stack-alertmanager` so the alert path stays in one namespace and the AlertmanagerConfig CR lives next to its consumer.
- **Image**: `binwiederhier/ntfy` (Docker Hub), pinned at scaffold time and Renovate-tracked.
- **Manifest shape**: hand-authored `Deployment + Service + ConfigMap + PVC + ExternalSecret + AlertmanagerConfig`, ~80 lines total. No Helm chart adopted. Rationale: ntfy is small enough that the maintenance overhead of a third-party chart (none of the community charts are upstream-blessed) is larger than the maintenance overhead of the manifests themselves.
- **Storage**: 1 GiB PVC on the `longhorn` StorageClass, mounted at `/var/cache/ntfy/`. Holds `cache.db` (SQLite). Default retention is 12 hours of message history. **PVC content is throwaway.** Loss of the volume costs at most 12 hours of unread alert history; no recovery action needed beyond Flux re-creating the PVC. Documented here so future-me does not invent a backup obligation that is not warranted.
- **Server config** (`server.yml` via ConfigMap):
  - `base-url: https://ntfy.<tailnet-name>.ts.net` — the public-facing URL the iPhone app will fetch from.
  - `upstream-base-url: https://ntfy.sh` — the APNs/Firebase relay for iOS push. Only message IDs transit; bodies stay on cluster.
  - `cache-file: /var/cache/ntfy/cache.db`
  - `behind-proxy: true` — Tailscale Ingress fronts it.
- **Authentication**: topic-as-secret only. Single long random topic string (32+ chars), generated via `openssl rand -hex 16`, held in 1Password vault `anton` as item `ntfy` field `topic`, materialised by ExternalSecret into the AlertmanagerConfig CR. No `auth-file`, no per-topic ACLs, no admin user. Single operator, single device — the topic name is the credential.
- **Reachability for iPhone**: Tailscale Ingress per ADR 0012 Recipe A. `ingressClassName: tailscale`, hostname `ntfy`, browser-trusted TLS via Tailscale's MagicDNS Let's Encrypt path. iPhone has Tailscale always-on, so the fetch-on-tap leg works whenever the device is awake.
- **Alertmanager → ntfy wiring**: `AlertmanagerConfig` CR (per ADR 0007's Trigger 4 prescription, not an inline `.alertmanager.config` block in the HelmRelease). Cluster-internal POST to `http://ntfy.observability.svc.cluster.local/<topic>`; no Tailscale needed for the publish leg. **Initial route shape: `severity: critical` only.** Easier to broaden than to silence; the new `ClusterPodCrashLoopBackOffCritical` is critical, so it gets through. Re-evaluate the route shape after a week of operation; flip to "everything except info" if the noise level is acceptable.

The ADR 0007 Trigger 4 condition "destination adds a Tier-0 dependency" is **not** triggered — ntfy is downstream of Alertmanager (which is itself downstream of Prometheus), and a ntfy outage costs at most "alerts go to /dev/null again," exactly the state ADR 0007 already accepted at install. ntfy is therefore a Tier-2 dependency at most.

## Alternatives considered

- **ntfy.sh public service.** Simpler — no in-cluster component, no PVC, no Tailscale Ingress; just an Alertmanager webhook to `https://ntfy.sh/<random-topic>`. **Why not picked**: alert bodies (containing pod names, namespaces, possibly hostnames or other infra labels) would transit a third-party service. The self-hosted shape keeps that data on cluster while preserving iOS push (only the message ID hits ntfy.sh). Marginal cost (one Deployment + one PVC + one ConfigMap) buys a meaningful privacy improvement and makes the architecture useful for future non-alert notification streams.
- **Discord or Slack webhook.** Genuinely simpler — no infrastructure at all, just a webhook URL in 1Password and an AlertmanagerConfig. Push notifications come for free via the Discord/Slack mobile app. **Why not picked**: the operator does not actively monitor Discord or Slack on this device, and adopting one of those would couple alerting reliability to a third-party SaaS account whose retention, mobile-notification reliability, and migration path are not under operator control. ntfy is the explicit homelab-native choice — picking Discord here would be a "use what's already on my phone" reflex rather than the considered choice. Reconsider only if ntfy's iOS push reliability turns out to be substantially worse than expected.
- **Email (SMTP).** Universal, archivable, no SaaS dependency if a self-hosted MTA is acceptable. **Why not picked**: SMTP is high-friction for *push* delivery (latency, mobile filtering), and adopting it would mean either standing up an MTA (a much larger commitment than ntfy) or coupling to Gmail SMTP (the SaaS-coupling problem from the previous bullet, with worse delivery latency). For ack-and-resolve workflows on infra alerts, push beats email.
- **Pushover / Healthchecks.io / OpsGenie / PagerDuty.** All viable. **Why not picked**: each adds either a paid SaaS dependency or another login to manage, and none beat self-hosted ntfy on the privacy + push-quality + cost axis for a single-operator homelab. PagerDuty in particular is significant overkill at this scale.
- **Status quo (Alertmanager → null).** Rejected — that is the position the 2026-05-04 incident exposed as broken. ADR 0007 itself names "stops the 'alerts into the void' pattern" as the install-time invariant, deferred until a destination was chosen; the destination is now chosen.

## Consequences

### Accepted costs

- **One more long-running Deployment in the cluster.** ~50 MiB RAM, negligible CPU. Under any reasonable resource budget.
- **A 1 GiB Longhorn PVC** that is mostly empty (12h cache + cooldown). Cheap.
- **iOS push depends on ntfy.sh availability** for the APNs relay leg. ntfy.sh is operated by the upstream maintainer with strong uptime history but is technically a third-party. If ntfy.sh is down, alerts still queue on the cluster's ntfy and the iPhone app picks them up on next foreground poll (delayed, not lost). Acceptable for homelab severity.
- **Topic-as-secret has no rotation primitive in this design.** Rotation = generate a new random topic, update the 1Password item, restart the Alertmanager pod (forces config re-render), and re-subscribe on the iPhone. ~3 minutes. Documented as a deliberate design choice, not a gap.
- **No recovery runbook for the cache PVC** because there is nothing to recover. If the volume vanishes, Flux re-creates it; in-flight messages are lost; subsequent messages flow normally. Stale-link risk on iOS is bounded by the 12h cache window — a tap on a too-old notification gets a 404 from the cluster ntfy and the user moves on.
- **The `severity: critical` initial route shape will under-deliver**: warnings won't surface on the iPhone until the route is broadened. Mitigated by the existing Grafana dashboard which surfaces all alert states regardless of routing. The week-after-deploy re-evaluation is a Follow-up.

### Renovate-PR tax

One new image stream: `binwiederhier/ntfy`. Add to `anton-upgrade-audit` triage as a routine app-tier bump (no special caution). Server config in the ConfigMap is stable across minor versions.

### Restore-runbook obligation

Two separate concerns:

1. **The cluster's ntfy itself**: no runbook beyond `flux reconcile`. Stateless from a recovery standpoint (see throwaway-PVC note above).
2. **The 1Password `ntfy/topic` secret**: rotation procedure (generate new value, re-deploy AlertmanagerConfig, re-subscribe on iPhone) is captured in this ADR's Decision section and does not need its own runbook entry. The `rotate-credential` skill does not need a new sub-workflow for it.

## Follow-ups

- [ ] **Operator: create the 1Password entry.** Item `ntfy` in vault `anton`, field `topic`, value `$(openssl rand -hex 16)`. Required before scaffolding so the ExternalSecret resolves on first reconcile. (See accompanying scaffolding instructions.)
- [ ] **Hand off to `flux-app-author` / `add-flux-app` skill** to scaffold the 3-file pattern under `kubernetes/apps/observability/ntfy/`: namespace inherited from the existing `observability` namespace; `ks.yaml` with `postBuild.substituteFrom: cluster-secrets`; `app/` with `helmrelease.yaml` *not applicable* — this is hand-authored manifests, so `app/kustomization.yaml` directly lists `deployment.yaml`, `service.yaml`, `configmap.yaml`, `pvc.yaml`, `externalsecret.yaml`, `ingress.yaml` (Tailscale), and `alertmanagerconfig.yaml`. Replace the Tailscale hostname placeholder with `ntfy` and rely on `cluster-secrets` substitution for `<tailnet-name>` everywhere.
- [ ] **Post-install verification via `anton-cluster-health`** plus a synthetic end-to-end alert test: temporarily lower a benign rule's threshold (or `kubectl run` a known-CrashLoopBackOff pod in a scratch namespace), observe the iPhone notification land, revert. Document the timing observed (publish → iPhone vibration) for future expectation-setting.
- [ ] **Re-evaluate the AlertmanagerConfig route shape one week after deploy.** Flip from `severity: critical` only to "everything except info" if the noise level is acceptable; widen further if alerts are still being missed; narrow further if the iPhone is buzzing for non-actionable warnings.
- [ ] **Update `.claude/agent-memory/cluster-intake-gatekeeper/`** with the ntfy adoption so future intake rounds see the precedent (already handled by the gatekeeper agent during this intake — verify the memory append landed).
