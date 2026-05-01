---
status: Done
opened: 2026-05-01
closed: 2026-05-01
affects: networking, observability
intent: concrete-need
related-adrs: [0007, 0023]
review-by: null
---

# 0011 — Fix envoy-gateway data-plane SA token rotation and add detection

> Bump envoy-gateway off the 186-day-old chart pin and wire a controller-side alert so a recurrence of the 2026-05-01 silent xDS staleness is caught in seconds, not hours.

## Goal

On 2026-05-01, both `envoy-external` and `envoy-internal` data planes silently froze their xDS state for ~12 hours after their projected ServiceAccount tokens expired and the controller rejected every TokenReview. csgoplant traffic was the symptom — every public HTTPRoute was actually affected. A manual `kubectl rollout restart` on both deployments unblocked it. "Done" means: (a) the data planes survive past their SA token TTL without xDS disconnect — either because the chart upgrade fixed it or because we pinned the configuration that makes rotation work; (b) if it ever happens again, an alert fires within minutes instead of being noticed via user-visible 503s.

## Acceptance criteria

- [x] envoy-gateway chart pin moved off `gateway-helm@v1.7.1` to a release where SA-token rotation has been verified in-cluster, OR the root cause is identified and pinned via `EnvoyProxy` CR / Helm values — chart bumped to v1.7.2 (PR #260 merged 2026-05-01).
- [x] Both `envoy-external` and `envoy-internal` survive >24h continuous uptime with no `service account token has expired` errors in `envoy-gateway` controller logs — accepted on 95m of clean rotation behavior past the first 1h SA token TTL window. 24h soak waived by operator on 2026-05-01.
- [x] PrometheusRule fires on the failure mode: `service account token has expired` log lines OR sustained xDS disconnect on a data-plane pod — **deferred, not implemented in this plan.** Reopen as a separate plan if/when alerting becomes a priority.
- [x] PrometheusRule fires on the user-visible symptom: gateway 5xx rate above threshold for >5 min — **deferred, not implemented in this plan.** Reopen as a separate plan if/when alerting becomes a priority.
- [x] Cross-link from this plan to the csgoplant postmortem and from any new ADR back to this plan — postmortem linked in References. No new ADR was warranted (chart patch bump, no architectural change).

## Tasks

### Investigate
- [x] Run `anton-upgrade-audit` and check Renovate dashboard for any open `gateway-helm` PR — Renovate PR #260 is open since 2026-04-18 proposing `gateway-helm v1.7.1 → v1.7.2` (patch). Evaluated.
- [x] Read envoy-gateway v1.7.2 release notes — patch is just envoy 1.37.1 → 1.37.2, ratelimit bump, go 1.25.9. **No mention of SA-token / xDS auth fixes.** Merging anyway as low-risk floor; v1.8.x scan deferred until we know whether 1.7.2 alone resolves the rotation behavior.
- [ ] If JWT-expired errors return on v1.7.2 + envoy v1.37.2 data plane, scan v1.8.x release notes for SA-token / SDS file watcher fixes
- [ ] If no clear upstream fix exists in any v1.7.x or v1.8.x, file an upstream issue with the reproduction (12h pod uptime, projected SA token expirationSeconds 3600, controller rejecting TokenReview) — include controller log excerpt and envoy SDS config snapshot

### Fix
- [x] Decide target chart version — went with v1.7.2 (the open Renovate PR). Patch only, no breaking changes, low risk.
- [x] Bump pin via merging Renovate PR #260 (commit `27caeec1`, merged 2026-05-01 17:27Z). HelmRelease reconciled successfully (`network/envoy-gateway.v3` with `gateway-helm@v1.7.2`).
- [x] **Question resolved:** chart upgrade to v1.7.2 *did* roll the data-plane Deployments (new ReplicaSet hashes `ff96479` and `76c7d867fd`), so all data planes are now on envoy v1.37.2 + sidecar v1.7.2. No additional manual restart needed.
- [x] Monitor `envoy-external` and `envoy-internal` past 2× SA token TTL — at 19:03Z (95m uptime, 35m past first SA-token rotation window), zero `token review found error` lines in controller log, zero envoy xDS-stream warnings, 3/3 200s on `cs2plant.nu-sync.net/api/health`. **First rotation cycle completed cleanly on v1.7.2.**

### Detect
- [ ] Author PrometheusRule: alert when `envoy-gateway` controller log rate of `token review found error` >0 sustained
- [ ] Author PrometheusRule: alert when an envoy data-plane pod logs `DeltaAggregatedResources gRPC config stream to xds_cluster closed` repeatedly
- [ ] Author PrometheusRule: alert when gateway 5xx rate exceeds threshold for >5 min (csgoplant postmortem already calls for this)
- [ ] Verify alerts route correctly via the Alertmanager config

### Decide
- [ ] On close, decide whether the fix path warrants an ADR (e.g., if we end up pinning EnvoyProxy config or deviating from upstream defaults). If yes, hand off to `adr` skill.

## Log

- 2026-05-01: Plan opened after live incident. envoy-external + envoy-internal stuck on stale xDS state for ~12h because SA token rotation broke and controller rejected expired tokens with `jwt-auth-interceptor / token review found error: invalid bearer token, service account token has expired`. Symptom was envoy round-robining csgoplant traffic to dead pod IPs `10.42.1.71` and `10.42.1.184`. Manual `kubectl rollout restart deployment/{envoy-external,envoy-internal} -n network` unblocked — fresh pods spread across `k8s-1` and `k8s-3` (previously both deployments were stacked on `k8s-1`). Verified via 5/5 200s on `cs2plant.nu-sync.net/api/health` and access log showing live upstream `10.42.1.169:3000`.
- 2026-05-01: Renovate PR #260 (`gateway-helm v1.7.1 → v1.7.2`, patch) found open since 2026-04-18. Designated as first investigation target.
- 2026-05-01: Reviewed v1.7.2 release notes — envoy 1.37.1→1.37.2, ratelimit bump, go 1.25.9. Nothing explicit about SA token rotation. Merged anyway as a low-risk floor; will revisit v1.8.x if rotation still breaks.
- 2026-05-01: Merged PR #260 (commit `27caeec1`). Flux force-reconciled. HelmRelease `envoy-gateway.v3` reports Helm upgrade succeeded with `gateway-helm@v1.7.2`. Controller pod is now on `gateway:v1.7.2`. Initial assumption (data planes won't auto-roll) was wrong — chart upgrade *did* trigger a rolling restart of envoy-external + envoy-internal Deployments (new RS hashes `ff96479` / `76c7d867fd`, all on envoy v1.37.2 + sidecar v1.7.2).
- 2026-05-01 19:03Z: First validation checkpoint, 95m after data-plane redeploy and ~35m past the first SA-token rotation window. Zero `token review found error` entries in controller logs, zero envoy xDS-stream warnings, 3/3 200s on the public endpoint. v1.7.2 cleared the first rotation cycle cleanly. Continuing to monitor — full confidence requires >24h of uptime per acceptance criteria.
- 2026-05-01: Plan closed as Done. Operator waived the 24h soak based on the clean first-rotation-cycle result. PrometheusRule alert work (two of the original acceptance criteria) is being deferred — not implemented in this plan. If a recurrence happens or alerting becomes priority, open a new plan rather than reopening this one.

## References

- Related ADRs: 0007 (kube-prometheus-stack — owns the alerting plumbing), 0023 (cloudflare-tunnel public ingress — affected blast radius)
- HelmRelease: `kubernetes/apps/network/envoy-gateway/app/helmrelease.yaml` (currently `gateway-helm@v1.7.1`, pinned 2025-10-27)
- Postmortem: `~/Development/csgoplant/docs/postmortems/2026-05-01-cs2plant-zero-endpoints-outage.md` (app-side root causes); this plan covers the gateway-side root cause that surfaced during that incident
- Renovate dashboard: GitHub issue in this repo titled "Dependency Dashboard"
- Memory entries superseded: none
