# ClickStack — MAINTENANCE

Renovate posture, the 2026-08-02 review-by checklist, and the exit/teardown runbook. This is a throwaway 60-day eval (ADR 0028) — maintenance is about keeping it contained and tearing it down cleanly, not about long-term hardening.

## Renovate posture

Three young pins enter the audit queue for the duration of the eval (ADR 0028 explicitly accepts this rising upgrade tax):

| Artifact | Pinned at | Where |
| --- | --- | --- |
| `clickstack-operators` chart | `1.0.0` | `clickstack-operators/app/helmrelease.yaml` |
| `clickstack` chart | `3.0.0` (appVersion 2.27.0) | `clickstack-app/app/helmrelease.yaml` |
| ClickHouse operator + MongoDB MCK operator | bundled by the operators chart | (transitive — moves when the operators chart bumps) |

**Rules:**

- **Both charts are pinned to exact versions** (no ranges) — Renovate owns every bump as a discrete PR. Do not introduce ranges.
- **Treat operators-chart bumps as cluster-tier.** They carry the two operators and can churn the `ClickHouseCluster` / `KeeperCluster` / `MongoDBCommunity` CRDs. CRD/operator-major changes can break the CRs the main chart renders. Read release notes; reconcile in a low-stakes window; verify the CRs still reconcile (see `operations.md` health checks) before considering the PR done.
- **Treat main-chart (`clickstack`) bumps as their own tier**, after the operators chart is known-good. A `clickstack` major may change HyperDX naming, the `hyperdx.secrets.*` value paths the `valuesFrom` injection depends on, or the OTel collector shape — re-verify the four `valuesFrom`/`targetPath` mappings and the `clickstack-app` Service name after any major.
- **This is throwaway** — if a bump is disruptive and the eval is near its review-by date, the right move is often to **decline the bump and tear down on schedule**, not to invest in the migration. Weigh upgrade effort against remaining timebox.

Hand actual PR triage and tiered merge ordering to the `anton-upgrade-audit` skill / `upgrade-auditor` subagent; this section is just the ClickStack-specific posture they should apply.

## Review-by checklist (2026-08-02)

ADR 0028's `review-by: 2026-08-02` is **load-bearing** — a learning intake without an enforced review becomes permanent intake. At (or before) that date, produce falsifiable answers to the four success criteria, then decide.

**1. Answer the four success criteria with evidence:**

- [ ] **Criterion 1 — wide-events querying vs VictoriaLogs.** Did ClickHouse-backed querying meaningfully beat VictoriaLogs for cross-pod / ≥24h questions (ADR 0008 Trigger 1)? Cite specific queries you ran (see `usage.md`) and their latency/UX.
- [ ] **Criterion 2 — "ClickHouse too heavy" at homelab scale.** Record real CPU/RAM/operational cost of ClickHouse + Keeper + MongoDB + HyperDX (`kubectl top pods` over the eval) vs a VictoriaLogs single binary. Is the "too heavy" claim from ADR 0008 still true given ~85 GiB free RAM/node?
- [ ] **Criterion 3 — HyperDX UX vs Grafana-as-front-door.** Was HyperDX's wide-events UX worth abandoning Grafana, or did running two UIs confirm ADR 0008's fragmentation concern?
- [ ] **Criterion 4 — containment held.** Did it stay in its namespace and the logs/traces pillar, or did it drift toward a second metrics store? (You should be able to answer "no metrics ever entered ClickHouse.")

**2. Decide and act:**

- [ ] Write the **ADR 0008 successor** via the `adr` skill — either *confirm* the VictoriaLogs+Jaeger shortlist with evidence, or *re-rank* toward a ClickHouse/HyperDX backend. This is the experiment's deliverable.
- [ ] Then **execute the exit plan** (below) — or **consciously re-decide** to extend, recording that as its own ADR. Do not let the experiment lapse silently.

## Exit / teardown runbook

Per ADR 0028. Eval data is throwaway — no production signal ever depends on it, so no data migration. Removal is heavier than a bundled StatefulSet because of the two operators and cluster-scoped CRDs.

Do each step deliberately; the destructive ones (`delete namespace`, CRD removal) require explicit operator confirmation per the root CLAUDE.md hard rules.

**1. Suspend Flux so it stops re-creating what you delete:**

```sh
flux suspend ks clickstack-app -n flux-system
flux suspend ks clickstack-operators -n flux-system
```

**2. Remove the manifests from Git** (the GitOps-correct teardown — Flux prunes on the next reconcile if not suspended; since we suspended, we delete by hand below). Delete the `kubernetes/apps/clickstack/` tree and its entry in the parent kustomization, commit, push.

**3. Delete the application namespace** (removes HyperDX, OTel collector, ClickHouse/Keeper/MongoDB StatefulSets, PVCs, the ESO Secret, the HTTPRoute, and the CRs):

```sh
kubectl delete namespace clickstack   # destructive — confirm with operator first
```

**4. Delete the custom resources first if the namespace delete hangs** — operator finalizers can block namespace deletion. Remove the CRs, then re-try the namespace delete:

```sh
kubectl -n clickstack delete clickhousecluster --all
kubectl -n clickstack delete keepercluster --all
kubectl -n clickstack delete mongodbcommunity --all
```

**5. Remove the two operators' cluster-scoped leftovers.** Namespace deletion does NOT remove cluster-scoped objects. Find and remove the operators' ClusterRoles / ClusterRoleBindings (names are operator-specific — list before deleting):

```sh
kubectl get clusterrole,clusterrolebinding | grep -iE 'clickhouse|keeper|mongodb'
# then delete the ones owned by the ClickHouse operator and MongoDB MCK
```

**6. Remove the three CRDs** (cluster-scoped — the heaviest part of the exit cost ADR 0028 flagged). This is irreversible for any remaining CRs:

```sh
kubectl get crd | grep -iE 'clickhouse|keeper|mongodb'
kubectl delete crd clickhouseclusters.<group>
kubectl delete crd keeperclusters.<group>
kubectl delete crd mongodbcommunity.<group>   # resolve exact CRD names from the get above
```

**7. Tear down the Temporal test signal if you wired it** (`usage.md`): revert the Temporal OTLP exporter change so Temporal isn't pointing at a dead collector. This is a Temporal-app manifest change — separate commit.

**8. Clean up out-of-cluster bits:**

- [ ] Delete the 1Password item `clickstack` from vault `anton` (the four credential fields).
- [ ] Confirm the `hyperdx.${SECRET_DOMAIN}` DNS/HTTPRoute is gone (deleted with the namespace).
- [ ] Verify nothing in `flux get ks -A` still references clickstack and no orphan CRDs remain.

**9. Record the teardown** — note it in the ADR 0008 successor (or an exit note), so the removal is in the graveyard for any future re-evaluation (`cluster-intake` checks the graveyard).
