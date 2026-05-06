---
status: In-progress
opened: 2026-05-05
closed: null
affects: observability
intent: concrete-need
related-adrs: []
review-by: 2026-06-05
---

# 0014 — Off-cluster forensics TSDB on betty

> Run a single-node VictoriaMetrics on betty as a `remote_write` target so the next silent-reboot event survives Prometheus going down with the affected node.

## Goal

The 2026-05-05 incident left an 80-minute Prometheus blackout (19:11Z–20:29Z) because the in-cluster Prometheus pod was scheduled on k8s-1 — the node that crashed. Every "what was happening before the reboot" question hit `(no data)`. Add an off-cluster, off-site `remote_write` receiver on betty so the next silent reboot leaves a queryable forensic trail. Keep it running until plan 0013 (cluster-wide silent-reboot localization) closes with a root cause identified, then decide: (a) tear down because the cluster is healthy, or (b) promote to a permanent ADR-backed off-cluster TSDB if the value justifies it.

## Acceptance criteria

- [ ] VictoriaMetrics receiving cluster-health metrics from anton, ≥7 days continuous retention without gap
- [ ] At least one anton incident window survives end-to-end in betty's TSDB and is queryable from Grafana via a betty-backed datasource
- [ ] Plan 0013 closes (root cause identified or formally abandoned), enabling a teardown-or-promote decision
- [ ] Final decision recorded: tear down per the runbook below, OR open an ADR + production-rollout follow-up plan for a permanent off-cluster TSDB

## Tasks

### Phase 1: Setup on betty

- [x] Create persistent data dir at `/home/wcygan/vmsingle-data`
- [x] Pull `victoriametrics/victoria-metrics:v1.142.0` (pinned arm64 image)
- [x] Run vmsingle container bound to the Tailscale interface only (`-p 100.119.71.22:8428:8428`), `--restart unless-stopped`, `-retentionPeriod=30d`, 1 GiB memory limit. Required `--user $(id -u):$(id -g)` (image runs as root, host dir is unprivileged) and SELinux relabel `:Z` on the volume mount (Fedora Asahi has SELinux enforcing).
- [x] Smoke-test: `curl http://100.119.71.22:8428/health` from betty returns `OK`; `ss -ltn` confirms binding only on `100.119.71.22:8428` (not LAN, not loopback). HostNetwork curl from k8s-2 also returns `OK`.
- [ ] Verify container survives a betty reboot (deferred — would disrupt this session)

### Phase 2: Wire anton → betty

- [x] Verify in-cluster reachability — **CONFIRMED**: Talos nodes themselves are tailnet members (hostNetwork curl from k8s-2 to `http://100.119.71.22:8428/health` returns `OK`), but **pods on the Cilium pod network CANNOT reach betty's tailnet IP** (curl from a regular pod times out from all 3 nodes). An egress shim is required. The Tailscale operator is already installed (CRDs `Connector`, `ProxyClass`, `ProxyGroup` available; `ts-*` ingress proxies in the `tailscale` namespace).
- [ ] Design + scaffold the egress: create a Kubernetes `Service` of type `ExternalName` annotated with `tailscale.com/tailnet-fqdn=betty.${TAILNET_NAME}`, OR a `Connector` CR. The operator spawns an egress proxy and exposes betty as a cluster-local DNS name. Postbuild-substitute `TAILNET_NAME` from `cluster-secrets` per anton convention (never commit literal tailnet name).
- [ ] Patch `kube-prometheus-stack` HelmRelease values to add a `remoteWrite` block targeting `http://betty:8428/api/v1/write` (or the chosen egress URL)
- [ ] Add a second Grafana datasource pointing at `http://betty:8428` named e.g. `Prometheus (betty)` so historical queries past in-cluster retention work in dashboards
- [ ] Verify ingestion: `curl -G 'http://100.119.71.22:8428/api/v1/query' --data-urlencode 'query=up{job="node-exporter"}'` from betty returns 3 series within 5 minutes of HelmRelease apply

### Phase 3: Monitor

- [ ] Confirm continuous ingestion for 7 days (`vm_rows{type="indexdb"}` or `count(up)` queryable across the full week)
- [ ] When the next silent-reboot fires, confirm the **failure window itself** is in betty's TSDB (the test plan 0009/0013 actually need)
- [ ] Cross-check at least one cluster-health-glance dashboard panel against the betty datasource — e.g., the new Hardware Health row + SFP+ throughput panel — confirm they render the failure window

### Phase 4: Decision (triggered by plan 0013 close, or 2026-06-05 review)

- [ ] If plan 0013 closes with root cause identified AND the off-cluster TSDB was useful → open a follow-up plan + ADR for a permanent solution (Grafana Cloud, Mimir on dedicated hardware, or productionize the betty setup with proper SOPS/Renovate/etc.). Then Phase 5 teardown.
- [ ] If plan 0013 closes without need for off-cluster forensics → Phase 5 teardown.
- [ ] If 2026-06-05 review arrives without a plan-0013 close → re-evaluate: extend, promote, or abandon.

### Phase 5: Teardown (conditional)

- [ ] Revert `kube-prometheus-stack` HelmRelease `remoteWrite` block (commit + Flux reconcile)
- [ ] Remove the `Prometheus (betty)` Grafana datasource
- [ ] `docker stop vmsingle && docker rm vmsingle` on betty
- [ ] Decide: keep `/home/wcygan/vmsingle-data` for archival query, or remove. Default: remove unless forensic value is being actively mined.
- [ ] `docker image rm victoriametrics/victoria-metrics:v1.142.0` on betty
- [ ] `close 0014 done "<closing note>"` via the planner skill

## Log

- 2026-05-05: Plan opened — 2026-05-05 incident left an 80-min Prometheus blackout because Prometheus was self-hosted on the crashed node (k8s-1, pod IP `10.42.1.167`). Plan 0013 needs forensics from the failure window to make progress. Betty is well-suited: 35 d uptime, on tailnet, off-site, aarch64 with native VictoriaMetrics image.
- 2026-05-05: Phase 1 complete. VM v1.142.0 (latest stable; original `v1.106.1` pin was old) running on betty bound only to Tailscale interface `100.119.71.22:8428`. SELinux relabel (`:Z`) and `--user 1000:987` were both required on Fedora Asahi. Self-`/health=OK`; hostNetwork curl from k8s-2 returns OK; pod-network curl from all 3 nodes times out (expected — bridge layer needed). Phase 2 reachability path: Tailscale operator egress proxy via `ExternalName` Service annotated with `tailscale.com/tailnet-fqdn`.

## References

- Related plan: [0013](0013-cluster-wide-silent-reboot-localization.md) — this plan exists to give 0013 a forensic surface
- Related plan: [0009](0009-k8s-2-k8s-3-silent-reboot-followup.md) — the broader silent-reboot investigation
- Incident this plan responds to: `../incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`
- Postmortem: `../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`
- Related ADR: [0010](../adrs/0010-persist-tailscale-node-identity.md) — confirms anton nodes run `tailscaled` (relevant to egress-path design in Phase 2)
- Cluster-side check: `kubectl -n observability get hr kube-prometheus-stack -o yaml`
- Betty-side check: `docker ps --filter name=vmsingle`
- VictoriaMetrics docs: <https://docs.victoriametrics.com/single-server-victoriametrics/>
