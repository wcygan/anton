# Cluster operation contracts: independent second architecture pass

Date: 2026-08-10

Revision inspected: `808bd81348ce7b009e1d7b3eb62a6796d7cad767`

## Research question

After the first cluster-operation-contract implementation, what residual
architectural friction still reduces safety, testability, or agent
navigability?

This was an independent, repository-only pass. It weighted the modules changed
by revision `808bd813`, the recent remote-health and logging work, and the
accepted Flux, logging, and Iceberg decisions. The review did not inspect or
mutate live cluster state.

## Implementation disposition

The 2026-08-10 follow-up implemented every supported repair without contacting
or mutating the live cluster:

| Finding | Disposition | Evidence surface |
| --- | --- | --- |
| Effective-target mutation preflight | Implemented | Direct wrappers and command-scoped context/config selections are analyzed; Kubernetes endpoint and Talos inventory identity are verified; ambiguous mutations fail closed |
| Shared Claude/Codex policy | Implemented | One semantic module with parity fixtures for every shared policy family |
| Logging production conformance | Implemented through generated source conformance | Golden records and the full ordered OTTL statement contract use the same canonical patterns |
| Missing Flux namespace registration | Fixed | A missing namespace `kustomization.yaml` is a contract violation |
| Labels-only raw Flux app | Fixed | Only resource-producing Kustomize keys satisfy raw-app material |

The logging repair deliberately proves exact deployed source conformance, not
execution by an OTel Collector process. A condition or ordering change now
fails the contract gate, while the remaining runtime risk stays in the
operator-approved rollout checks documented in the primary contract note.

Follow-up repository evidence:

```text
mise exec -- task contracts:validate
Flux application contract: PASS (47 applications)
Kubernetes logging contract: PASS
SeaweedFS provisioning contract: PASS
Cluster target contract: PASS
Ran 69 tests ... OK
```

The 69 tests include 17 cross-adapter policy cases. The separate Codex hook
entrypoint has 13 passing fixtures. Python compilation and
`git diff --check` also pass. These are repository and injected-event checks;
they do not establish applied cluster state.

## Ranked findings

| Rank | Candidate | Strength | Dependency category |
| --- | --- | --- | --- |
| 1 | Deepen mutation preflight around the effective target | Strong | Ports & adapters |
| 2 | Concentrate shared hook policy behind the two agent adapters | Strong | In-process |
| 3 | Make deployed log normalization the test surface | Worth exploring | Local-substitutable |

## 1. Deepen mutation preflight around the effective target

### Independent finding

The target/preflight module has a small interface and useful implementation,
but its target guarantee stops at the current named context. Anton's operating
contract requires the context, cluster, namespace, and exact target to be
established before a cluster command (`AGENTS.md:35-39`). The module reduces a
command to binary, subcommand, and classification, then compares only the
current kube or Talos context with the expected name
(`scripts/lib/cluster_target_contract.py:347-430`). An explicit command-scoped
target such as `kubectl --context ...` is discarded while extracting the
subcommand (`scripts/lib/cluster_target_contract.py:295-309`).

A local probe supplied the expected current context and received no violation
for each of these mutation shapes:

```text
kubectl --context definitely-wrong delete pod demo
env FOO=bar kubectl delete pod demo
bash -c 'kubectl delete pod demo'
command kubectl delete pod demo
```

The first shape can select a different cluster despite the current-context
check. The other shapes are not classified because the recognized cluster
binary must be the first token after only assignment or Mise handling
(`scripts/lib/cluster_target_contract.py:287-292,347-359`).

The existing tests prove Mise wrapping, a pipeline, port-forward
classification, missing-context refusal, and expected-context acceptance, but
do not cover command-scoped targets or shell indirection
(`scripts/tests/test_cluster_target_contract.py:62-91`).

### Counterevidence

- Live target discovery refuses a partial node set and falls back as one
  complete set (`scripts/lib/cluster_target_contract.py:208-261`).
- The command splitter preserves quoted separators
  (`scripts/lib/cluster_target_contract.py:312-344`).
- Current-context lookup failure is fail-closed for a recognized mutation
  (`scripts/lib/cluster_target_contract.py:400-429`).
- Production subprocess execution and the test `Runner` are two adapters at a
  real seam (`scripts/lib/cluster_target_contract.py:17,187-205`;
  `scripts/tests/test_cluster_target_contract.py:29-34`).

### Deletion test

Passes. Deleting the module would move target resolution and mutation
classification back into the Claude and Codex callers, reducing locality. The
module earns its seam; the residual is insufficient depth in the effective
target behavior behind its interface.

### Plain-English deepening

Make the effective target selected by the whole command part of the behavior
owned by this module, including explicit target flags and supported shell
indirection. Keep ambiguous mutation shapes fail-closed. Exercise those shapes
through the existing production and test adapters so every hook gains the same
leverage.

### Supervisor should verify

- Which shell forms the agent tools actually emit and therefore must be
  supported rather than rejected.
- Whether named-context identity is sufficient, or whether the module must also
  verify the selected cluster endpoint before a mutation.
- The desired classification for command-scoped kubeconfig and talosconfig
  overrides.

## 2. Concentrate shared hook policy behind the two agent adapters

### Independent finding

Claude registers separate policy hooks while Codex routes the same policy
families through one adapter (`.claude/settings.json:3-64`;
`.codex/hooks.json:3-25`). Flux validation and target preflight now cross shared
seams, but destructive-command, Secret-output, tailnet, SOPS, YAML, and plan
rules still have separate implementations. The Codex adapter owns those rules
directly (`.codex/hooks/anton_policy.py:35-109,139-169,173-255`), while Claude
keeps them in individual hook files, for example destructive-command policy
(`.claude/hooks/guard_destructive.py:99-176`) and plan status policy
(`.claude/hooks/validate_plan_status.py:24-41,70-118`).

This is already observable semantic drift, not a hypothetical seam:

- Claude permits `talosctl apply-config` when an explicit mode is present
  (`.claude/hooks/guard_destructive.py:158-161,210-214`); Codex places every
  `talosctl apply-config` behind its destructive approval rule
  (`.codex/hooks/anton_policy.py:57-61,150-157`).
- Claude accepts the compact namespace form `-nfoo` for a scoped Flux suspend
  (`.claude/hooks/guard_destructive.py:163-171,216-220`); Codex's scope check
  only names the spaced `-n` form, long namespace form, and all-namespaces
  forms (`.codex/hooks/anton_policy.py:85-88`).
- Codex protects `github-push-token.txt` in addition to the three shared
  bootstrap credential names (`.codex/hooks/anton_policy.py:39-44`), while the
  Claude SOPS hook's protected set contains only those three
  (`.claude/hooks/guard_sops.py:51-55`).

Local hook probes confirmed the first two differences: the Claude destructive
hook returned success while the Codex policy hook blocked the same strings.

### Counterevidence

- Separate transport adapters are warranted because Claude and Codex emit
  different edit-event shapes (`.claude/hooks/check_3_file_pattern.py:17-35`;
  `.codex/hooks/anton_policy.py:173-212`).
- Cross-adapter Flux smoke tests exist
  (`scripts/tests/test_flux_hook_adapters.py:15-42`), and Codex has fixtures for
  its combined adapter (`.codex/hooks/test_anton_policy.py:36-125`).
- The current plan-status values happen to agree: Claude loads the same five
  values with a fallback (`.claude/hooks/validate_plan_status.py:24-41`) and
  Codex hard-codes those five (`.codex/hooks/anton_policy.py:37-38`).

### Deletion test

Passes for shared semantic policy and fails for duplicated rule copies. Deleting
a shared policy module would spread complexity across both adapters; deleting
either copied rule set merely leaves the other implementation in place. Claude
and Codex are two adapters, so this is a real seam.

### Plain-English deepening

Move shared policy meaning, decisions, and evidence into deep in-process
modules. Leave each agent-specific file responsible only for translating its
event shape and rendering feedback. Test both adapters against the same
behavior table so policy changes gain leverage and drift stays local.

### Supervisor should verify

- Which observed differences are intentional and should remain adapter-specific.
- Whether Claude's documented fail-open philosophy is still accepted for every
  policy family.
- Whether transport feedback text must remain different even when decisions
  become shared.

## 3. Make deployed log normalization the test surface

### Independent finding

The logging module says its Python normalizer has the same public behavior as
the OTel adapter (`scripts/lib/kubernetes_log_contract.py:55-72`), but golden
records execute only that Python implementation
(`scripts/lib/kubernetes_log_contract.py:89-106`;
`scripts/tests/test_kubernetes_log_contract.py:24-32`). The deployed OTel
normalization remains a separate list of OTTL statements
(`kubernetes/apps/observability/otel-collector/app/helmrelease.yaml:94-118`).
The validator checks that copied text fragments exist and that three processor
names appear in order; it does not execute the golden records through the
deployed transform (`scripts/lib/kubernetes_log_contract.py:109-142`).

The current interface therefore proves a surrogate and source-text agreement,
not behavior through the production adapter. That weakens locality: a behavior
change must be represented in Python patterns, required OTTL fragments, the
manifest implementation, and fixtures
(`scripts/lib/kubernetes_log_contract.py:55-72,109-128`;
`scripts/tests/fixtures/kubernetes-log-records.json:1-44`).

### Counterevidence

- The module centrally owns the accepted severity, indexed-label, and retention
  vocabulary (`scripts/lib/kubernetes_log_contract.py:11-38`), matching ADR
  0030's contract (`context/adrs/0030-adopt-loki-for-kubernetes-logs.md:30-45`).
- Loki retention and indexed attributes are parsed and compared with the
  canonical values (`scripts/lib/kubernetes_log_contract.py:145-197`).
- The full current repository passes the aggregate contract gate defined in
  `Taskfile.yaml:47-56`.

### Deletion test

Fails for the Python normalization surrogate. Deleting it removes a parallel
implementation rather than forcing complexity to reappear across production
callers. The claimed seam is hypothetical until a second executable adapter
processes the same records as the deployed transform.

### Plain-English deepening

Make the deployed normalization behavior—not copied source fragments—the
interface that golden records exercise. Preserve one canonical vocabulary, but
remove any parallel implementation that does not drive or execute production
behavior. This would increase locality and make the interface the test surface.

### Supervisor should verify

- Whether the pinned collector can execute this transform deterministically in
  a bounded local test.
- Whether a generated production transform would create more leverage than it
  costs in manifest readability.
- Which retention and query checks should remain structural because they have
  no practical local execution adapter.

## Explicit non-findings

### SeaweedFS provisioning

No residual deepening candidate is supported by this pass. The shell
provisioner hides preflight, collision refusal, creation, verification, and
evidence behind one implementation (`kubernetes/apps/storage/seaweedfs-config/app/provision-buckets.sh:23-162`).
Its fake AWS executable is a second adapter that exercises creation,
idempotency, invalid intent, and collision behavior through the production
script (`scripts/tests/test_seaweedfs_bucket_provisioner.py:17-67,70-131`). The
deletion test passes: removing the provisioner would spread those rules across
the Harbor, Loki, and Iceberg intents declared in the CronJob
(`kubernetes/apps/storage/seaweedfs-config/app/buckets-cronjob.yaml:41-49`).

### Flux application contract

No second-pass candidate has enough current evidence. The module has one
repository validation interface and is consumed by the repository validator,
Claude adapter, and Codex adapter (`scripts/lib/flux_application_contract.py:272-298`;
`scripts/validate-flux-contract.py:18-22`;
`.claude/hooks/check_3_file_pattern.py:14-35`;
`.codex/hooks/anton_policy.py:29-33,268-279`). Its parser is convention-shaped
and regex-based (`scripts/lib/flux_application_contract.py:72-138`), but the
current tree-wide gate covers 47 discovered applications and reports that count
from the same iterator (`scripts/validate-flux-contract.py:80-94`). This pass
found no committed nested app manifest that demonstrated an ADR 0027 escape, so
a parser replacement would be speculative rather than evidence-backed.

### Iceberg acceptance

Not reconsidered. ADR 0031 defines a learning experiment and a 2026-08-20
retain, revise, or remove review (`context/adrs/0031-adopt-seaweedfs-iceberg-log-demo.md:39-55`).
The completed plan explicitly defers further deepening until that gate
(`context/plans/0021-deepen-cluster-operation-contracts.md:56-60`).

## Supervisor verification

The supervisor independently reproduced the three ranked findings:

- Preflight returned no violation for `kubectl --context definitely-wrong
  delete pod demo` when the injected current context matched Anton. It also
  returned no classified operation for `env kubectl ...`, `command kubectl
  ...`, `sudo kubectl ...`, or `bash -c 'kubectl ...'`.
- Claude returned success while Codex blocked both `talosctl apply-config
  --mode=auto -f machine.yaml` and `flux suspend ks demo -nfoo`. These probes
  executed hook policy only; they did not invoke either cluster command.
- `normalize_severity("notice", "error request failed")` returned `error`,
  while the deployed OTTL statements retain the non-null `notice`, skip body
  heuristics, and finally assign the indexed severity `info`
  (`scripts/lib/kubernetes_log_contract.py:55-72`;
  `kubernetes/apps/observability/otel-collector/app/helmrelease.yaml:99-117`).

The supervisor also found two narrower Flux contract defects in synthetic
fixture trees: validation returned no violation when the namespace
`kustomization.yaml` was absent, and a raw app whose app kustomization contained
only a `labels` list passed the non-empty check. The implementation only checks
registration when the namespace file already exists and treats any YAML list
item as raw material (`scripts/lib/flux_application_contract.py:180-189,213-220`).
These defects merit direct regression fixes, but they do not yet establish a
new deepening candidate beyond the subagent's three ranked seams.

## Source and claim limits

- Primary sources only: repository source, tests, manifests, accepted ADRs, and
  the completed plan. No external source was necessary.
- Repository validation establishes committed intent, not live cluster state;
  the original note makes that limit explicit
  (`context/notes/cluster-operation-contracts.md:68-91`).
- The command and hook probes were local, injected-input executions. They did
  not invoke Kubernetes, Talos, Flux reconciliation, Tailscale mutation, or any
  cluster write.
- Recommendation 3 remains `Worth exploring` because this pass did not prove a
  bounded executable OTel adapter; the implemented repair proves exact ordered
  source conformance only.

## Inspection and validation performed

The following commands and 26-test result describe the pre-implementation
review snapshot at revision `808bd813`; the follow-up evidence above is the
current post-repair result.

```sh
git log --oneline -40
git show --name-status --format=fuller 808bd813
find kubernetes/apps -path '*/app/*/*.yaml' -type f
python3 scripts/validate-flux-contract.py
mise exec -- task contracts:validate
git show --check --oneline 808bd813
```

The local preflight probe used an injected runner and the local hook probes fed
JSON directly to the hook processes. The aggregate gate passed four validators,
47 Flux applications, and 26 tests. No live command was run.
