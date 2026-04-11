# scripts/

Bash orchestration called from Taskfile targets for operations too stateful for a one-line `cmd:`. Every script sources `lib/common.sh` and uses the same three helpers so behavior, logging, and failure modes stay uniform across the repo.

## Contents

- `bootstrap-apps.sh` — the only end-user script today; invoked by `task bootstrap:apps` to run the five phases (wait for nodes → apply namespaces → apply SOPS secrets → apply CRDs → `helmfile sync`) that hand the cluster off to Flux
- `lib/common.sh` — shared helpers: `log <level> <msg> key=value…` (debug|info|warn|error; error exits 1), `check_env <VAR…>`, and `check_cli <tool…>`; source it from every new script

## Usage

New scripts follow the existing shape: `set -Eeuo pipefail`, `source "$(dirname "${0}")/lib/common.sh"`, then `check_env`/`check_cli` up front before any mutating work. Wire them in by adding a Task target under `.taskfiles/` with `preconditions:` that assert required env vars and files — the script then trusts its environment and focuses on the imperative work.

Add code to `lib/common.sh` only when a helper would be reused by a second script; until then, keep it local. When diagnosing a failed run, re-run with `LOG_LEVEL=debug` — `log` respects the env var and promotes debug lines without needing a flag. Never log secret values; log file paths or resource names instead.
