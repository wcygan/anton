# .taskfiles/

Per-subsystem Task targets that the root `Taskfile.yaml` includes under the `bootstrap`, `talos`, and `template` namespaces. These are the canonical entry points for every lifecycle operation in the repo — if a workflow isn't exposed as a task, it's either a script under `scripts/` or it doesn't exist yet.

## Contents

- `template/Taskfile.yaml` — rendering and validation pipeline: `:init:` scaffolds configs, `:configure:` runs `validate-schemas → render-configs (makejinja) → encrypt-secrets → validate-kubernetes-config → validate-talos-config`; plus `debug`, `tidy`, `reset`
- `template/resources/` — CUE schemas (`cluster.schema.cue`, `nodes.schema.cue`) and `kubeconform.sh` that back the validation tasks
- `talos/Taskfile.yaml` — `generate-config`, `apply-node IP=<ip> [MODE=auto]`, `upgrade-node IP=<ip>`, `upgrade-k8s`, and the destructive `reset`; Talos-version and K8s-version come from `talos/talenv.yaml`
- `bootstrap/Taskfile.yaml` — `talos` (one-shot Talos install + bootstrap + kubeconfig) and `apps` (delegates to `scripts/bootstrap-apps.sh`)

## Usage

All tasks run from the repo root (`KUBECONFIG`, `SOPS_AGE_KEY_FILE`, and `TALOSCONFIG` are set in the root `Taskfile.yaml`'s env). Use `task --list` to see everything; `task reconcile` lives at the root for the one workflow common enough to deserve it.

Destructive tasks (`task talos:reset`, `task template:reset`) gate behind `prompt:` — never pipe `yes` or use `--yes`; the root CLAUDE.md requires explicit confirmation for these. Most other tasks are idempotent and safe to re-run. Tasks prefixed with `:` (e.g. `:configure:`, `:init:`) are the user-facing entry points aggregated from internal helper tasks in the same file.

When adding a new task, extend the right subsystem file rather than creating a new one. Follow the existing shape: a one-line `desc:`, `preconditions:` that assert files/tools exist before the work runs, `requires.vars:` for parameters like `IP=`. For high-stakes Talos or rolling-upgrade work, prefer the `talos-operator` subagent and `upgrade-talos-or-k8s` skill over writing bespoke task wrappers.
