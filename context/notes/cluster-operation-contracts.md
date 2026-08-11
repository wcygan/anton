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
| Kubernetes log contract | Implemented; ADR 0032 sets Loki's 24-hour stream minimum | `scripts/lib/kubernetes_log_contract.py` |
| Cluster target and preflight resolution | Implemented | `scripts/lib/cluster_target_contract.py` plus `scripts/cluster-targets.json` |
| Shared agent safety policy | Implemented after adapter-parity proof | `scripts/lib/agent_policy_contract.py` |
| Iceberg acceptance module | Deferred | ADR 0031 review on 2026-08-20 decides retain versus remove before more abstraction |

## Interfaces

### Flux application contract

Codex and Claude retain separate hook event adapters, but both call the same
dependency-free module. It validates namespace registration, app source shape,
the committed application path, ADR 0027 consumer `dependsOn` edges, and
provider readiness. A namespace-level `kustomization.yaml` is required, and a
raw app must contain a resource-producing Kustomize key rather than an
unrelated list such as `labels`. `python3 scripts/validate-flux-contract.py`
scans the full tree, while PostToolUse hooks validate the affected app or
namespace.

### Kubernetes logging contract

The module owns severity normalization patterns, their serialized OTTL
statements, indexed resource attributes, default retention, stream retention,
and golden log records. Golden records and the deployed transform therefore
consume one policy vocabulary. The OTel adapter compares the full ordered
statement list, including conditions, rather than checking copied fragments;
it does not claim to execute an OTel Collector binary. Other adapters validate
Loki policy, Grafana datasource, query catalog, runbook pointer, and query skill
pointer. `python3 scripts/validate-log-contract.py --show` prints the current
contract without another copied table.

ADR 0032 is authoritative: debug and trace retention is 24 hours, Loki's
supported stream minimum. Applying the corrected Loki source restores desired
state convergence. Reverting after reconciliation restores the failed value
and can stall Loki again.

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
Direct environment, `command` without `-p`, Mise, `exec`, `nohup`, `nice`,
`timeout`, and `time` wrappers retain classification and target-query semantics;
`command -p` fails closed because it changes executable lookup.
Every Kubernetes or Flux mutation must resolve to the independently derived
Anton API endpoint, and every Talos mutation must resolve to the committed node
inventory. Explicit `--context`, `--kubeconfig`, `--talosconfig`, `KUBECONFIG`,
and `TALOSCONFIG` selections are included in that effective-target check. The
Kubernetes identity comes from the repo-selected canonical kubeconfig when it
is available, otherwise from the operator-proxy context or committed fallback
endpoint; custom context fixtures must pair `ANTON_KUBE_CONTEXT` with
`ANTON_KUBE_ENDPOINT`. Repeated scalar target flags use the CLI-effective final
value, while repeated Talos node and endpoint selections are conservatively
combined. Talos identity includes committed LAN node addresses and remote
Tailscale targets. Explicit executable paths are reused for target
queries. Environment-clearing wrappers, target-affecting environment or shell
state, compound forms, `eval`, command substitution, `sudo`, `xargs`, and
parallel mutations fail closed when their runtime target cannot be proved;
indirect read-only operations remain read-only.
Local context-selection commands remain local mutations so the operator can
repair an incorrect context.

### Shared agent safety policy

Claude and Codex keep separate event-shape adapters but consume one policy
module for destructive-command approval, Secret-output protection, tailnet
privacy, protected credentials and encrypted SOPS files, YAML syntax, and plan
status. The stricter shared meaning requires approval for every
`talosctl apply-config` and `flux suspend` command and protects the union of
known bootstrap credential artifacts. Cross-adapter fixtures exercise each
policy family so transport changes cannot silently fork policy behavior.

## Validation

Run the aggregate source gate:

```sh
mise exec -- task contracts:validate
```

It runs the four contract validators and the shared fixture suite, including
Claude/Codex safety-policy parity. Also run the Codex adapter fixtures and
manifest/render checks for touched apps:

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
