# scripts/

Goal: Maintain shared Bash orchestration with predictable logging and failure behavior.

Success means:
- Scripts use the existing `scripts/lib/common.sh` helpers.
- Mutating scripts validate environment and CLI prerequisites before acting.
- Logs name resources and paths, while secret values stay out of output.

Stop when: the script is wired through a Task target or clearly documented command path and a focused dry run or narrow validation passes.

## Pattern

Start new Bash scripts with:

```sh
set -Eeuo pipefail
source "$(dirname "${0}")/lib/common.sh"
```

Use `check_env` and `check_cli` before stateful work. Use `log <level> <message> key=value` for output. Add helpers to `lib/common.sh` only after a second script needs the same behavior.

## Executable contracts

Run `mise exec -- task contracts:validate` after changing Flux application
rules, logging semantics, SeaweedFS provisioning, target/preflight behavior, or
agent safety policy. Keep shared implementations in `scripts/lib/`, thin
adapters at agent/tool boundaries, and golden behavior under `scripts/tests/`.
When Claude and Codex enforce the same meaning, change the shared policy and its
cross-adapter fixtures rather than either transport adapter alone.
`scripts/cluster-targets.json` is the only committed fallback for Talos
Tailscale endpoints.

## Debugging

Run scripts with `LOG_LEVEL=debug` to surface debug lines. Keep command wrappers in `.taskfiles/` so the repo exposes one operator path.
