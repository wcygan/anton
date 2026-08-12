# AGENTS.md

Goal: Operate and evolve the **anton** Talos Kubernetes homelab safely by reconciling Git intent with current cluster state.

Success means:
- Route the task through the matching Anton skill and subsystem guidance before acting.
- Preserve GitOps ownership, secrets, SOPS encryption, cluster identity, and tailnet privacy.
- Diagnose the first failing layer with current, bounded evidence instead of treating retries or downstream symptoms as causes.
- Verify every authorized change from its source of truth through the user-visible outcome, with no hidden live drift.

Stop when: the read-only question has an evidence-backed answer, or the authorized change passes its stated acceptance checks. If another authority boundary remains, return an exact operator handoff instead of crossing it.

## Repo Model

Anton is a hand-edited Talos + Flux cluster. `kubernetes/`, `talos/`, and `bootstrap/` are committed directly; there is no repository render step. Talos machine configs are generated from `talos/talconfig.yaml` plus `talos/talenv.yaml` with talhelper. After bootstrap, Flux renders and applies the committed desired state.

## Agent skills

### Issue tracker

Specs and tickets use Local Markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Local issue status uses the five canonical triage roles. See `docs/agents/triage-labels.md`.

### Domain docs

Anton uses one domain context with durable records under `context/`. See `docs/agents/domain.md`.

## Route First

Read the matching `.agents/skills/<name>/SKILL.md` before following that branch:

| Branch | Skill |
|---|---|
| Kubernetes access, context, kubeconfig, talosconfig, or off-LAN connectivity | `anton-remote-access` |
| Broad cluster health or an unclear symptom | `anton-cluster-health`; start with `talos-inspect` for node, etcd, disk, route, or interface symptoms |
| Stuck Flux source, Kustomization, HelmRelease, SOPS, postBuild, or dependency | `debug-flux-reconciliation` |
| Incident logs, LogQL, missing logs, or the OTel-to-Loki path | `query-kubernetes-logs` |
| Flux manifest authoring or review | `anton-repo-conventions` plus the task-specific app, exposure, storage, database, or observability skill |
| Node replacement, upgrades, credential rotation, restore, or storage-node work | The matching high-risk skill; retain all of its preconditions, approval gates, and rollback checks |

Read the instruction file for every area the task touches:

| Area | Read |
|---|---|
| Flux apps | [kubernetes/apps/AGENTS.md](kubernetes/apps/AGENTS.md) |
| Network, gateways, Multus, storage VXLAN | [kubernetes/apps/network/AGENTS.md](kubernetes/apps/network/AGENTS.md) |
| Longhorn and SeaweedFS | [kubernetes/apps/storage/AGENTS.md](kubernetes/apps/storage/AGENTS.md) |
| CNPG and Dragonfly operators | [kubernetes/apps/databases/AGENTS.md](kubernetes/apps/databases/AGENTS.md) |
| Harbor registry | [kubernetes/apps/registries/AGENTS.md](kubernetes/apps/registries/AGENTS.md) |
| Talos config and patches | [talos/AGENTS.md](talos/AGENTS.md) |
| Bootstrap Helmfile | [bootstrap/AGENTS.md](bootstrap/AGENTS.md) |
| Shared scripts | [scripts/AGENTS.md](scripts/AGENTS.md) |
| Task wrappers | [.taskfiles/AGENTS.md](.taskfiles/AGENTS.md) |
| ADRs and plans | [context/AGENTS.md](context/AGENTS.md) |
| Docusaurus docs | [docs/AGENTS.md](docs/AGENTS.md) |

The `.claude/` tree remains authoritative precedent during the Codex migration. Preserve it and consult it when the active Codex guidance does not cover a branch.

## Operational Contract

### Authority and preflight

- Treat inspect, diagnose, audit, assess, and recommend requests as read-only.
- Treat repository edits, Flux actions, Kubernetes/Talos mutations, DNS or provider changes, and credential work as separate authority boundaries. Authority for one does not grant the others.
- Before a cluster command, establish the current kube or Talos context, cluster, namespace, exact target, owner, and incident window. Before a repository edit, establish branch, revision, and dirty state.
- Use the repo environment through `mise exec --`; discover task entry points with `mise exec -- task --list`. Fail closed on an unexpected context, ambiguous target, missing access, or unclear mutation owner.
- Treat port-forwards, debug pods, ephemeral containers, ad hoc jobs, synthetic traffic, and force reconciles as live mutations with explicit approval and cleanup requirements.

### Diagnose one path

Define the symptom, scope, expected state, current evidence, authority, and acceptance condition. For broad health requests, let `anton-cluster-health` bound the layer walk.

Reconcile these layers separately:

```text
committed intent -> Flux source revision -> render/apply status -> applied object
                 -> Kubernetes controller -> workload runtime -> dependencies
                 -> external or user-visible outcome
```

At each relevant layer, record identity, expected state, observed state, conditions, evidence time, and owner. Work from the earliest discriminating failure in the selected window; connect events by revision, generation, ownership, or a verified dependency path rather than timestamp proximity alone.

Use bounded events and logs. Preserve reason, message, generation, restart count, and timestamps where relevant; redact secret-bearing output. When evidence is ambiguous, keep a short hypothesis ledger with supporting evidence, contradicting evidence, and the next read-only check.

Report current impact and health, the earliest supported cause, confidence, rejected explanations when material, and whether a mutation is actually needed.

### Change at the owner

Prefer the smallest repair at the authoritative owner: a repository change for GitOps-managed state, an external-system change for a failed external dependency, then a controller action when desired state is already correct. Use live mitigation only when explicitly approved, time-sensitive, recoverable, and paired with a durable follow-up.

Before an approved live mutation, state:

- exact owner, target, command or file, and expected scope;
- preconditions, backup or recovery state, and predicted transitions;
- stop condition and timeout;
- rollback trigger and operation; and
- acceptance checks and evidence to retain at every affected layer.

Perform one causal mutation at a time and observe its predicted transition before continuing. A restart, reconcile, credential rotation, or stateful-resource replacement requires causal evidence; it is not a diagnostic shortcut.

### Verify end to end

Verify the intended revision or configuration, Flux-reported revision and reconciliation, applied generation and controller status, stable workload readiness without a new event or restart loop, required dependencies and data, and the actual service or user-visible outcome. Confirm that no unmanaged drift or temporary diagnostic resource remains. Observe the known recurrence window when practical; otherwise state the residual risk.

## QMD Context Search

Use QMD before broad manual browsing when the task depends on Anton's ADRs, plans, incidents, postmortems, or inventory under `context/`. Search `anton-context`, then retrieve the source with `qmd get` or `qmd multi-get` before relying on it. Treat snippets as leads and cite the actual `context/` path. Use `rg` for exact repository state. Rebuild a missing or stale local index with `mise exec -- task qmd:bootstrap`.

## Safety and Secrets

- Keep the literal tailnet name out of committed files. Use `<tailnet-name>.ts.net`.
- Keep existing `*.sops.*` files encrypted. Edit them with `sops <file>` and verify with `sops filestatus <file>`.
- Keep bootstrap credentials out of edits and output: `age.key`, `github-deploy.key`, `cloudflare-tunnel.json`, and token files.
- Prefer namespaced, bounded reads such as `kubectl get`, `kubectl describe`, `kubectl logs`, `talosctl get`, `talosctl read`, `talosctl logs`, `talosctl health`, `flux get`, and `flux logs`. Inspect secret metadata and delivery conditions without reading Secret data.
- Present the exact target and effect, then obtain explicit operator approval before any live-cluster mutation, credential rotation, Talos reset/upgrade/apply, namespace or storage deletion, Flux suspend/uninstall/reconcile, or recursive deletion.
- Verify kube and Talos context immediately before an approved mutation. The expected Kubernetes context is the Tailscale operator proxy, with `admin@anton` only as fallback.

## Repository Change Loop

1. Read the matching subsystem guidance, skill, and representative sibling files; finish when the intended convention and ownership boundary are explicit.
2. Edit the committed source of truth directly while preserving unrelated dirty work; finish when the diff contains only the requested change.
3. For Talos source edits, run `mise exec -- task talos:generate-config`; finish when generated configs reflect the intended source change.
4. For SOPS files, verify encryption with `sops filestatus`; finish only when every touched payload reports encrypted.
5. Run the narrowest validation that proves the edited surface: YAML parse, skill or hook fixture, Docusaurus check, generated-config check, or read-only Flux/Talos status. Run `mise exec -- task contracts:validate` when changing Flux application policy, Kubernetes logging semantics, SeaweedFS bucket provisioning, cluster target/preflight behavior, or shared agent safety policy.
6. Summarize changed files, validation evidence, residual risks, and any operator-only follow-up. Do not reconcile or apply merely because repository validation passed.

## Codex Enablement

Repo-local Codex work is tracked in [context/plans/0017-codex-usage-parity.md](context/plans/0017-codex-usage-parity.md). Add Codex skills under `.agents/skills/`, Codex project config and hooks under `.codex/`, and keep each port scoped to a proven Claude precedent.
