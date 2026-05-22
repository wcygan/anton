# .taskfiles/

Goal: Maintain Task targets as Anton's operator-facing command surface.

Success means:
- Each lifecycle workflow has one clear `task` entry point.
- Targets set preconditions before calling scripts or cluster tools.
- Destructive targets keep explicit prompts and require operator intent.

Stop when: `task --list` remains useful and edited targets validate the files, tools, and variables they require.

## Layout

- `bootstrap/Taskfile.yaml`: fresh-cluster bootstrap targets.
- `talos/Taskfile.yaml`: Talos generate, apply, upgrade, and reset targets.
- Root `Taskfile.yaml`: shared env and `task reconcile`.

Add new targets to the subsystem file that owns the workflow. Use `requires.vars` for parameters such as `IP=` and `preconditions` for required tools or files.

## Safety

Keep prompts on destructive targets such as `task talos:reset`. Use explicit `MODE=` for Talos apply paths. Prefer read-only task wrappers for diagnostics.
