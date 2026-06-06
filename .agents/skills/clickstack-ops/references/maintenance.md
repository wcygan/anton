# ClickStack Maintenance

Use this reference for Renovate posture, the 2026-08-02 review, and teardown. This is a throwaway eval; maintenance is about preserving the timebox and removing cleanly.

## Renovate Posture

ClickStack adds young chart and operator pins for the duration of the eval:

| Artifact | Pinned at | Source |
| --- | --- | --- |
| `clickstack-operators` chart | `1.0.0` | `clickstack-operators/app/helmrelease.yaml` |
| `clickstack` chart | `3.0.0` | `clickstack-app/app/helmrelease.yaml` |
| ClickHouse and MongoDB operators | bundled | operators chart |

Rules:

- Keep exact versions. Do not introduce ranges.
- Treat operators-chart bumps as cluster-tier because CRDs and controllers can change.
- Treat main-chart bumps as their own tier after the operators chart is known-good.
- Re-check `valuesFrom` target paths, `clickstack-app` Service naming, and OTel collector shape after any main-chart major.
- If a disruptive bump appears close to review-by, declining the bump and tearing down on schedule may be cheaper than migrating the eval.

Use `anton-upgrade-audit` for PR inventory, supersession detection, and merge ordering. This reference only supplies ClickStack-specific risk posture.

## Review-By Checklist: 2026-08-02

ADR 0028's review date is load-bearing. Before or on 2026-08-02, produce falsifiable answers to all four criteria:

- [ ] Criterion 1: Did ClickHouse-backed wide-events querying beat VictoriaLogs for cross-pod and 24h-or-longer questions? Cite specific Lucene or SQL queries and latency/UX.
- [ ] Criterion 2: Is "ClickHouse is too heavy" still true at Anton scale? Record CPU, memory, storage, and operational cost for ClickHouse, Keeper, MongoDB, HyperDX, and collector.
- [ ] Criterion 3: Was HyperDX worth a separate logs/traces UI, or did it confirm the Grafana fragmentation concern?
- [ ] Criterion 4: Did containment hold? The expected answer is that no Prometheus metrics entered ClickHouse.

Then act:

- [ ] Write the ADR 0008 successor with the `adr` skill. Either confirm VictoriaLogs plus Jaeger or re-rank toward ClickHouse/HyperDX.
- [ ] Execute the exit plan, or write a new ADR that consciously extends or changes the experiment.

Do not let ClickStack remain because nobody closed the loop.

## Exit And Teardown Runbook

Teardown is destructive and requires explicit operator approval. Present the commands, expected effect, and verification before running any live step.

1. Suspend Flux so it does not recreate deleted resources:

   ```sh
   flux suspend ks clickstack-app -n flux-system
   flux suspend ks clickstack-operators -n flux-system
   ```

2. Remove the source manifests from Git:

   - Delete `kubernetes/apps/clickstack/`.
   - Remove any parent kustomization entry that references it.
   - Revert any Temporal OTLP exporter change that points at ClickStack.

3. Delete the application namespace after approval:

   ```sh
   kubectl delete namespace clickstack
   ```

4. If namespace deletion hangs, remove namespaced custom resources after approval:

   ```sh
   kubectl -n clickstack delete clickhousecluster --all
   kubectl -n clickstack delete keepercluster --all
   kubectl -n clickstack delete mongodbcommunity --all
   ```

5. Remove operator cluster-scoped leftovers after listing exact names:

   ```sh
   kubectl get clusterrole,clusterrolebinding | rg -i 'clickhouse|keeper|mongodb'
   ```

6. Remove the CRDs only after confirming no remaining CRs need them:

   ```sh
   kubectl get crd | rg -i 'clickhouse|keeper|mongodb'
   kubectl delete crd <clickhousecluster-crd>
   kubectl delete crd <keepercluster-crd>
   kubectl delete crd <mongodbcommunity-crd>
   ```

7. Clean up out-of-cluster bits:

   - Delete the 1Password item `clickstack`.
   - Confirm the Tailscale `hyperdx` MagicDNS entry is gone.
   - Confirm `flux get ks -A` has no ClickStack entries.
   - Confirm no ClickStack CRDs remain.

8. Record the teardown in the ADR 0008 successor or an exit note so future intake can see the result.
