---
status: Accepted
date: 2026-04-18
deciders: ['@wcygan']
affects: registries
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0015 — Adopt Harbor as the in-cluster image registry

> Restore Harbor (full HA shape: 2-rep components + CNPG-3-rep Postgres + DragonflyDB-3-rep cache) as anton's OCI registry, backed by SeaweedFS S3 instead of the removed Ceph filesystem; Trivy disabled, anonymous-pull / authenticated-push, exposed via reused `192.168.1.105` LAN LoadBalancer plus reused `registry.<tailnet-name>.ts.net` Tailscale ingress, with the existing Spegel install re-mirrored to the registry.

## Status

Accepted

## Context

Harbor was a production workload on anton from **2026-01-02** (commit `feb60dd6` — "feat(harbor): add Harbor container registry with HA PostgreSQL and DragonflyDB") through **2026-04-10**, when it was removed in three sequential commits (`5b70cf94` app, `9c8cfd44` postgres+redis, `f2e73cf7` namespace) as part of the cluster reset framed by ADR 0001. Removal cause was **purely a storage cascade**: Harbor's registry component used `ceph-filesystem` RWX storage, ADR 0002 deferred Rook-Ceph indefinitely, and no S3 / RWX replacement existed at reset time. The ~3 months of operational history surfaced no Harbor-internal defects worth changing the shape over — the LoadBalancer / auth-realm work in `c316e5e4` (2026-02-11) and the Spegel mirror coexistence patches in `4a7cb9ed` and `bb2345cc` were one-time integration costs, not recurring pain. The previous install is documented in `docs/docs/notes/harbor-registry.md`.

The registry need predates Harbor. Commit `e37f6fc8` (2025-08-15, "feat: add private docker registry for NextJS app deployment") shipped a docker-distribution registry for the same use case 5 months before Harbor superseded it. Removing Harbor on 2026-04-10 left this need unfulfilled for the past week. The day-1 consumer for the restored registry is **personal app images** (NextJS-style projects, custom builds the operator pushes from a laptop), naming a concrete workload per ADR 0001's anti-completionism bar — this is not an "installed, unused" decision.

The decision composes with two storage ADRs. **ADR 0006 (SeaweedFS)** provides the S3 backend Harbor's `imageChartStorage.type: s3` path consumes — Harbor and SeaweedFS install in the same dependency chain (SeaweedFS first, Harbor follows). **ADR 0005 (Longhorn 2-replica + best-effort)** provides the block storage for CNPG and DragonflyDB PVCs; the asymmetric 2+1+2 disk layout does not block Harbor — Postgres / Redis-compat replicas are MB-scale, well inside Longhorn's per-node headroom even on the smallest node.

The operator's explicit framing during the 2026-04-17 interview was **learning / homelab-native fit** as the load-bearing reason, not network independence, not cost avoidance, not pull latency. That framing matters: a hosted registry (GHCR free tier, DockerHub Pro, Quay) would meet the technical bar at lower operational weight. The choice to restore Harbor in-cluster is partly to relearn the OCI distribution path under anton's GitOps shape, partly to keep the cluster genuinely self-contained as a learning surface. `intent: concrete-need` is correct because there is a named consumer; the Re-adoption section honours the secondary learning framing.

## Decision

Anton **adopts Harbor as the in-cluster container registry**, restored to its pre-reset shape with the following decisions locked in:

- **Product**: Harbor (`goharbor/harbor` Helm chart). Not Zot, not raw Distribution, not hosted.
- **Storage backend**: SeaweedFS S3 via Harbor's native `registry.storage.s3` path; bucket `harbor`, credentials sourced from a 1Password-backed `ExternalSecret`. No Longhorn RWX share-manager fallback.
- **Database**: CloudNative-PG operator + 3-replica Postgres `Cluster` CR. Operator is reinstalled (was removed alongside Harbor on 2026-04-10).
- **Cache**: DragonflyDB operator + 3-replica Dragonfly CR (Redis-compat). Operator is reinstalled on the same trigger.
- **Component HA**: 2 replicas each for `core`, `portal`, `jobservice`, `registry`. Single-replica jobservice fallback documented under Consequences if RWX provisioning proves painful at scaffold time.
- **Vulnerability scanning**: **Trivy disabled.** Threat model is "private cluster, trusted upstream sources"; scanning is operational tax for no marginal safety here.
- **Authentication — cluster-side pull**: **anonymous pull** (Harbor projects marked `public`). This is a deliberate deviation from the previous robot-account + per-namespace `ImagePullSecret` + `ServiceAccount` patch pattern (documented in `harbor-registry.md` §"Cluster-Wide Image Pull Configuration"). Acceptable because the registry is reachable only on tailnet + LAN, never the public internet.
- **Authentication — push**: admin password via SOPS, plus per-purpose robot accounts as needed (laptop push, future CI). Push surface remains authenticated.
- **Exposure — LAN**: Cilium LoadBalancer at **`192.168.1.105`** (HTTP, kubelet/Spegel/host-network reachable). Reused IP from the previous install.
- **Exposure — remote**: Tailscale ingress at **`registry.<tailnet-name>.ts.net`** (HTTPS, web UI + remote push). Reused hostname.
- **Exposure — internal Envoy gateway**: not used. No HTTPRoute on `envoy-internal`. Cluster workloads pull via the LAN LB; pod network reaches `192.168.1.105` directly.
- **Spegel coexistence**: re-enable the Harbor mirror config in the existing `kubernetes/apps/kube-system/spegel/` install. Spegel survived the cluster reset; only the Harbor-specific values were stripped on 2026-04-10 by `287a6fa5`.
- **Naming continuity**: reuse `192.168.1.105` and `registry.<tailnet-name>.ts.net`. Old image refs in any historical manifests / docs / muscle memory continue to resolve.
- **Install ordering**: SeaweedFS green (per ADR 0006's install plan) → CNPG operator green → DragonflyDB operator green → Harbor namespace + Postgres CR + Dragonfly CR + Harbor `HelmRelease` green → Spegel mirror config patch. Sequential; no bundling.

Hand off to `add-flux-app` / `flux-app-author` once the SeaweedFS dependency lands. A dedicated `planner` plan tracks the multi-step rollout.

## Alternatives considered

### Do nothing — operator pushes to GHCR / DockerHub for every dev iteration

Continue without an in-cluster registry. Every custom-built image goes through an external registry before deployment.

**Why rejected**: a concrete day-1 consumer is named (personal app images, predates Harbor by 5 months). Forcing every `myapp:dev` push through an external registry just to deploy locally is the friction the 2025-08-15 docker-distribution install already solved once. Doing nothing reverts to a known-bad state.

### Zot single-binary registry on SeaweedFS — rejected (kept as fallback)

Zot is a single-binary OCI-spec registry with native S3 backend, no separate database, no Redis, optional embedded scanning. Architecturally the cleanest minimum-viable shape: SeaweedFS + Zot, no operators pulled in.

**Why rejected**: the operator's "match previous install" + "HA match previous" interview answers push toward the full Harbor shape. The "learning / homelab-native" framing explicitly values relearning the Harbor + CNPG + DragonflyDB integration. Zot remains the obvious fallback if Harbor's operational weight proves regrettable in the first 6 months — wholesale swap is cheap because Harbor stores blobs in SeaweedFS S3, which Zot can read in place with a one-line config change.

### Distribution (vanilla `docker-distribution`) on SeaweedFS — rejected

The pre-Harbor shape from 2025-08-15 (`e37f6fc8`). Single binary, no UI, no auth UI, no scanning, no projects.

**Why rejected**: zero learning value (already shipped + retired this exact shape once), no UI for the projects/quotas the operator has historically used, no compelling differentiator over Zot if the goal were "lightest possible."

### Hosted registry (GHCR, DockerHub Pro, Quay) — rejected

GHCR free tier covers personal-account private images; DockerHub Pro is ~$5/mo; Quay is free for personal use. All three eliminate the entire CNPG + DragonflyDB + Spegel-coexistence + LB-IP-management surface.

**Why rejected**: the "learning / homelab-native" framing is the load-bearing reason, with full disclosure that the strict cost/benefit comparison favours hosted. Anton's intake gate accepts honest learning per global memory `feedback_learning_intake.md`, and this ADR exercises that allowance with a concurrently-named concrete consumer (so it is not pure speculation). The Re-adoption section covers the "learning value plateaus" supersession case.

### Embedded Postgres + Redis (Harbor's chart subcharts) — rejected

Harbor's chart can deploy its own internal `database` + `redis` subcharts (single-replica, PVC-backed). Skips the CNPG and DragonflyDB operators entirely.

**Why rejected**: contradicts "HA match previous" — single-replica DB/cache means the registry is briefly unavailable on any DB pod reschedule, and Harbor's internal Postgres lacks the operational tooling (PITR, online major upgrade, monitoring integration) that CNPG provides. The operators are real complexity but pay for themselves once a second consumer of either operator arrives.

### Longhorn RWX share-manager for filesystem-mode Harbor backend — rejected

Use Longhorn's `share-manager` pod to expose a Longhorn volume over NFS for RWX access, matching the previous `ceph-filesystem` shape literally.

**Why rejected**: SeaweedFS is the strategic object-storage backend per ADR 0006; routing Harbor blobs through a parallel RWX path bypasses that decision and creates a second Tier-0 storage dependency for no benefit. Harbor's S3 backend is well-trodden upstream and matches the operator's "S3-on-k8s pattern" learning interest declared in ADR 0006's Context.

### Restore-as-was *with* Trivy enabled — rejected

Match the previous install bit-for-bit including Trivy vulnerability scanning on push.

**Why rejected**: operator answered "Don't need it" in the interview — private cluster, trusted upstream sources, scanning is operational tax for no marginal safety in this threat model. Trivy can be re-enabled in a successor ADR if a future consumer changes the threat model (e.g., a CI runner pulling third-party PR builds).

## Consequences

### Accepted costs

- **Two operators reinstated as Harbor prereqs.** CloudNative-PG and DragonflyDB. Both were removed on 2026-04-10 (commits `9c8cfd44`, `f2e73cf7`); reinstalling them adds two CRDs, two operator Deployments, and two Renovate-tracked Helm charts. Both have homelab-relevant follow-on uses (CNPG for any future DB-backed app, Dragonfly for any future cache-backed app), so the reinstallation cost amortises.
- **LAN LoadBalancer IP consumed** (`192.168.1.105`) from the Cilium IPAM pool. Reused from the previous install so no net change vs pre-reset state, but still a finite resource to track.
- **Spegel containerd mirror config reinstated.** The jj log shows real friction in 2026-02-11 (`12f48802` "preserve Talos-managed containerd registry mirrors", `bb2345cc` "explicitly list registries to prevent Harbor interception"). Restoring the mirror config means re-applying those guardrails. Apply the diff from `4a7cb9ed`; do **not** re-apply `287a6fa5` (the strip commit).
- **Insecure-registry HTTP exposure on the LAN.** Kubelet on each Talos node must be configured to treat `192.168.1.105` as an insecure registry (Talos machine config patch). Same posture as the previous install; verify that patch did not survive the cluster reset and re-apply.
- **Anonymous-pull change vs previous install.** `docs/docs/notes/harbor-registry.md` and `harbor-developer-guide.md` need updating — the entire "Cluster-Wide Image Pull Configuration" section becomes obsolete. One-time documentation churn.
- **RWX gap for jobservice multi-replica.** Harbor's `jobservice` historically ran 2 replicas backed by `ceph-filesystem` RWX (commit `a1599a18`). With Longhorn (RWO by default) + SeaweedFS (object, not file), the choices at scaffold time are: (a) **single-replica jobservice** (recommended), accepting an HA regression scoped to one component, (b) Longhorn RWX share-manager just for jobservice, (c) alternate RWX provider. Single-replica is the recommended scaffold-time choice; revisit only if jobservice load makes it painful.
- **No vulnerability scanning** while Trivy is disabled. Acceptable under the current threat model. If the cluster ever hosts code from an untrusted source, this decision needs revisiting in a successor.
- **Backup gap widens.** Harbor's Postgres holds projects, users, robot accounts, quotas, replication policies — small but irreplaceable state. Image blobs in SeaweedFS are reproducible. The backup ADR flagged as morally required by ADR 0005 and 0006 becomes more pressing once Harbor's DB lands. **Recommend the backup ADR be the immediate next decision after this one.**
- **Renovate-PR tax.** Three new charts to track: Harbor, CloudNative-PG, DragonflyDB-operator. CNPG especially has occasional CRD migrations — tag for `upgrade-auditor` review on each minor bump.

### What this preserves

- **ADR 0001 anti-completionism** — named day-1 consumer (personal app images), with 5 months of registry-need history backing the concrete-need framing. Not "installed, unused."
- **ADR 0004 best-of-breed split** — Harbor uses SeaweedFS for object storage and Longhorn for block storage. Both upstream decisions stand; this ADR consumes their outputs without adding new storage primitives.
- **ADR 0006 gateway-only SeaweedFS shape** — Harbor pushes/pulls blobs via the S3 API, exactly the consumer profile gateway-only was designed for. No filer needed.
- **Previous install's documentation surface** — `harbor-registry.md` mostly stays correct with auth-section rewrite; reused IP/hostname mean image references in any historical manifests / docs / muscle memory continue to work.
- **Spegel investment** — the existing Spegel install is preserved; only the Harbor-specific mirror config is re-added.

## Re-adoption guidance

This ADR is `Accepted`, not `Reverted`. Supersession conditions (the anton-style equivalent for a forward decision):

1. **Harbor's operational weight proves regrettable in the first 6 months** (auth-realm friction returns, Spegel coexistence breaks again, CNPG/Dragonfly operator upgrades disrupt registry availability). Successor swaps to **Zot single-binary** on the same SeaweedFS bucket — wholesale swap is cheap because the blob storage layer doesn't change.
2. **Operator's stated learning value plateaus** — relearning the integration delivered the educational return, ongoing operational tax exceeds the marginal learning. Successor swaps to a **hosted registry** (GHCR is the natural successor given the operator's GitHub-centric workflow). Migration path: dual-push during transition, point Spegel at the hosted registry's pull-through path, retire Harbor.
3. **A second registry consumer arrives that needs vulnerability scanning** (CI runner, third-party builds, containers-from-customers). Successor flips Trivy back on; this is an incremental amend to the Decision section, not a wholesale swap.
4. **CNPG or DragonflyDB operator stalls upstream** (long gap between releases, security CVE without a fix). Decide per-operator: swap CNPG for an alternative HA Postgres operator (e.g., Zalando), swap Dragonfly for vanilla Redis. Harbor itself is unaffected.
5. **SeaweedFS regresses** — covered by ADR 0006's own supersession path. If SeaweedFS is replaced (e.g., by Garage v2.x per ADR 0006's supersession #1), this ADR's storage backend follows automatically; only the bucket-credential `ExternalSecret` changes.
6. **Backup ADR makes Harbor's DB protectable.** Once the long-outstanding backup ADR lands, this ADR's "Backup gap widens" Consequences entry softens; cross-link the new backup ADR from this one's References at supersession time.

## Follow-ups

- [ ] **Sequencing**: SeaweedFS install (per ADR 0006's plan) → CNPG operator install → DragonflyDB operator install → harbor namespace + Postgres CR + Dragonfly CR + Harbor `HelmRelease` → Spegel mirror config patch. Each step is its own commit; do not bundle.
- [ ] **Plan handoff**: open a dedicated `planner` plan for the Harbor restoration once SeaweedFS is green. This ADR is the *decision*; the *execution* belongs in a plan.
- [ ] **Storage credentials**: provision a SeaweedFS bucket `harbor` and an access-key / secret-key pair, store in 1Password vault `anton`, expose via `ExternalSecret`. Bucket policy: read+write for the `harbor` robot key only.
- [ ] **Talos `insecure-registry` config**: add `192.168.1.105` to each node's containerd configuration via Talos machine config patch. Confirm patch survived the cluster reset (likely did not) and re-apply.
- [ ] **Spegel mirror config**: re-apply the values diff from `4a7cb9ed` and the surrounding 2026-02-11 commits (`12f48802`, `bb2345cc`). Do not re-apply `287a6fa5`.
- [ ] **Harbor admin secret**: rotate from any pre-reset value; store new admin password in SOPS at `kubernetes/apps/registries/harbor/app/secret.sops.yaml`.
- [ ] **Project bootstrap**: create `library` project with public visibility (anonymous-pull config). Create one robot account with push permissions for laptop use.
- [ ] **Documentation rewrite**: update `docs/docs/notes/harbor-registry.md` and `harbor-developer-guide.md` — drop the "Cluster-Wide Image Pull Configuration" section, add a one-paragraph "Anonymous pull" section, refresh storage backend description (Ceph → SeaweedFS S3).
- [ ] **Smoke test**: scratch namespace, push from laptop via Tailscale (HTTPS), pull from a different namespace via `192.168.1.105`, controlled node reboot to verify the registry survives master rescheduling.
- [ ] **Renovate**: ensure `goharbor/harbor`, `cloudnative-pg/cloudnative-pg`, and `dragonflydb/dragonfly-operator` Helm charts are tracked. Tag for `upgrade-auditor` review on each minor bump.
- [ ] **Backup ADR**: this ADR's "Backup gap widens" entry should be the trigger for finally writing the long-outstanding backup ADR (flagged in ADR 0004 §Follow-ups, ADR 0005 §Follow-ups, ADR 0006 §Follow-ups, plan 0001 §Acceptance criteria). Recommend it be the **immediate next ADR** after this one.
- [ ] **Update `kubernetes/apps/CLAUDE.md`** if the `registries` namespace pattern needs documentation alongside the existing namespace examples (this is the first ADR to use `affects: registries` since the reset).
