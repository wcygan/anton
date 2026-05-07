---
status: In-progress
opened: 2026-05-06
closed: null
affects: all
intent: concrete-need
related-adrs: [0017, 0018, 0019]
review-by: 2026-05-20
---

# 0016 — Harden Flux dependsOn graph for cluster-wide cold-start

> Cope-side complement to plans 0013 / 0014 / 0015: tighten Flux ordering so a simultaneous 3-node reboot reconciles deterministically without operator intervention.

## Goal

Anton's MS-01 nodes have demonstrated a recurring failure mode of simultaneous (or sequential within ~30 min) silent reboots; the cause-side investigation lives in plans 0013/0014/0015. Even when the cause is fixed, the cluster will continue to cold-start at random intervals (planned reboots, power events, kernel upgrades). Today only 7 of 37 Flux Kustomizations declare `dependsOn` (~19% coverage), and 3 of those edges are weak (`wait: false` on the upstream means the dep waits for `ks-applied` rather than `Ready`). On a cold start, reconcile order relies on Flux's 1h retry interval to eventually converge — every retry is a CRD race, an ExternalSecret-not-resolved Secret, an HTTPRoute-without-Gateway. Done state for this plan: every consumer that needs a CRD, secret store, or platform Gateway declares an explicit `dependsOn` to the upstream that owns it; every platform-layer Kustomization that downstreams depend on uses `wait: true` (or `healthChecks`); a deliberate 3-node cold-start drill recovers without operator intervention and the recovery time is captured by betty's off-cluster TSDB (plan 0014).

## Acceptance criteria

- [ ] PR1 lands: 5 platform `wait: true` flips + 11 consumer `dependsOn` additions (the 15-file changeset spec'd in `~/.claude/plans/handoff-cluster-wide-reboot-mellow-tarjan.md`).
- [ ] Steady-state `task reconcile` time post-PR is within 3 minutes of pre-PR baseline (deeper chain is acceptable; runaway reconcile is not).
- [ ] A deliberate 3-node simultaneous cold-start drill reaches `flux get ks -A` all-Ready without operator intervention; recovery delta is captured in betty's TSDB.
- [ ] Any new gaps surfaced by the drill are either fixed in a follow-up PR or explicitly accepted as non-load-bearing in this plan's Log.
- [ ] One of: (a) plan closes Done with the drill demonstrating clean recovery, OR (b) plan closes Done after a real cold-start event in the watch window demonstrates clean recovery (whichever comes first).

## Tasks

### Phase 1 — PR1: dependsOn graph + wait flips (this session)

- [x] Edit 5 platform-layer ks.yamls — flip `wait: false` → `wait: true`: external-secrets, envoy-gateway, multus, storage-vxlan, kube-prometheus-stack.
- [x] Edit 11 consumer ks.yamls — add `dependsOn` per the table in the handoff plan: longhorn-config, longhorn, bakery-server, echo, homepage, flux-instance, cloudflare-tunnel, kube-prometheus-stack, ntfy, harbor-config, seaweedfs-config.
- [x] Run `conventions-linter` subagent on the diff.
- [x] Verify SOPS encryption status repo-wide.
- [x] Commit and push branch; open PR referencing this plan.
- [x] Time `task reconcile` before and after merge; record steady-state delta in this plan's Log.

### Phase 2 — Cold-start drill (post-PR-merge)

- [ ] Schedule a maintenance window for a deliberate 3-node simultaneous reboot.
- [ ] Pre-drill: capture baseline metrics from betty (vmsingle at `100.119.71.22:8428`) — Kustomization-Ready timing, HelmRelease-Ready timing, pod-Ready percentage, Longhorn replica-attached count.
- [ ] Execute drill (`talosctl reboot --mode=default` on all 3 nodes within ~10s of each other; coordinate with plan 0013's reboot-discriminator instrumentation if it's live).
- [ ] Post-drill: capture the same metrics; record recovery delta vs. baseline in this plan's Log.
- [ ] Identify and triage any Kustomization that fails-and-retries during the drill; classify each as new-edge-needed vs benign.

### Phase 3 — Follow-up edges (if drill reveals more gaps)

- [ ] If pod-restart noise is observable from `Secret-not-yet-resolved`: swap consumer deps from `external-secrets` → `onepassword-store`; flip `onepassword-store/ks.yaml` to `wait: true`. One PR, ~6 ks.yaml edits.
- [ ] If Longhorn replicas race the storage-vxlan host-shim DaemonSet despite the new edge: add `healthCheckExprs` to `storage-vxlan/ks.yaml` checking the DaemonSet's per-node Ready count.
- [ ] If the drill shows specific HelmReleases lagging on Ready: add `healthCheckExprs` (cert-manager-style) on longhorn (`replicas in Ready state`) and seaweedfs (`Seaweed CR Ready=True`) for stronger Ready signals than plain `wait: true` on Helm releases.
- [ ] If Cilium / CoreDNS bootstrap timing dominates recovery (they are Helmfile-bootstrapped, not Flux-managed, so they cannot be `dependsOn`'d): document the floor and either accept it or open a follow-up plan to migrate them under Flux.

### Phase 4 — Close-out

- [ ] On terminal state (a) drill clean OR (b) real event clean: invoke `planner close 0016 done "<closing note>"`.
- [ ] If a durable architectural rule emerged worth recording (e.g. "every consumer that authors an ExternalSecret/HTTPRoute/DNSEndpoint MUST declare a dependsOn to the corresponding platform Kustomization"), hand off to the `adr` skill — likely captures the load-bearing dependsOn graph as a permanent invariant.
- [ ] Cross-link this plan from the active reboot-investigation plans (0013, 0014, 0015) so future sessions can walk between cause-side and cope-side work.

## Log

- 2026-05-06: Plan opened from a session-handoff audit. Audit found 30/37 Flux Kustomizations with no `dependsOn` and 3 of the 7 existing edges weak (`wait: false` on the upstream). Pairs with plans 0013 (reboot discriminator), 0014 (off-cluster forensics on betty), 0015 (firmware/power profile) — together cover localize → measure → fix → recover. PR1 (15 ks.yaml edits) drafted at `~/.claude/plans/handoff-cluster-wide-reboot-mellow-tarjan.md`; this plan is the durable tracker for the cope-side initiative now that the audit has progressed past one-session scope.
- 2026-05-07: PR1 landed as PR #282 squash-merged at `9054990f`, prerequisite PR #283 (dragonfly-operator switch from `HelmRelease + GitRepository(chart)` to vendored upstream manifest, merged at `36f1ead1`) fixed the flux-local CI block via allenporter/flux-local#753. Combined CI is fully green on PR #282 (Diff helmrelease/kustomization, Test, Success all pass). Steady-state reconcile timing post-merge: `task reconcile` (flux-system Kustomization only) = 6.5 s; full cascade convergence to new SHA — 39 of 40 Kustomizations Ready=True within ~5 min of merge. Two inner Kustomizations (`multus-upstream`, `whereabouts-upstream`) reconcile against their own external GitRepo SHAs (`v4.2.4@705a59ea`, `v0.9.3@c4bb29f7`), not main — that is correct and expected. **Pre-existing exception**, not regression: `registries/harbor-config` stuck at SHA `11e097a5` with `HealthCheckFailed` because `harbor-postgres-2` is in a CNPG-bootstrap-controller restart loop (`Init:0/1`) that has been visible since at least 2026-05-06T20:36 — earlier reconcile attempts at SHA `77667632` and `36f1ead1` failed identically. Documented in talos-operator memory `project_iter15_retraction_complete.md`. Does not block close of Phase 1 acceptance criterion 1, but Phase 2 cold-start drill cannot start until harbor-postgres-2 is Ready (or harbor-config's `wait: true` health-check is loosened) — surfaces a real gap in cope coverage that the drill will exercise.

## References

- **Sibling reboot plans:** [`0013-cluster-wide-silent-reboot-localization.md`](0013-cluster-wide-silent-reboot-localization.md) (cause-side discriminator), [`0014-off-cluster-forensics-tsdb-betty.md`](0014-off-cluster-forensics-tsdb-betty.md) (off-cluster TSDB on betty for retrospective drill metrics), [`0015-ms-01-firmware-power-stability-profile.md`](0015-ms-01-firmware-power-stability-profile.md) (BIOS/power profile work).
- **Driving handoff plan (PR1 spec):** `~/.claude/plans/handoff-cluster-wide-reboot-mellow-tarjan.md` — concrete file-by-file changeset, verification block, pre-commit guardrails. Lives outside the repo because it's a Claude Code planning artifact, not durable repo state.
- **Repo conventions touched:** `kubernetes/apps/CLAUDE.md` (3-file Flux pattern), `kubernetes/apps/network/CLAUDE.md` (storage-vxlan host-shim), `kubernetes/apps/storage/CLAUDE.md` (Longhorn / SeaweedFS chain).
- **ADRs scoping the storage-fabric chain:** 0017 (Multus CNI for Longhorn), 0018 (install-cni init container), 0019 (SeaweedFS chart 0.1.14 with `spec.s3`).
- **Cluster checks:** `flux get ks -A`, `kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A`, `kubectl -n <ns> get kustomization <name> -o jsonpath='{.spec.dependsOn}'`.
- **Off-cluster TSDB for drill metrics:** `100.119.71.22:8428` (betty vmsingle) — both vmui and HTTP API. Plan 0014.
