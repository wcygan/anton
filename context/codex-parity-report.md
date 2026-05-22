# Codex Parity Report

Date: 2026-05-22

## Summary

Codex now has a repo-local Anton operating model that covers the highest-value Claude Code behavior: project instructions, subsystem routing, read-only cluster triage skills, Flux convention guidance, safety hooks, and selected custom agents.

This is practical parity for day-to-day Codex use in Anton, not a full mechanical clone of `.claude/`. The remaining Claude-only pieces are either high-risk, lower-frequency, or better handled after the new Codex layer sees real use.

## What Codex Now Loads

- Root instructions: `AGENTS.md`
- Subsystem instructions:
  - `kubernetes/apps/AGENTS.md`
  - `kubernetes/apps/network/AGENTS.md`
  - `kubernetes/apps/storage/AGENTS.md`
  - `kubernetes/apps/databases/AGENTS.md`
  - `kubernetes/apps/registries/AGENTS.md`
  - `talos/AGENTS.md`
  - `bootstrap/AGENTS.md`
  - `scripts/AGENTS.md`
  - `.taskfiles/AGENTS.md`
  - `context/AGENTS.md`
  - `docs/AGENTS.md`
- Repo-local Codex skills under `.agents/skills/`:
  - `anton-repo-conventions`
  - `anton-remote-access`
  - `talos-inspect`
  - `anton-cluster-health`
  - `debug-flux-reconciliation`
- Project Codex agents under `.codex/agents/`:
  - `anton-cluster-triage`
  - `anton-flux-debugger`
  - `anton-flux-app-author`
- Project hooks:
  - `.codex/hooks.json`
  - `.codex/hooks/anton_policy.py`
  - `.codex/hooks/test_anton_policy.py`

## Safety Coverage

The Codex hook adapter covers these policies:

- Blocks dangerous Bash commands such as `task talos:reset`, `talosctl reset`, `talosctl apply-config`, destructive namespace/PV/PVC/CRD deletes, `helmfile destroy`, `flux uninstall`, unscoped `flux suspend`, and root/home recursive deletion.
- Blocks `kubectl get secret ... -o yaml/json/jsonpath/...` patterns that would expose Secret `.data`.
- Blocks patch edits to protected credential artifacts.
- Blocks patch edits to existing encrypted SOPS files.
- Blocks real tailnet hostnames when `ANTON_TAILNET_NAME` is set.
- Validates YAML touched under `kubernetes/`, `talos/`, and `bootstrap/` when `yq` is available.
- Validates Flux app scaffolding for touched apps under `kubernetes/apps/`.
- Validates `context/plans/NNNN-*.md` status values.

The hooks are project-local. Codex may ask for hook trust on first use of `.codex/hooks.json`; trust the hook only after reviewing the file content in this repo.

## Validation Evidence

Commands run from `/Users/wcygan/Development/anton`:

```sh
codex debug prompt-input 'noop' | rg -n 'anton-cluster-health|anton-remote-access|anton-repo-conventions|debug-flux-reconciliation|talos-inspect|project-doc' | head -80
```

Result: root `AGENTS.md` was visible as `project-doc`, and all five repo-local skills appeared from `/Users/wcygan/Development/anton/.agents/skills`.

```sh
for skill in .agents/skills/*; do
  uv run --with pyyaml /Users/wcygan/Development/dotfiles/config/codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill"
done
```

Result: all five skills returned `Skill is valid!`.

```sh
uv run --script .codex/hooks/test_anton_policy.py
```

Result: seven hook fixture tests passed.

```sh
python3 -m json.tool .codex/hooks.json >/dev/null
python3 - <<'PY'
import tomllib
from pathlib import Path
for path in sorted(Path('.codex/agents').glob('*.toml')):
    with path.open('rb') as f:
        data = tomllib.load(f)
    missing = {'name','description','developer_instructions'} - data.keys()
    if missing:
        raise SystemExit(f'{path}: missing {missing}')
    print(f'{path}: ok')
PY
```

Result: hooks JSON parsed and all three custom-agent TOML files had required fields.

```sh
rg -n 'realtail\.ts\.net|TODO|\[TODO' AGENTS.md .agents .codex context/plans/0017-codex-usage-parity.md kubernetes/apps/AGENTS.md kubernetes/apps/network/AGENTS.md kubernetes/apps/storage/AGENTS.md kubernetes/apps/databases/AGENTS.md kubernetes/apps/registries/AGENTS.md talos/AGENTS.md bootstrap/AGENTS.md scripts/AGENTS.md .taskfiles/AGENTS.md context/AGENTS.md docs/AGENTS.md
```

Result: no matches.

```sh
find . -name '*.sops.*' -not -name '.sops.yaml' -not -path './.private/*' -exec sops filestatus {} \;
```

Result: every SOPS payload file reported `{"encrypted":true}`. The SOPS config file `.sops.yaml` is intentionally excluded because it is not an encrypted payload.

## Remaining Claude-Only Gaps

- P1/P2 write workflows are not fully ported yet: `add-flux-app`, `expose-service`, `adr`, `planner`, `observability-integrate`, and `anton-upgrade-audit`.
- High-risk operations remain Claude-first or human-gated: node add/replace, Talos/Kubernetes upgrades, and credential rotation.
- Claude session-start context injection is not ported: ADR index, active plan index, and cluster-state injection.
- Claude agent memory is not bulk-ported. Durable facts should move into `AGENTS.md`, skill references, ADRs, plans, or docs as they prove current.
- Hook coverage is fixture-tested but not yet exercised through a fresh interactive Codex session after hook trust.

## Recommended Next Ports

1. Port `add-flux-app` and `expose-service` once the P0 skills have been used on at least one real manifest edit.
2. Port `adr` and `planner` so Codex can author durable Anton decisions and plans without referencing Claude skills.
3. Add read-only session-start context only after validating Codex hook output semantics for `SessionStart`.
4. Port `anton-upgrade-audit` as a read-only agent/skill pair after GitHub/Renovate workflows are checked in a real upgrade task.
