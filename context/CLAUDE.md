# context/ — north star

This directory holds **immutable architectural decisions** for anton. It exists so that Claude Code agents and skills (and your future self) can discover *why* the cluster looks the way it does, without having to mine `git log` or interrogate the operator.

## Layout

- `adrs/` — numbered ADRs (`NNNN-kebab-slug.md`), `TEMPLATE.md`, and `RE-ADOPTION-RUBRIC.md`.

## Hard rules

- **ADRs are immutable.** Once a decision is recorded, the body never changes. To revise a decision, write a new ADR with `supersedes: [NNNN]` in frontmatter and edit *only* the old ADR's `status:` line to `Superseded-by NNNN`.
- **Numbers are never reused.** Allocate the next NNNN by globbing the highest existing file.
- **`Status: Reverted`** is anton-specific — a decision that was originally accepted, then later removed. Standard MADR has no status for this; the migrated graveyard ADRs (0001–0017) all use it.

## How decisions get here

1. **Intake-driven** — `cluster-intake-gatekeeper` produces ADR-shaped output and hands off to `/adr new`. This is the dominant authoring path.
2. **Human-driven** — invoke the `adr` skill directly when capturing a decision that didn't go through intake (e.g., "we picked Cilium over Calico").
3. **Migration (one-time)** — ADRs 0001–0017 were retrospectively migrated from the old `cluster-intake/references/anton-history.md` removal graveyard. They are labelled `retrospective: true` in frontmatter.

## How decisions get read

- **At session start** — `.claude/hooks/inject_adr_index.py` scans ADR files directly (frontmatter + H1 title), builds a table, and injects it (capped at 40 lines) into every Claude Code session, including subagents. No intermediate index file needed.
- **On demand** — the `adr` skill's `list` workflow filters by `--status` or `--affects` for targeted lookup. `cluster-intake` Step 2 uses this to detect retries of past failures.

## Out of scope (for now)

`context/arch/`, `context/specs/`, `context/plans/`, `context/memory/` — the full `~/.claude/skills/context-repo/` layout. Only `adrs/` is adopted at present.
