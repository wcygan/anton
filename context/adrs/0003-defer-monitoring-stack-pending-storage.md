---
status: Deferred
date: 2026-04-11
deciders: ['@wcygan']
affects: observability
intent: unknown
supersedes: []
superseded-by: null
retrospective: false
---

# 0003 — Defer monitoring stack pending object storage

> Three observability stacks (kube-prometheus-stack, VictoriaMetrics, Grafana LGTM) are documented as deferred candidates; the eventual choice is gated on object storage landing on anton for another reason.

## Status

Deferred

## Context

A monitoring stack has been on anton's mental backlog since the LGTM removal in commit `1753eec8` (`chore(observability): remove alloy/grafana/loki/prometheus-operator stack`). That removal — labelled in the historical graveyard as the **#1 completionism intake regret** — taught the lesson that installing observability *before* there are workloads to observe burns 4–8 GiB of RAM watching nothing. The lesson is recorded; this ADR exists so it doesn't have to be relearned by accidentally repeating the same install.

The interview that produced this ADR established three things explicitly:

1. **Intent is `unknown`.** The operator opted out of both concrete-need framing (no specific present-day failure) *and* timeboxed learning intake ("no learning intake, I may do this whenever I want"). This is a research-and-shelve posture, not a committed adoption.
2. **The aspirational shape is full LGTM** — metrics, logs, *and* traces in one Grafana-fronted stack — with the eventual dashboard target being a "cluster health" view (node CPU/RAM, pod restarts, Flux reconcile state) opened weekly.
3. **The trigger to revisit is dependency-driven**: when object storage lands on anton for another reason, the LGTM prerequisite is paid for free, lowering the cost-to-deploy threshold from "stand up monitoring + stand up storage" to just "stand up monitoring."

The dependency-driven trigger ties this ADR to **ADR 0002** (Defer Rook-Ceph). 0002 explicitly leaves the door open for non-Rook object/block/file storage candidates (Longhorn, MinIO, Garage, SeaweedFS, JuiceFS, NFS-via-CSI) under standard intake. This ADR is the downstream consumer of whichever object-storage path 0002's successor eventually chooses.

The cluster shape that all three candidates must fit: 3 control-plane nodes (`k8s-1`/`k8s-2`/`k8s-3`), all colocated, no dedicated workers, currently no object storage. The operator's accepted resource ceiling for an eventual monitoring stack is **~8 GiB total cluster-wide RAM** — generous by anton standards, deliberately set at the high end of what is sustainable on the current hardware so that mode choice is the constraint, not headroom.

## Decision

Anton will not add a monitoring stack today. This ADR records the three candidate architectures, their deployment modes, and per-component storage type requirements so that the eventual decision can be made quickly when the revisit trigger fires. No candidate is preferred at this time; the comparison is preserved equally so that the choice remains open to whichever shape best fits the cluster *as it exists when the trigger fires* — which may differ from today's shape.

## Alternatives considered

### Do nothing — current baseline

The status quo. `metrics-server` already provides `kubectl top` for live RAM/CPU, and `kubectl logs` covers ad-hoc log inspection. There are no alerts, no historical metrics, no traces, no dashboards.

- **What it preserves**: ~0 GiB RAM committed to observability, zero Renovate-PR tax for monitoring components, zero secret lifecycle, zero stuck-HelmRelease 3am incidents from the monitoring chart itself.
- **What it costs**: blindness to anything that doesn't manifest as a current pod-state issue. Trends, cardinality of failures, and "what was this app doing yesterday at 2pm" are all unreachable.
- **Honest evaluation**: this is the right answer until the trigger fires. The graveyard's lesson is exactly that "do nothing" loses to a monitoring stack only when there are workloads worth monitoring.

### Candidate 1 — kube-prometheus-stack

The community-canonical Prometheus stack: Prometheus Operator + Prometheus + Alertmanager + Grafana + node-exporter + kube-state-metrics, all bundled in one Helm chart from `prometheus-community`.

**Deployment modes**:

| Mode | Replicas | Notes |
|---|---|---|
| Default single-replica | Prom ×1, Alertmanager ×1, Grafana ×1 | Sane fit for 3-node anton. Loses recent in-flight scrapes if Prometheus restarts; otherwise unaffected by node reboots one at a time. |
| HA dual-replica | Prom ×2, Alertmanager ×3 | Deduplicated reads, gossip-based AM. Doubles Prometheus RAM and disk. Overkill on this hardware unless paired with Thanos for long-term storage. |
| With Thanos sidecar | Prom + Thanos sidecar per replica + Thanos compactor + Thanos store gateway | Adds long-term retention via remote object storage. Effectively turns this candidate into a hybrid that *also* needs object storage — converging on Mimir's shape. Out of scope unless adopted alongside object storage. |

**Per-component storage type requirements**:

| Component | Storage type | Size estimate | Notes |
|---|---|---|---|
| Prometheus TSDB | **File** (PVC, local-path acceptable) | 30–60 GiB at default 15d retention | The single biggest disk consumer. Anton's local-path storage is sufficient. |
| Prometheus WAL | **File** (same PVC) | included above | — |
| Alertmanager state | **File** (PVC) | <1 GiB | Notification dedup state. |
| Grafana | **File** (PVC) for SQLite, OR **external SQL** (Postgres/MySQL) | <1 GiB local | SQLite is fine for single-instance. |
| node-exporter | None (DaemonSet, hostpath reads) | — | — |
| kube-state-metrics | None (in-memory) | — | — |

**Object storage required: NO.** This candidate has no object-storage dependency in its default form. *Therefore the "object storage lands" trigger does not gate this candidate* — it could be adopted independently if the operator's stance shifts toward "metrics only, file-backed, deploy now."

**Resource estimate at default mode on anton**: ~3 GiB RAM cluster-wide, ~500m CPU steady-state, well under the 8 GiB ceiling.

**Why deferred under the current decision**: the operator's stated aspirational shape is full LGTM (three pillars), not metrics-only. If the aspirational shape changes, this candidate moves to the front of the line because it has no storage prerequisite.

### Candidate 2 — victoria-metrics-k8s-stack

The VictoriaMetrics-flavored equivalent of kube-prometheus-stack: VMOperator + VMSingle (or VMCluster) + VMAlert + VMAgent + Grafana, packaged by the VictoriaMetrics team in one Helm chart. Prometheus-protocol-compatible — `/metrics` endpoints scrape the same way — but uses VictoriaMetrics' own CRDs (`VMServiceScrape`, `VMPodScrape`, `VMRule`) and storage engine.

**Deployment modes**:

| Mode | Components | Notes |
|---|---|---|
| VMSingle | 1 vmsingle pod, 1 vmagent pod, 1 vmalert pod, 1 grafana pod | The native shape for small clusters. ~1/4 the RAM of equivalent Prometheus for the same data. Best fit for 3-node anton. |
| VMCluster | vmstorage ×N + vminsert ×M + vmselect ×K | Horizontally-scalable. Designed for high cardinality / multi-tenancy. Overkill at this scale. |
| VMAgent → external | VMAgent in-cluster, remote-write to external VM-as-a-service or Grafana Cloud | Drops local TSDB cost to zero. Trades self-containment for an external dependency and remote-write credentials. |

**Per-component storage type requirements**:

| Component | Storage type | Size estimate | Notes |
|---|---|---|---|
| VMSingle TSDB | **File** (PVC) | 10–30 GiB (~7× compression vs Prometheus) | Smaller footprint than Prometheus for the same scrape set. |
| VMAgent buffer | **File** (small PVC or emptyDir) | <1 GiB | Local persistence for remote-write retries. |
| VMAlert state | **File** (small PVC) | <1 GiB | Rule evaluation state. |
| Grafana | **File** (PVC) for SQLite | <1 GiB | Same as Candidate 1. |
| vmoperator | None (in-memory) | — | — |

**Object storage required: NO.** Same as Candidate 1 — VictoriaMetrics' single-instance and cluster modes both store on local disk. Optional integration with object storage exists for backups (`vmbackup`) but is not required.

**Integration caveat (Gate 4 yellow flag)**: VictoriaMetrics ships its own CRDs that are *parallel* to the Prometheus operator's, not built on them. Charts in the broader ecosystem ship `ServiceMonitor`, not `VMServiceScrape`. The VM operator can optionally consume Prometheus operator CRDs via a converter, but this means either (a) installing the prometheus-operator CRDs alongside VM, or (b) writing `VMServiceScrape` resources by hand for any chart that doesn't ship them. This is a recurring small tax on operating VM in a Prometheus-CRD-dominant ecosystem.

**Resource estimate at VMSingle mode on anton**: ~600 MiB RAM cluster-wide, ~200m CPU steady-state. The lightest of the three candidates by a meaningful margin.

**Why deferred under the current decision**: same as Candidate 1 — the operator's aspirational shape is three pillars, and VM is fundamentally a metrics-only stack. Logs would need a separate intake (Loki, or just stop pretending and use `kubectl logs`). Traces would need yet another (Tempo or Jaeger). At that point the comparison reduces to LGTM anyway, just assembled piecewise instead of as one chart.

### Candidate 3 — Grafana LGTM

The Grafana stack — Loki for logs, Grafana for visualization, Tempo for traces, Mimir for metrics — collected by Grafana Alloy and fronted by Grafana. The most ambitious of the three candidates and the closest in shape to the original `1753eec8` removal.

**Deployment modes**: each LGTM component independently supports three modes; combinations are typically picked uniformly across the stack.

| Stack mode | Loki | Mimir | Tempo | Realistic RAM (3-node anton) |
|---|---|---|---|---|
| **Monolithic** | single binary, 1 pod | single binary, 1 pod | single binary, 1 pod | ~3–4 GiB total |
| **Read-write split (SSD / SimpleScalable)** | reader + writer split, 2–3 pods each | reader + writer split | reader + writer split | ~5–6 GiB total |
| **Microservices (distributed)** | distributor + ingester + querier + query-frontend + compactor + ruler (6+ pods) | same distributor/ingester/querier shape | distributor + ingester + querier + compactor | 8+ GiB total — at the operator's stated ceiling, no headroom |

The **monolithic** mode is the only one that fits comfortably under the 8 GiB ceiling on a 3-node cluster while leaving room for the rest of anton's workloads. Read-write split is borderline. Microservices is the original removal commit's shape — fits but consumes the whole ceiling, which is exactly the trap that produced `1753eec8`.

**Per-component storage type requirements**:

| Component | Storage type | Backend options | Filesystem mode supported? | Notes |
|---|---|---|---|---|
| **Loki** chunks | **Object** (S3-compatible) or **File** | S3, GCS, Azure Blob, Swift, or local filesystem | Yes — officially supported | Filesystem mode is viable for low-volume single-instance Loki. |
| **Loki** index (TSDB) | **Object** (preferred) or **File** | Same as chunks | Yes | Modern Loki keeps the TSDB index alongside chunks. |
| **Loki** WAL | **File** (PVC) | local-path | Always | Required regardless of backend choice. |
| **Mimir** blocks (long-term) | **Object** (S3-compatible) | S3, GCS, Azure Blob, Swift, *or* filesystem | Yes — but explicitly **not recommended** by upstream | The biggest fork in the road. Filesystem mode "works" but Grafana docs steer away from it. |
| **Mimir** ingester WAL | **File** (PVC) | local-path | Always | Required regardless of backend. |
| **Mimir** compactor / ruler / alertmanager state | **Object** | Same as blocks | Same caveat as blocks | These reuse the configured object backend. |
| **Tempo** trace blocks | **Object** (S3-compatible) or **File** | S3, GCS, Azure Blob, Swift, or local filesystem | Yes — officially supported | Filesystem mode is viable for low-volume single-instance Tempo. |
| **Tempo** WAL | **File** (PVC) | local-path | Always | Required regardless of backend. |
| **Grafana** | **File** (PVC) for SQLite, OR **external SQL** | local-path or Postgres/MySQL | N/A | SQLite is fine for single-instance. |
| **Grafana Alloy** position state | **File** (small PVC or hostpath) | local-path | N/A | Tracks log scrape positions per file. |

**Object storage required: YES, at least for Mimir** in any production-shaped deployment. Loki and Tempo both have officially-supported filesystem modes; Mimir has filesystem mode but the upstream documentation actively discourages it. A "filesystem mode for everything" LGTM deployment is technically possible but is the only configuration of any candidate that runs against vendor guidance.

**This is the candidate that the "object storage lands on the cluster for another reason" trigger gates.** Until anton has either (a) a successor decision to ADR 0002 that brings an object-storage backend, or (b) an explicit acceptance that LGTM will run filesystem-mode-against-vendor-guidance, this candidate stays deferred even if the operator's intent shifts to "deploy now."

**Resource estimate at monolithic mode on anton**: ~3–4 GiB RAM cluster-wide, ~800m CPU steady-state. Within the 8 GiB ceiling. Note that this estimate includes Mimir, Loki, Tempo, Grafana, and Alloy *combined* — it is comparable to kube-prometheus-stack's footprint while delivering all three pillars. The resource cost of LGTM is not actually the problem people remember from `1753eec8`; the problem was running it in microservices mode with no workloads to observe.

**Why deferred under the current decision**: the object-storage prerequisite is the gating constraint, and the operator has tied the revisit explicitly to that landing for another reason. This is the candidate the operator currently *prefers* in shape (three pillars) but the dependency math defers it.

### Single-pillar reframings (not chosen, recorded for completeness)

- **Logs only — Loki by itself or even just `kubectl logs` + a TUI like `stern` / `k9s`**: If the actual gap turns out to be "I can't grep logs across pods," the answer is much smaller than any of the three full stacks. Recorded so a future-self doesn't go straight to LGTM if logs are the real need.
- **Traces only — Tempo by itself**: Traces without metrics is unusual at homelab scale; recorded only to note it's possible and would still hit the object-storage gate.

## Consequences

### Accepted costs

- **Monitoring blindness continues.** Diagnosis stays at `kubectl get` / `kubectl describe` / `kubectl logs` / `kubectl top` level. Trend visibility, alert-driven response, and post-incident historical queries are unreachable until the trigger fires.
- **Some workloads are implicitly off-limits while this is deferred.** Anything whose operational story assumes "you have a Prometheus to scrape me" or "you have a Loki to read my JSON logs" will be harder to operate. None of anton's current workloads need this; future intake decisions should note it.
- **The eventual deploy is one more intake load.** Whichever candidate is picked will incur a Renovate-PR tax, a chart-version-tracking tax, and one more line in `flux get hr -A` going forward.
- **The interview that produced this ADR is itself a sunk cost** — future-self should not redo it. If the trigger fires and the choice still feels unclear, re-read this document before re-running `cluster-intake`.

### What this preserves

- **~3–8 GiB of RAM** is not committed to dashboards nobody opens — directly the lesson from `1753eec8`.
- **Optionality.** Any of the three candidates can be picked when the trigger fires. The cluster shape and object-storage backend chosen *between now and then* determines which is cheapest to adopt at that point. Locking in a candidate today would foreclose options that might become better fits later.
- **The honesty of the current intent**. The operator explicitly opted out of timeboxed learning intake. Forcing this into an `Add (learning)` verdict for procedural neatness would contradict the operator's actual stated intent and violate the rubric's "do not lecture the user on whether their learning is worth it" rule.

## Re-adoption guidance

This ADR can be revisited under any of the following conditions:

1. **Object storage lands on anton for another reason** — *primary trigger*. Once a successor decision to ADR 0002 brings any S3-compatible backend (MinIO, Garage, SeaweedFS, JuiceFS, external Backblaze/R2/Hetzner via ESO, or eventually a re-adopted distributed store), Candidate 3's prerequisite is paid for free. At that point, run `cluster-intake` against Candidate 3 with the new storage backend named in the intake declaration. Candidates 1 and 2 also become re-evaluable but were never gated on this trigger in the first place.
2. **First incident the operator cannot diagnose with `kubectl` alone** — *concrete-need reframing*. If a real outage produces a "I cannot answer X about what happened" sentence, the intent flips from `unknown` to `concrete-need` and the full production rubric applies. Re-run intake; the past-incident sentence is the Gate 7 evidence.
3. **A stateful workload arrives that strictly requires uptime visibility** — *workload-driven reframing*. If a future workload's operational story explicitly assumes monitoring exists, the workload itself is the Gate 7 evidence. Note this is the inverse of the LGTM removal pattern: install monitoring *because* a real workload needs it, not the other way around.
4. **The operator's intent shifts to declared learning intake** — *learning reframing*. "I want to learn how PromQL works" or "I want to actually build a Grafana dashboard end-to-end" with an explicit timebox and exit plan flips this to the contained-learning rubric. Candidates 1 and 2 are the cleanest learning vehicles; Candidate 3 still needs the storage answer.

If the operator instead decides to **narrow the aspirational shape** from full LGTM to "metrics only", Candidates 1 and 2 are not gated by trigger #1 and could be re-evaluated immediately. That re-evaluation should happen as an explicit successor ADR, not as an in-place edit to this one — this ADR's body is now immutable.

## Follow-ups

- [ ] Re-evaluate when one of the four revisit triggers above fires.
- [ ] If a future ADR adopts an object-storage backend, link to it from that ADR's "downstream consumers" / Follow-ups section so the dependency relationship is bidirectional.
- [ ] If the aspirational shape narrows from full LGTM to metrics-only, write a successor ADR re-opening Candidates 1 and 2 *without* waiting for the storage trigger.
- [ ] If a workload arrives that needs monitoring before any trigger fires, write the successor ADR under `concrete-need` intent with the workload named in the Context section.
