# Anton removal graveyard

Historical record of components that were installed and later ripped out. Each entry is a lesson in what "minimal fuss" meant in practice, and why the intake rubric gates what it gates.

**Not every removal is a mistake.** Several of these (TiDB, Scylla, Redpanda, arguably Dragonfly) were honest learning experiments that served their purpose — "tried it, learned it, moved on" is the contained-learning variant of the rubric working as designed, not a failure. The entries below label intent where it's knowable. Treat removals differently depending on whether they were tuition on production intake that failed, or learning intake that completed successfully.

**Update this file** whenever a new removal commit lands. Stale history is worse than no history, because a candidate that looks novel might actually be a retry of something already rejected — or a retry of something already *successfully learned*, which is a different conversation.

**Lookup procedure** in Step 2 of the main workflow:

```sh
git log --oneline --all --grep='remove\|rip\|drop\|abandon\|descope' -i | head -50
```

## The graveyard (grouped by category)

### Storage

| Component | Commit | Lesson |
|---|---|---|
| Rook-Ceph operator + cluster | `889a9662` (`chore(storage): remove rook-ceph operator and cluster`) | Ceph on 3 consumer nodes is a distributed-storage footgun. The operational surface (OSDs, mons, mgrs, PVC lifecycle, recovery at 2am) is not justified by the availability benefit at homelab scale. If you need block storage, prefer local-path or a single-node NVMe PVC + tested backup. |

### Observability (the full LGTM stack)

| Component | Commit | Lesson |
|---|---|---|
| kube-prometheus-stack + Alloy + Grafana + Loki + (Tempo never actually landed) | `1753eec8` (`chore(observability): remove alloy/grafana/loki/prometheus-operator stack`) | Full observability was installed before there were real alerts to write. RAM spent watching a handful of stateless apps the operator never paged on. **#1 completionism intake regret in anton.** Start smaller next time — blackbox exporter + a single uptime probe is enough to answer the question "is my cluster up?" at this scale. |
| Cilium Prometheus scrape + dashboards + ServiceMonitor | `caf5d7cd` (`chore(cilium): disable prometheus/dashboards/serviceMonitor (descope observability)`) | When the observability stack came out, the bits scattered across other charts had to come out too. Lesson: observability integration in *other* components is a second-order cost of adopting a monitoring stack, paid again on removal. |
| envoy-gateway PodMonitor | `95a33ad7` (`chore(envoy-gateway): remove PodMonitor (descope observability)`) | Same pattern — monitoring hooks added to every component become a second removal wave when the monitoring stack itself leaves. |
| Grafana external exposure | `792e05a2` (`fix: remove external exposure of Grafana - internal/Tailscale access only`) | Even before the full removal, anton walked back Grafana being externally reachable. Exposing dashboards publicly was more attack surface than it was worth. |

### Databases (every one of them, removed)

| Component | Commit | Lesson |
|---|---|---|
| CloudNativePG operator | `6f51c3dd` (`chore(databases): remove cloudnative-pg and dragonfly-operator`) | Installed without a concrete app that needed Postgres. Classic "platform-first" intake error — the operator and its CRDs have ongoing upgrade cost, and when no workload arrived to justify them, the cost stood alone. **Rule for next time**: don't install a DB operator until a specific app is actively waiting for it. |
| Dragonfly operator + cluster | `6f51c3dd` + `30195ca6` (`chore(playground): remove dragonfly-cluster`) | Same pattern — added for a workload that didn't materialize. In-memory datastores without a real consumer burn RAM continuously. |
| TiDB operator + cluster | `5495950d` + `24647502` | **Intent: learning** — distributed SQL on 3 consumer nodes is explicitly not a production fit, and was never claimed to be. This was a learning experiment without the explicit contained-learning framing we have now. Under today's rubric, this would have been an **Add (learning)** with a stated timebox, and the removal would have been scheduled, not reactive. The lesson is not "don't run TiDB" — the lesson is "run it declared as learning intake with an exit plan, so the removal is a planned milestone rather than a cleanup." |
| Scylla operator + manager + cluster | `69678fa2` + `ba86a873` + `bc7474dd` | **Intent: learning** — same shape as TiDB. Wide-column stores on 3 nodes are valid learning territory. Add (learning) with a timebox would have been the right framing. |
| Redpanda operator + cluster | `70687c55` + `f8bf4b28` | **Intent: learning** — Kafka-compatible streaming without streaming consumers. Genuine learning territory for understanding Kafka semantics; fine as declared learning intake with a review date. |

**Meta-lesson from the database graveyard**: the mistake wasn't running these — it was running them *without declaring the intent*. Under today's rubric, each of these would be a valid **Add (learning)** verdict. The removal commits aren't evidence that these were bad intakes; they're evidence that the intake lacked a stated timebox, so removal happened reactively instead of as a scheduled milestone. The one intake here that was arguably a concrete-need failure was **CNPG** (listed above under Databases — added as infrastructure for apps that never arrived, which is the completionism-as-need pattern).

### Registries

| Component | Commit | Lesson |
|---|---|---|
| Harbor app | `5b70cf94` (`chore(harbor): remove harbor app (descope registry)`) | Private registry with no consumers — Flux was pulling all charts/images from public OCI anyway. |
| Harbor Postgres + Redis (its two backing stores) | `9c8cfd44` (`chore(harbor): remove harbor-postgres and harbor-redis`) | Concrete example of "app requiring its own operator + its own CRDs + its own database" from known-bad pattern #4. Harbor alone was one intake; with its two backing stores it was three intakes in a trench coat. |
| Harbor namespace | `f2e73cf7` | Final cleanup — namespaces linger after apps leave. |
| Spegel `harbor` mirror + `prependExisting` | `287a6fa5` (`chore(spegel): drop harbor mirror and prependExisting`) | Second-order integration that had to be unwound. Removing a component isn't just `flux delete ns` — other components that talked to it also need cleanup. |
| Harbor mid-life LoadBalancer changes | `c316e5e4` → `92309a0a` (`fix(harbor): switch to LoadBalancer for auth realm` → `refactor(harbor): remove dead config from migration`) | Harbor's operational cost showed up as a series of "fix harbor to work with X" commits *before* it was removed. Operational friction is a leading indicator of an eventual removal commit. |

### Demos / playground

| Component | Commit | Lesson |
|---|---|---|
| echo-two demo app | `5e1bdf78` | Demo apps are fine, but they also have a removal cost — every demo is a future cleanup commit. |
| echo demo app | `363e902f` | Same. |

## Categories that require intent declaration before re-adopting

If a new candidate falls in any of these categories, Step 2 of the main workflow **must** surface this file, and the user must state either:

1. **An explicit delta that supports a new concrete-need verdict** — scale has changed, maturity threshold crossed, a specific app now needs the backing store, etc. OR
2. **An explicit learning-intake declaration** — timebox, exit plan, throwaway data, "I want to learn X specifically." The fact that a category was previously removed is not an obstacle under learning intent; "I want to actually understand why it didn't fit last time" is a valid learning goal.

"I want to try it again" without either framing is not enough. Pick one.

1. **Distributed / HA storage** — Rook-Ceph, Longhorn (never adopted), MinIO HA. Single-node local-path + rsync to external storage is the current answer.
2. **Full observability stacks** — kube-prometheus-stack, Loki, Tempo, Jaeger, ELK, OpenSearch. Minimal metrics + single probe is the current answer.
3. **SQL / NoSQL / streaming databases without a concrete app** — CNPG, Postgres-Operator, TiDB, Scylla, Redpanda, Kafka operators, Vitess. The rule is: the app that will use it must arrive *first*.
4. **Private container registries** — Harbor, Zot, distribution/distribution. Spegel + public OCI is the current answer.
5. **In-memory caches without a concrete app** — Dragonfly, Redis operator, KeyDB. Same rule as databases.

## Valid reframings for a retry

A candidate in the graveyard can be revisited under either of these paths:

### Concrete-need reframing

- **Scale has changed** — e.g., more than 3 nodes, more than 1 user, more than one workload that genuinely benefits.
- **An upstream maturity threshold was crossed** — e.g., project reached CNCF Incubating since the removal, or shipped a new stable release line that addresses the specific pain that caused the removal.
- **A concrete present-day need now exists** — a specific app has been running for >30 days and has hit the limitation that the removed component would solve. (Not "a workload I'm about to add" — a workload that is already suffering.)

### Learning-intake reframing

- **The removal rationale was primarily learning / experimental** — some removals (TiDB, Scylla, Redpanda especially) were exactly this. Re-adopting under a new learning angle is fine: "last time I wanted to see X, this time I want to understand Y." Timebox it, state the new thing to learn, and plan the removal up front.
- **There's a specific thing about the failure mode you want to understand** — "I want to actually learn why Rook-Ceph didn't fit" is a valid learning goal. The graveyard hit becomes the *reason* for the learning intake, not an obstacle.
- **You want to see if something has changed** — upstream project matured, upgrades got easier, new maintainer, new architecture. That's a legitimate learning angle too, as long as it's declared and timeboxed.

What isn't enough: "I want to try it again" without framing, or "I need X now" when the need is still the same completionism that produced the original removal.

## Appendix: filed-away but related lessons

- **`42822fc3` (`fix(cloudflare-tunnel): switch quic -> http2`)** — not a removal, but a representative example of "ongoing operational toil per component." Cloudflared has required fixes even as a core Tier-0 component, reminding us that every installed thing has a tail of these.
- **`adc2ef8e` (`fix: remove Helm CRD management from Redpanda operator`)** — CRD management quirks inside a chart were friction even before the full Redpanda removal. Charts that manage their own CRDs awkwardly are a yellow flag on `Maintenance burden` in the rubric.
