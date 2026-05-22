---
status: Done
opened: 2026-05-22
closed: 2026-05-22
affects: all
intent: concrete-need
related-adrs: []
review-by: null
---

# 0017 - Bring Codex usage to parity

> Codex should be able to work in Anton with repo-native guidance, task skills, and safety checks comparable to the existing Claude Code setup.

## Goal

Codex should enter `/Users/wcygan/Development/anton`, discover Anton-specific instructions, use focused workflows for common cluster tasks, and respect the same safety boundaries that Claude Code currently gets from `CLAUDE.md`, `.claude/skills/`, `.claude/agents/`, and `.claude/hooks/`.

## Acceptance criteria

- [x] Codex loads root and subsystem guidance through `AGENTS.md` files.
- [x] High-value Claude skills have Codex-native equivalents or explicit bridge/defer decisions.
- [x] Codex safety hooks or command rules cover destructive cluster operations, SOPS/tailnet leaks, YAML validation, and Flux app-shape checks.
- [x] Validation evidence shows Codex can see the guidance and the adapted hooks pass fixture tests.
- [x] Remaining Claude-only capabilities and follow-up gaps are documented.

## Current parity inventory

### Instruction Files

| Claude artifact | Codex action | Notes |
|---|---|---|
| `CLAUDE.md` | Port to root `AGENTS.md` | Keep as the high-signal routing layer for Anton. |
| `kubernetes/apps/CLAUDE.md` | Port to `kubernetes/apps/AGENTS.md` | Capture 3-file Flux pattern and read order. |
| `kubernetes/apps/network/CLAUDE.md` | Port to `kubernetes/apps/network/AGENTS.md` | Capture gateway and storage-fabric rules. |
| `kubernetes/apps/storage/CLAUDE.md` | Port to `kubernetes/apps/storage/AGENTS.md` | Capture Longhorn and SeaweedFS load-bearing details. |
| `kubernetes/apps/databases/CLAUDE.md` | Port to `kubernetes/apps/databases/AGENTS.md` | Capture CNPG/Dragonfly operator quirks. |
| `kubernetes/apps/registries/CLAUDE.md` | Port to `kubernetes/apps/registries/AGENTS.md` | Capture Harbor dependency and auth-realm details. |
| `bootstrap/CLAUDE.md` | Port to `bootstrap/AGENTS.md` | Capture bootstrap-only scope. |
| `scripts/CLAUDE.md` | Port to `scripts/AGENTS.md` | Capture Bash helper conventions. |
| `.taskfiles/CLAUDE.md` | Port to `.taskfiles/AGENTS.md` | Capture Taskfile entry points and destructive prompts. |
| `context/CLAUDE.md` | Port to `context/AGENTS.md` | Capture ADR and plan rules. |
| `docs/CLAUDE.md` | Port to `docs/AGENTS.md` | Capture Docusaurus commands and file placement. |

### Skills

| Claude skill | Codex action | Priority |
|---|---|---|
| `anton-repo-conventions` | Port first | P0 |
| `anton-remote-access` | Port first | P0 |
| `talos-inspect` | Port first | P0 |
| `anton-cluster-health` | Port first | P0 |
| `debug-flux-reconciliation` | Port first | P0 |
| `add-flux-app` | Port after conventions | P1 |
| `expose-service` | Port after conventions | P1 |
| `adr` | Port with context guidance | P1 |
| `planner` | Port with context guidance | P1 |
| `observability-integrate` | Port after app authoring | P2 |
| `anton-upgrade-audit` | Port as read-only | P2 |
| `longhorn-volume-ops` / `longhorn-node-ops` / `longhorn-backup-dr` | Bridge or port selectively | P2 |
| `cluster-intake` | Bridge after ADR support | P3 |
| `deploy-owned-app` | Defer until base Flux skills work | P3 |
| `ntfy-alert-triage` | Defer until alerting need recurs | P3 |
| `add-or-replace-node` / `upgrade-talos-or-k8s` / `rotate-credential` | Keep high-friction; port only with guardrails | P3 |

### Agents

| Claude agent | Codex action | Notes |
|---|---|---|
| `cluster-triage` | Port to `.codex/agents/cluster-triage.toml` | Useful for explicit read-only investigations. |
| `flux-app-author` | Port after `add-flux-app` | Useful for scoped write work. |
| `flux-debugger` | Port after debug skill | Useful for explicit stuck-sync triage. |
| `talos-operator` | Defer until hooks are proven | High-stakes node work needs tested guards first. |
| `upgrade-auditor` | Port as read-only later | Depends on GitHub/Renovate access. |
| `conventions-linter` | Prefer hook/script first | Deterministic checks should lead. |
| `cluster-intake-gatekeeper` | Defer | Depends on ADR + intake workflow parity. |
| `credential-rotator` | Defer | Credential work needs explicit human approval. |

### Hooks And Safety Checks

| Claude hook | Codex action | Notes |
|---|---|---|
| `guard_destructive.py` | Adapt and fixture-test | Block dangerous Talos, kubectl, Flux, Helmfile, and filesystem commands. |
| `guard_k8s_context.py` | Adapt and fixture-test | Verify mutating cluster commands target Anton context. |
| `guard_sops.py` | Adapt and fixture-test | Protect bootstrap credentials and encrypted SOPS footers. |
| `guard_tailnet.py` | Adapt and fixture-test | Keep literal tailnet names out of committed files. |
| `guard_secret_leak.py` | Adapt and fixture-test | Catch obvious secret exfiltration or logs. |
| `validate_yaml.py` | Adapt and fixture-test | Parse edited YAML under `kubernetes/`, `talos/`, and `bootstrap/`. |
| `check_3_file_pattern.py` | Adapt and fixture-test | Enforce Flux app shape. |
| `validate_plan_status.py` | Adapt and fixture-test | Keep plan status values valid. |
| `inject_adr_index.py` / `inject_plans_index.py` / `inject_cluster_state.py` | Defer | Codex session-start injection needs schema and trust testing. |
| `reinject_conventions.py` | Defer | Less important once Codex has skills and `AGENTS.md`. |

## Tasks

- [x] Open the Codex goal for parity work.
- [x] Inventory Claude artifacts and classify Codex actions.
- [x] Add Codex-native `AGENTS.md` files.
- [x] Port P0 Codex skills.
- [x] Add Codex hook adapters and fixture tests.
- [x] Add selected `.codex/agents` only after skills and hooks are stable.
- [x] Write the final parity report.

## Log

- 2026-05-22: Plan opened after confirming Anton has a mature Claude Code setup and no repo-local Codex layer.
- 2026-05-22: Root and subsystem `AGENTS.md` files added; Codex prompt debug confirmed root guidance loads as project-doc.
- 2026-05-22: P0 repo-local Codex skills added under `.agents/skills/` and validated with `quick_validate.py`.
- 2026-05-22: Codex hook adapter, fixture tests, and three project agents added; hook tests pass and remaining gaps are documented in `context/codex-parity-report.md`.

## References

- Root Claude guide: `CLAUDE.md`
- Codex docs skill: `/Users/wcygan/Development/dotfiles/config/codex/skills/codex-docs/`
- Existing Claude skills: `.claude/skills/`
- Existing Claude agents: `.claude/agents/`
- Existing Claude hooks: `.claude/hooks/`
- Final report: `context/codex-parity-report.md`
