# Re-adoption rubric

Meta-policy that supports the `cluster-intake` skill's Step 2 (the historical-state lookup). This is **policy**, not a decision — it does not get an ADR number and it is mutable.

The April 2026 reset (see ADR 0001) removed a long list of previously-installed components. **Almost all of them are eligible for re-adoption** under the standard `cluster-intake` flow with declared intent. There are no gated categories. There is exactly one component-specific defer (ADR 0002 — Rook-Ceph), and even that does not extend to other storage approaches.

## Storage: an open exploration area for the rebuild

Storage on anton is an explicitly **open question** for the post-reset rebuild. Object, Block, and File storage alternatives are all first-class candidates for evaluation under standard `cluster-intake`. The current baseline (local-path provisioning + tested external backups) is *a starting point*, not a permanent answer.

The **only** storage decision currently locked in is **ADR 0002**, which defers **Rook-Ceph specifically** because its operational footprint (OSDs, mons, mgrs, recovery rituals) is the wrong shape for 3-node consumer hardware. ADR 0002 does **not** veto other distributed-storage approaches; it is narrowly about Rook-Ceph.

Worth exploring under standard intake — no special friction, no graveyard hit:

| Layer | Candidates worth evaluating | Notes |
|---|---|---|
| **Block** (RWO PVCs) | Longhorn, OpenEBS (Mayastor / LVM-LocalPV / Jiva), Piraeus, local-path-with-snapshots | Each has a meaningfully smaller operational surface than Ceph; intake conversation should focus on whether replication is actually needed at this scale. |
| **File** (RWX shared filesystems) | In-cluster NFS server + CSI, JuiceFS, SeaweedFS in filer mode, simpler CephFS-only operators | The question is usually "what specific workload needs RWX," and the answer often turns out to be "none yet." |
| **Object** (S3-compatible) | MinIO (standalone single-node, *not* the HA operator), Garage, SeaweedFS in object mode, OpenIO | The most likely category to land first — many homelab apps speak S3 natively. Standalone MinIO is the canonical "is S3 enough" baseline. |

Each candidate is a separate intake conversation. Bring it through `cluster-intake` with declared intent (concrete need or honest learning). The fact that anton was reset is **not** a veto on storage — it's the *reason* the storage layer is being rebuilt deliberately.

## Other reset-removed categories: standard re-adoption

These categories had components removed during the April 2026 reset (see ADR 0001 for the inventory). They are **not** gated and **do not** require special pleading — they go through the standard `cluster-intake` flow with declared intent like any other candidate.

The removal commits in `git log` for early April 2026 are not evidence that any of these components are bad; they are evidence that anton was reset and is being rebuilt deliberately. Treat the removal as historical context, not as a veto.

| Category | Components removed in the reset | Standard re-adoption path |
|---|---|---|
| **Observability** | kube-prometheus-stack, Alloy, Grafana, Loki (LGTM); Cilium scrape/dashboards; envoy-gateway PodMonitor | Concrete need: there must be a specific operational question that a single uptime probe cannot answer. Or learning intake with declared scope ("I want to learn Loki for 30 days"). |
| **Databases** (relational, NoSQL, streaming, in-memory) | CloudNativePG, Dragonfly, TiDB, Scylla, Redpanda | Concrete need: a specific app already running on anton hitting the limitation. Or learning intake with timebox + exit plan + throwaway data. |
| **Container registries** | Harbor + Harbor-Postgres + Harbor-Redis + harbor namespace; Spegel `harbor` mirror | Concrete need: a specific case where Spegel + public OCI is insufficient (air-gap, internal-only image, signed-image enforcement). Or learning intake. |
| **Demo / playground apps** | `echo`, `echo-two` | Treat as implicit learning intake with a timebox. Demo apps have a removal cost; the timebox front-loads the cleanup decision. |

## What "standard intake" means here

It means: run the `cluster-intake` skill end-to-end. Declare intent (concrete need / honest learning). Pass containment gates 1–5. If concrete need, also pass gates 6–7 and the soft score. If learning, declare timebox + exit plan. The gatekeeper's verdict lands as a new ADR via the `adr` skill.

There is **no special "you removed this, so demand a delta"** check. That was the old framing from the pre-reset graveyard, and the reset framing makes it inappropriate. Aside from the narrow Rook-Ceph defer in ADR 0002, the rebuild has no category-level friction.

## Filed-away lessons that survived the reset

These are not decisions and don't get ADRs. They're observations worth keeping handy for future intake conversations:

- **`42822fc3` (`fix(cloudflare-tunnel): switch quic -> http2`)** — every component has a tail of operational fixes, even Tier-0 ones. Cloudflared has needed multiple fixes despite being core infrastructure. When estimating intake cost, budget for the tail, not just the install.
- **`adc2ef8e` (`fix: remove Helm CRD management from Redpanda operator`)** — charts that manage their own CRDs awkwardly are a yellow flag on `Maintenance burden` in the rubric. This applies to *any* candidate, not just Redpanda.
- **The completionism trap** — "every real cluster has X" is the sentence that produced almost every removal in the reset. If a candidate's justification reduces to that sentence, it is not concrete need. The honest reframings are: declared learning intake, or "wait until the consumer arrives."
- **Compound intakes** — Harbor was app + Postgres + Redis = three intakes in a trench coat. Always count the full dependency surface, not just the headline component.
- **Second-order integration debris** — when one component leaves, every other component that referenced it generates cleanup. Future "remove an app" runbooks should `grep -r <component-name>` across the manifest tree first.
