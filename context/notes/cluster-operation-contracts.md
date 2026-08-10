# Cluster operation contracts

This note records the 2026-08-09 architecture-review implementation. The
temporary visual report identified repeated operational knowledge across Flux
hooks, logging manifests and guidance, SeaweedFS bucket jobs, target inventory,
and the Iceberg demo. Plan 0021 tracks the execution state; this note is the
durable map of the resulting interfaces and rollout boundaries.

## Disposition

| Review candidate | Disposition | Durable interface |
| --- | --- | --- |
| Flux application contract | Implemented | `scripts/lib/flux_application_contract.py` |
| SeaweedFS storage provisioning | Implemented after fixture proof | `kubernetes/apps/storage/seaweedfs-config/app/provision-buckets.sh` |
| Kubernetes log contract | Implemented; ADR drift resolved to the accepted decision | `scripts/lib/kubernetes_log_contract.py` |
| Cluster target and preflight resolution | Implemented | `scripts/lib/cluster_target_contract.py` plus `scripts/cluster-targets.json` |
| Iceberg acceptance module | Deferred | ADR 0031 review on 2026-08-20 decides retain versus remove before more abstraction |

## Interfaces

### Flux application contract

Codex and Claude retain separate hook event adapters, but both call the same
dependency-free module. It validates namespace registration, app source shape,
the committed application path, ADR 0027 consumer `dependsOn` edges, and
provider readiness. `python3 scripts/validate-flux-contract.py` scans the full
tree, while PostToolUse hooks validate the affected app or namespace.

### Kubernetes logging contract

The module owns severity normalization, indexed resource attributes, default
retention, stream retention, and golden log records. Its adapters validate the
OTel pipeline, Loki policy, Grafana datasource, query catalog, runbook pointer,
and query skill pointer. `python3 scripts/validate-log-contract.py --show`
prints the current contract without another copied table.

ADR 0030 is authoritative: debug and trace retention is six hours. Applying
the changed Loki source lets the compactor delete older low-severity records.
Reverting before Flux reconciliation is safe; reverting afterward changes
future retention but cannot recover objects already deleted by compaction.

### SeaweedFS bucket provisioning

Storage owns bucket lifecycle in `seaweedfs-buckets-ensure`. Workload intent is
declared as ordinary buckets (`harbor`, `loki`, and `iceberg-raw`) and an S3
Tables bucket (`iceberg-warehouse`). The mounted script performs endpoint and
authorization preflight, refuses kind collisions before creating anything,
verifies each create, and emits bounded key/value evidence. The existing admin
identity remains the provisioning credential; consolidation does not broaden
credential access. Loki retains its existing runtime Secret.

Reverting restores the separate CronJobs but does not remove buckets created by
the shared job. No rollback path deletes bucket data.

### Cluster target and preflight contract

Target resolution prefers a complete live Tailscale status and otherwise uses
the complete committed fallback set. It never mixes sources. Default evidence
redacts addresses; `--show-addresses` is explicit. Talos health, the task
wrapper, both agent context guards, the remote-access skill, and the Talos
runbook consume the interface.

Command classification treats port-forwards and pod exec as cluster mutations.
Mutations fail closed when the current kube or Talos context cannot be resolved
or does not match Anton. Local context-selection commands remain local
mutations so the operator can repair an incorrect context.

## Validation

Run the aggregate source gate:

```sh
mise exec -- task contracts:validate
```

It runs the four contract validators and the shared fixture suite. Also run the
Codex hook fixtures and manifest/render checks for touched apps:

```sh
python3 .codex/hooks/test_anton_policy.py
mise exec -- kustomize build kubernetes/apps/storage/seaweedfs-config/app
mise exec -- kustomize build kubernetes/apps/observability/loki/app
cd docs && bun run build
```

These checks prove committed intent and renderability only. No Flux reconcile,
Kubernetes apply, ad hoc Job, port-forward, or other live-cluster mutation is
part of this implementation. An operator-approved rollout must separately
verify the applied revision, `seaweedfs-buckets-ensure` execution, Loki
readiness and retention configuration, OTel export health, Grafana queries,
and absence of new controller/event loops.

## Iceberg gate

Do not deepen the Iceberg acceptance workflow before ADR 0031's 2026-08-20
review. If the decision is retain, the next design may put Spark/Trino outcome
correlation behind live-cluster and disposable-local adapters. If the decision
is remove, follow the existing cleanup plan instead of preserving the demo as
an abstraction.
