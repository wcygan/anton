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

## Debugging

Run scripts with `LOG_LEVEL=debug` to surface debug lines. Keep command wrappers in `.taskfiles/` so the repo exposes one operator path.
