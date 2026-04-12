---
status: Accepted
date: 2026-04-11
deciders: ['@wcygan']
affects: storage
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0006 — Adopt SeaweedFS for object storage

> SeaweedFS via seaweedfs-operator is anton's Object-category pick under the ADR 0004 framework: S3-gateway-only shape (no filer), SeaweedFS replication='000' so Longhorn owns durability, master HA on all 3 nodes, S3 pod replicas ≥ 2. Install gated on Longhorn landing for the LGTM successor to ADR 0003.

## Status

Accepted

## Context

ADR 0004 ("storage stack framework") committed anton to a best-of-breed shape with a yellow-flagged shortlist for Object — Garage, SeaweedFS, Pigsty-MinIO as transitional fallback — and deferred the concrete pick to a successor. ADR 0005 ("adopt Longhorn for block storage") then picked Longhorn as the Block successor, with install gated on the monitoring-stack successor to ADR 0003. This ADR is the Object successor in that chain.

The concrete-need anchor is an **LGTM monitoring stack** (Grafana Loki + Mimir + Tempo) as the successor to ADR 0003. All three LGTM components have a *hard* S3 dependency — Loki chunks, Mimir blocks, and Tempo traces all want object storage as their primary backend. Object is squarely on the critical path; ADR 0003's "object storage lands for another reason" trigger fires the moment this ADR's install executes. Steady-state footprint was interviewed at **100–300 GB** for the homelab scale (~2 weeks of logs at low verbosity, ~30 days of metrics at default resolution, ~3 days of traces). Well inside the ~3 TB usable ceiling Longhorn 2-replica provides on anton's 6× 1 TB SSDs.

Upstream status of **SeaweedFS** and **seaweedfs-operator**, verified directly on 2026-04-11:

| Artefact | Facts | Source |
|---|---|---|
| `seaweedfs/seaweedfs-operator` default branch | `master` | GitHub repo metadata |
| Last push to master | **2026-04-10 02:01:52Z** (≈24 h before this ADR) | GitHub API `repos/.../commits` |
| Recent merges | PR #202 "ingress for volume/filer/S3" (2026-04-10), **PR #200 "standalone S3 gateway"** (2026-04-09) | GitHub API |
| Latest operator binary release | `seaweedfs-operator-0.1.13` (2026-02-03) — still pre-1.0 | GitHub releases |
| Latest Helm chart release | `1.0.11` (2026-02-03) — monthly cadence Jan/Feb 2026 | GitHub releases |
| Published Helm repo | `https://seaweedfs.github.io/seaweedfs-operator/` — Flux install example in the README | README |
| License | Apache-2.0 | GitHub repo |
| Star count / open issues | 291 stars / 36 open issues / not archived | GitHub repo |
| README "Maintenance and Uninstallation: TBD" warning (cited in pre-ADR research memo) | **No longer present** in current README | README HEAD |

The PR #200 "standalone S3 gateway" merge is load-bearing for this decision. Before 2026-04-09, the `Seaweed` CRD only deployed a full master + volume + filer + s3 stack; an Object-only use case had to skip the operator and use a raw Helm chart. That constraint lifted one day before this ADR was written — the operator now natively supports a gateway-only shape. This ADR adopts that shape; the implications are discussed in "Decision" and "Alternatives considered".

The binding ADR 0005 precedent on **1 Gbit network discipline** also constrains this ADR: ADR 0005 chose 2-replica Longhorn over 3-replica specifically because rebuilds saturate the link on consumer hardware. The same reasoning applies here — SeaweedFS-layer replication on top of Longhorn-layer replication would double write amplification on that same 1 Gbit link, which is exactly the kind of choice ADR 0005 already rejected.

Interview on 2026-04-11 fixed four architectural decisions that shape the install:

1. **Install timing**: gated on Longhorn landing (which is itself gated on the ADR 0003 monitoring successor). Same trigger as 0005 — storage lands with its consumer, anti-completionism per ADR 0001.
2. **Consumer**: LGTM with hard object dependency (not VictoriaMetrics or kube-prometheus-stack).
3. **Failure-mode fear**: "SeaweedFS being the wrong shape for LGTM entirely." Reading: optimize for small surface area and cheap wholesale swap, not for maximal durability. This directly drives the gateway-only shape and the `replication='000'` pick.
4. **Regret shape**: "hitting a scale wall the single S3 pod can't handle." Reading: configure for horizontal growth from day one — S3 pod replicas ≥ 2 and master HA on all three nodes, not replica=1 + master=1 minimalism.

## Decision

Anton adopts **SeaweedFS via seaweedfs-operator** as its in-cluster S3 backend with the following shape:

- **Deployment mode**: **S3-gateway-only**. Master + volume + S3 pods. **No filer.** Uses the standalone-S3 path from PR #200 merged upstream on 2026-04-09.
- **SeaweedFS replication string**: `000`. Longhorn owns durability; SeaweedFS does not double-replicate over the same 1 Gbit link Longhorn is already competing on. (This is the SeaweedFS equivalent of ADR 0005's "2-replica, not 3" choice.)
- **Master**: `replicas: 3`, one per node, quorum-tolerant. Survives a single node loss without an endpoint outage.
- **Volume servers**: one per node on Longhorn-backed PVCs. The initial `volumeSizeLimitMB` and per-pod request are picked at scaffold time against the 100–300 GB LGTM budget, not locked in this ADR.
- **S3 gateway pods**: **`replicas: 2`** minimum from day one, fronted by a ClusterIP Service and exposed via `HTTPRoute` on `envoy-internal`. Not a single SPOF — directly answers the "scale wall on single S3 pod" regret shape.
- **Filer**: **not deployed.** No named RWX workload exists and ADR 0004 defers File explicitly. A future successor ADR adds the filer if/when a concrete RWX need is named; the operator's `Seaweed` CRD supports adding it in place without a full reinstall.
- **Backing storage**: Longhorn `longhorn` StorageClass with `numberOfReplicas: 2, dataLocality: best-effort` (per ADR 0005). Every SeaweedFS pod's PVC is Longhorn-replicated; any node loss drops at most one SeaweedFS pod *and* its PVC stays accessible on the surviving replica.
- **Version pin**: the **first seaweedfs-operator Helm chart release that ships the PR #200 standalone-S3 path** (i.e. the first release after 1.0.11). At install time, if that release has not yet shipped, hold install — do not run a master-branch build of the operator into the cluster.
- **Webhook gotcha**: initial HelmRelease values set `webhook.enabled: false` to work around the `seaweedfs-operator-webhook-server-cert` bootstrap issue documented in the README; a follow-up commit flips it back to `true` after the operator has reconciled once.
- **IAM**: the operator supports IAM (Identity and Access Management) embedded in the S3 server on port 8333. **Not enabled at install time**; LGTM will use a static access-key/secret-key pair stored in an `ExternalSecret` from 1Password. IAM is a follow-up if a second S3 consumer arrives.
- **Install timing**: **accepted-but-deferred install**, same pattern as ADR 0005. Scaffolding and HelmRelease fire only when the monitoring-stack successor to ADR 0003 names LGTM as its concrete consumer. Dependency order inside that successor is: Longhorn green → SeaweedFS green → LGTM green.
- **Upgrade discipline**: every seaweedfs-operator minor bump is tested in a scratch namespace with a throwaway `Seaweed` CR before promoting to the production namespace. CRD migrations specifically — the operator is still pre-1.0 at the binary level (0.1.x) even though the Helm chart is at 1.0.x. Renovate PRs for the chart are labelled for `upgrade-auditor` review.

## Alternatives considered

### Garage v2.2.x — rejected after correcting ADR 0004's stale upstream claim

**Retraction of ADR 0004's Garage shortlist row.** ADR 0004's Object shortlist row for Garage stated: *"main-v2 last commit 2024-12-17 (~16 months stale), 88 tags, AGPL-3"*. Independent verification on 2026-04-11 shows this is wrong:

- `main-v2` HEAD as of this ADR is **`9969c3e5999ce5f7077b36ffffc6b9d535fd83f6`** — a CORS website-configuration fix (#1392) committed **2026-03-22T17:09:16Z** (≈3 weeks before this ADR, not 16 months).
- Garage **v2.2.0** shipped **2026-01-24** following a v2.0.0 → v2.1.0 → v2.2.0 quarterly cadence that started 2025-06-14.
- A parallel **v1.3.1** LTS release shipped the same day (2026-01-24), confirming Garage's v1 branch is still maintained for conservative users.
- Source: `git ls-remote https://git.deuxfleurs.fr/Deuxfleurs/garage` + the Deuxfleurs Gitea `/api/v1/repos/Deuxfleurs/garage/{branches,releases}` endpoints.

ADR 0004's Garage row is therefore factually incorrect but — per anton's ADR immutability rule — is **not edited**. This retraction is the canonical correction; readers should cite it alongside any future reference to 0004's Object shortlist.

With the staleness caveat gone, Garage is architecturally the cleanest candidate in 0004's shortlist: single binary, ~50 MB RAM per pod (per community reports), Rust, small surface, disciplined quarterly releases, published Helm chart in `script/helm`, and a near-perfect anton-shape implementation writeup from the Sneekes blog. It is a legitimately better minimum-viable architecture than SeaweedFS by most measures.

**Why rejected anyway**: the operator (@wcygan) explicitly picked SeaweedFS during the 2026-04-11 interview, with full disclosure of Garage's corrected status. The decision rests on factors outside the upstream-health comparison: SeaweedFS's Kubeflow Pipelines 2.15 "default S3" blessing, the Apache-2.0 license vs. Garage's AGPL-3 (not binding for homelab use, but a softer preference), the just-merged PR #200 making operator-managed gateway-only viable, and the operator's explicit Flux deployment documentation. This is a deliberate trade of architectural minimalism for operator-managed lifecycle. The regret case — "in 6 months the Garage shape looks obviously right" — was interviewed directly and ranked lower than the scale-wall regret shape.

**Supersession trigger specific to Garage**: if the decision-points above flip (seaweedfs-operator stalls, the Kubeflow blessing evaporates, the PR #200 path regresses, or operational experience on anton proves SeaweedFS too heavy), a successor ADR swaps to Garage v2.x. The wholesale swap is cheap precisely because this ADR's shape is gateway-only with no filer state to migrate.

### Raw SeaweedFS Helm chart without the operator — rejected

The pre-ADR research memo (`.claude/agent-memory/cluster-intake-gatekeeper/project_s3_shortlist_apr2026.md`) recommended skipping seaweedfs-operator entirely and deploying SeaweedFS via its raw community Helm chart, because the operator was pre-1.0 and the README carried a "Maintenance and Uninstallation: TBD" warning.

**Why rejected**: upstream verification on 2026-04-11 found the operator substantially healthier than the memo reported. Commits landed yesterday, the README's TBD warning no longer appears, the Helm repository at `https://seaweedfs.github.io/seaweedfs-operator/` is published, and the README carries a worked FluxCD install example. Deploying the raw chart would discard the operator's CRD-driven upgrades, the standalone-S3 path from PR #200, and the embedded IAM support for no material benefit.

### Full-stack SeaweedFS (filer + master + volume + s3) with `replication='010'` — rejected

This is the operator-idiomatic shape — deploy all four components, let SeaweedFS do 2-copy replication at the volume layer (`010` = one replica on a different "rack", with each k8s node mapped to a rack).

**Why rejected**: (1) stacks 2× SeaweedFS amplification on top of Longhorn's 2× amplification for 4× total write traffic on a 1 Gbit link, directly contradicting ADR 0005's 1 Gbit discipline. (2) The filer introduces stateful metadata that would need to be migrated or re-provisioned on any CRD breakage. (3) Pre-positioning the filer for File RWX is speculative — the interview confirmed no named RWX workload is on the horizon.

### Full-stack SeaweedFS with `replication='000'` — rejected

Same deployment shape as the previous alternative but with SeaweedFS replication disabled. Removes the 1 Gbit amplification concern.

**Why rejected**: the filer is still deployed with no consumer, violating ADR 0001's anti-completionism principle the same way ADR 0004 warned about it. The gateway-only shape from PR #200 is strictly smaller and loses nothing this cluster actually uses.

### Pigsty MinIO fork (`pgsty/minio`) — rejected

The research memo included this as the third shortlist entry, explicitly tagged "transitional fallback only, do not lead with it." Single-maintainer fork of MinIO after the parent `minio/minio` repository was archived in early 2026.

**Why rejected**: single maintainer is a worse supply-chain risk than a pre-1.0 operator with an active multi-person project behind it. If SeaweedFS-via-operator regresses in a way that forces a wholesale swap, Garage v2.x is now the clearly-better fallback, not this fork.

### Install Object now on local-path-provisioner — rejected

Would scaffold SeaweedFS today backed by the existing `local-path` StorageClass, without waiting for Longhorn. Unblocks any workload that wants S3 semantics before the monitoring-stack successor to ADR 0003 lands.

**Why rejected**: violates ADR 0005's precedent and ADR 0001's anti-completionism. An "installed, unused" SeaweedFS is exactly the shape that produced the cluster-reset ADR. Also forces a data migration from local-path to Longhorn the moment Longhorn lands, which is pure churn.

### Defer Object, run LGTM on filesystem backends — rejected

Mimir, Loki, and Tempo all support a `filesystem` backend that writes chunks/blocks/traces to a local volume instead of S3. This would dodge the Object decision entirely at the cost of no horizontal scaling, no long-term retention tiering, and a dramatically harder backup story.

**Why rejected**: rewrites ADR 0003's "object storage lands for another reason" trigger into "object storage is no longer required," which is a framework-level change that belongs in a successor to 0003, not a workaround in 0006. The operator's intent declared on 2026-04-11 includes learning the S3-on-k8s pattern specifically, which the filesystem-backend escape hatch sidesteps.

### Master HA replicas=1 — rejected

Single master pod, minimal resource footprint. Accepted in many homelab writeups.

**Why rejected**: directly contradicts the interviewed regret shape ("scale wall on single S3 pod"). Any node reboot takes the S3 endpoint down until the master is rescheduled. Master pod footprint is ~50 MB RAM each per community reports; the cluster has 16 GiB per node minimum and this is a trivial cost.

## Consequences

### Accepted costs

- **Bleeding-edge adoption of a 1-day-old upstream PR.** PR #200 merged 2026-04-09; this ADR is written 2026-04-11. The gateway-only path has had ≈48 hours of community use. Mitigation: install is deferred (probably weeks to months) and pinned to a released Helm chart, not a master-branch build. If PR #200 regresses in review, the release that contains it will reflect that.
- **Pre-1.0 operator CRD surface.** The operator binary is at `0.1.13`. CRD schemas may change in backwards-incompatible ways across versions. Mitigation: upgrade discipline policy (scratch namespace before promotion) and the wholesale-swap plan.
- **Triple-layer storage dependency for LGTM**: LGTM → SeaweedFS pods → Longhorn PVCs → Talos disk. A break in any layer breaks monitoring observability. This is intrinsic to the "best-of-breed, two tools" shape from ADR 0004, not a new cost introduced here.
- **Second Tier-0 dependency** once installed. SeaweedFS outage = every S3 consumer is broken. Today that's LGTM; tomorrow it may include more. Same pattern as Longhorn's Tier-0 elevation in ADR 0005.
- **No RWX today.** Explicitly by design, matching ADR 0004's File-deferred framing and the interviewed "maybe eventually, nothing named" horizon. A future RWX workload forces a successor ADR to add the filer.
- **IAM is off.** LGTM will use a single static key pair out of 1Password via ESO. Acceptable because the S3 endpoint is internal-only (behind `envoy-internal`) and the cluster has one Object consumer. Flip to embedded IAM if/when a second consumer arrives.
- **Renovate PR tax.** One more Helm chart tracked, plus whatever cadence the operator settles into post-1.0. Adds to `upgrade-auditor`'s weekly budget.
- **AGPLv3-vs-Apache-2.0 decision locked.** By picking SeaweedFS, future homelab-internal sharing is unaffected — neither license binds here — but if any code is ever packaged or distributed from anton, the license surface is entirely Apache-2.0 which is the less-friction outcome. Noted for completeness.
- **Webhook bootstrap gotcha** is a known operator defect requiring the two-step `webhook.enabled: false → true` dance documented in the README. Minor operational tax but must be captured in the scaffold PR's description.
- **Backup story unchanged.** SeaweedFS + Longhorn protect against node loss. They do not protect against accidental delete, app corruption, ransomware, or full cluster rebuild. The outstanding backup ADR from 0004 and 0005 remains morally required before any irreplaceable-data workload lands.

### What this preserves

- **ADR 0004's best-of-breed split** — Longhorn owns Block, SeaweedFS owns Object. A regression in one does not take the other down. Deliberate extra install cost, already justified in 0004.
- **ADR 0005's 1 Gbit discipline** — `replication='000'` is the SeaweedFS analogue of 2-replica Longhorn. Write traffic stays inside Longhorn's replication envelope rather than doubling.
- **ADR 0001's anti-completionism** — nothing ships until LGTM is ready to install. No filer-waiting-for-a-workload. Gateway-only is strictly the minimum viable for the one consumer on the horizon.
- **Small failure surface** — the interviewed failure fear was "SeaweedFS being the wrong shape for LGTM entirely." Gateway-only with no filer and no SeaweedFS-layer replication is the smallest installable shape; wholesale swap to Garage is a `flux delete` + new `add-flux-app` scaffold away, not a filer-migration saga.
- **Garage optionality** — the retraction above makes Garage a first-class fallback with corrected, verified status. A future supersession would not need to re-research Garage's upstream health.
- **ADR 0003's unblock trigger** stays intact. The moment this ADR's install fires, "object storage lands on anton for another reason" is true, and the monitoring-stack successor to 0003 can proceed.

## Re-adoption guidance

Not applicable — this ADR is `Accepted`, not `Reverted`. Supersession conditions (the anton-style equivalent for a forward decision):

1. **seaweedfs-operator CRD migration damages production state** — e.g. a Helm chart upgrade reconciles away `Seaweed` resources or silently drops volume metadata. Write a successor ADR that switches to the raw SeaweedFS Helm chart *or* wholesale-swaps to Garage. The gateway-only shape is intentional so this swap is cheap.
2. **seaweedfs-operator project stalls** — e.g. two consecutive quarters with no merges, or PR #200 regresses in a release. Write a successor ADR that swaps to Garage v2.x (the retraction in this ADR ensures Garage is still viable).
3. **Concrete RWX workload arrives** (media stack, Nextcloud, ML pipelines sharing state, etc.). Write a successor ADR that adds the filer to the existing `Seaweed` CR. This is an incremental amend, not a wholesale swap.
4. **LGTM scale wall hits a single-replica bottleneck** before horizontal scaling is enabled. Write a successor ADR that bumps S3 replicas, master replicas, or both — same architecture, tuned parameters.
5. **SeaweedFS is dramatically more operationally expensive than expected** during the first 6 months. Write a successor ADR swapping to Garage under the "interviewed regret shape" condition #4. The wholesale-swap plan is already in place.
6. **ADR 0004 hard constraints relax** (external S3 becomes acceptable, or a LAN NAS appears). At that point both 0004 and 0006 should be revisited together.

## Follow-ups

- [ ] **Gate**: wait for the monitoring-stack successor to ADR 0003 to name LGTM as its concrete consumer. Do not execute the remaining follow-ups until that successor is written.
- [ ] **Confirm Longhorn is green first** per ADR 0005's install sequence. SeaweedFS PVCs come from Longhorn — install order is Longhorn → SeaweedFS → LGTM.
- [ ] **Re-verify seaweedfs-operator upstream status** at install time. Specifically: confirm that a released Helm chart contains PR #200's standalone-S3 CRD field. If not yet released, hold install — do not run master-branch operator builds.
- [ ] **Scaffold the SeaweedFS Flux app** via `add-flux-app` / `flux-app-author`. 3-file pattern (`namespace.yaml` + `ks.yaml` + `helmrelease.yaml`), `HelmRepository` pointing at `https://seaweedfs.github.io/seaweedfs-operator/`, pinned version. `values:` sets `webhook.enabled: false` initially with a comment pointing at this ADR.
- [ ] **Follow-up commit flipping `webhook.enabled: true`** after the operator has reconciled once in the cluster. Documented as part of the scaffold PR description so future-self doesn't forget.
- [ ] **Write the `Seaweed` CR** with `replication: "000"`, `master.replicas: 3`, `volume.replicas: 3` (one per node), `s3.replicas: 2`, `filer: {}` omitted or disabled via the PR #200 path, and an `ExternalSecret` providing the access-key/secret-key pair from 1Password.
- [ ] **Expose the S3 endpoint** via an `HTTPRoute` on `envoy-internal` per the `expose-service` skill. Do not expose externally; LGTM is an in-cluster consumer.
- [ ] **Post-install smoke test**: scratch namespace, a throwaway S3 client pod, write/read/list a test bucket, controlled node reboot to verify the S3 endpoint survives a master-loss, verify Longhorn replica failover timing. Document in `docs/` as the baseline the next operator upgrade must not regress against.
- [ ] **LGTM integration gate**: only after the SeaweedFS smoke test passes does the monitoring-stack successor ADR install LGTM pointing at the new S3 endpoint. These are intentionally sequential.
- [ ] **Backup ADR still outstanding**. SeaweedFS `replication='000'` + Longhorn 2-replica protects against node loss only. Before any irreplaceable-data workload (beyond LGTM, which is idempotent and rebuildable) lands, the backup ADR flagged in both 0004 and 0005 must be written.
- [ ] **Update `.claude/agent-memory/cluster-intake-gatekeeper/project_s3_shortlist_apr2026.md`** with the corrected Garage upstream facts and the verified seaweedfs-operator facts from this ADR's Context. Current memo cites both incorrectly.
- [ ] **Watch the Renovate PR stream** for the first `seaweedfs-operator` chart release after `1.0.11` (2026-02-03). That release is the earliest possible install trigger for the PR #200 path.
