---
name: planner
description: Anton planner skill — author, update, and close multi-session initiatives (migrations, rollouts, long-running refactors) in `context/plans/`. Use when starting a multi-session initiative, tracking next steps on in-flight work, migrating a memory entry to a durable plan, closing a completed initiative, or reviewing what's open. Plans live at `context/plans/NNNN-kebab-slug.md` and are mutable — they capture execution state (what's next, what's blocked, log of decisions made during work) while ADRs capture immutable decisions (why). The active-plan index is built by scanning plan files directly and injected into every Codex session by `.Codex/hooks/inject_plans_index.py`. Keywords — plan, planner, initiative, track work, multi-session, next steps, checklist, migration plan, rollout plan, roadmap, in-flight, blocker, close plan, review-by, exit plan, timebox, memory-to-plan handoff.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Planner

Anton-local skill for the in-repo plan lifecycle. Owns four workflows: **new**, **list**, **update**, **close**. Plans live at `context/plans/NNNN-kebab-slug.md` and are **mutable** — the body is edited as work progresses, tasks get checked off, the log grows.

## Why this skill exists

Anton already has two complementary persistence layers:

- **ADRs** (`context/adrs/`) — immutable decisions. Answer *why*.
- **Auto-memory** — ephemeral cross-session hints. Answer *what did I just learn*.
- **Git log** — immutable commits. Answer *what changed*.

But there's a missing layer: the multi-session initiative — "adopt Longhorn", "migrate Tailscale", "roll out OpenTelemetry". These span many commits and several sessions. Memory is too ephemeral (decays as new entries push it out); git log is too coarse (no sense of what's *next*); ADRs are too rigid (decisions, not execution state).

Plans fill that gap. They're **in-repo** (survive across sessions without relying on memory), **mutable** (task lists churn), **discoverable at session start** (via the SessionStart hook), and **trunk-compatible** (just files edited on main — no long-lived branches).

The skill is anton-local. Format is intentionally compatible with the global `context-repo` skill but this skill never delegates to that one.

## Hard rules

- **Plans are mutable — but carefully.** Task lists, logs, and status flip freely. **Goal** and **Acceptance criteria** should change only when the scope itself changes; substantial scope changes should `close` the plan as abandoned and `new` a replacement rather than quietly mutating the intent.
- **Numbers are never reused.** Next number is `max(existing) + 1`, zero-padded to four digits.
- **Active statuses** are `Draft`, `In-progress`, `Blocked`. Terminal statuses are `Done`, `Abandoned`. Only active plans are surfaced in the SessionStart index.
- **Close on done.** Plans should not drift into a permanent In-progress state. If nothing has changed in >30 days, mark `Blocked` with a reason, or `close` as abandoned.
- **Plans point at ground truth; they do not duplicate it.** Renovate dashboards, Flux kustomization status, memory entries — reference them, don't mirror them.
- **Plans do not replace ADRs.** If a plan surfaces a durable architectural decision during execution, hand off to the `adr` skill to record it. Link the new ADR from the plan's References section.

References:
- Field reference, status enum, and immutability rules → [conventions](references/conventions.md)
- Canonical template for new plans → [template](references/template.md)

## Workflow — `new`

Triggered by:
- The user says "open a plan for X" / "start tracking X" / `/planner new "<title>"`
- The user wants to promote an in-flight memory entry into a durable plan
- The user commits to a multi-session migration, rollout, or refactor

Before running the full workflow, **ask**: does this really need a plan? If the work is a single commit, a Renovate PR, or something that will finish in this session, say so and decline. Plans are for work that spans sessions.

### Steps

1. **Allocate the next number.** `Glob('context/plans/0[0-9][0-9][0-9]-*.md')`. Sort. Next number is `max + 1`, zero-padded to 4 digits. Never reuse.

2. **Generate the slug.** Lowercase, kebab-case, drop articles/prepositions, 4–6 meaningful words. Example: "Migrate Tailscale to the new tailnet" → `migrate-tailscale-new-tailnet` → `0001-migrate-tailscale-new-tailnet.md`.

3. **Interview the user.** Ask only for what isn't already known:
   - **Title** (one short sentence, imperative or descriptive)
   - **Goal** (one paragraph — what "done" looks like in plain language)
   - **Acceptance criteria** (2–5 outcome bullets, not tasks — conditions that must be true at close)
   - **Initial task list** (3–10 concrete next steps; more will accrue during execution)
   - **`affects`** — same category list as ADRs (`storage`, `observability`, `networking`, `security`, `compute`, `all`, etc.)
   - **`intent`** — `concrete-need` / `learning` / `unknown`
   - **`related-adrs`** — list of ADR NNNNs that scope this plan (usually the decision that triggered the work)
   - **`review-by`** — required for `intent: learning`, optional otherwise. Date to re-evaluate.
   - **Initial log entry** — one-line note of *why now*, to anchor the history.

4. **Write the plan file** at `context/plans/NNNN-slug.md` using the shape from [template](references/template.md). Set `status: In-progress` (or `Draft` if the user is still shaping the goal), `opened: YYYY-MM-DD` to today.

5. **If this replaces an in-flight memory entry**, tell the user to remove the memory file (auto-memory is not self-cleaning). Cite the exact path. The plan supersedes the memory.

6. **Confirm to the user** with the file path, the plan number, and a reminder that the SessionStart hook will pick it up on the next session.

## Workflow — `list`

Triggered by:
- `/planner list` — default, shows active plans only
- `/planner list --all` — include terminal (Done / Abandoned)
- `/planner list --status <X>` or `--affects <X>` — filter

### Steps

1. `Glob('context/plans/0[0-9][0-9][0-9]-*.md')`.
2. Read frontmatter of each. Extract `status`, `opened`, `closed`, `affects`, `intent`, `related-adrs`, `review-by`, and the H1 title.
3. Apply filters:
   - Default: keep only `Draft` / `In-progress` / `Blocked`
   - `--all`: no filter
   - `--status X`: case-insensitive exact match
   - `--affects X`: substring match on the `affects:` field
4. Format as a markdown table sorted by NNNN. Columns: #, Title, Status, Opened, Review-by, Related ADRs.
5. If a plan has `review-by` ≤ today and status is still active, flag it with `⚠` in the Status column.

## Workflow — `update`

Triggered by:
- `/planner update <NNNN>` — the user wants to edit an existing plan
- The user says "check off X on plan NNNN" / "log Y on plan NNNN" / "mark NNNN blocked"

This is the most-used workflow. The skill doesn't wrap every possible edit — it knows the plan's shape and uses the ordinary `Edit` tool to make targeted changes.

### Common edit recipes

- **Check off a task.** Find the task line in the **Tasks** section and replace `- [ ] text` with `- [x] text` (preserve exact indentation). Then append a one-line entry to the **Log** with today's date.
- **Add a task.** Append to the **Tasks** section under the appropriate heading (or at the end). Keep the task imperative, concrete, and verifiable.
- **Log a decision or surprise.** Append to the **Log** section. Format: `- YYYY-MM-DD: <one sentence>`. The log is append-only; never rewrite past entries.
- **Flip to `Blocked`.** Edit the `status:` line in frontmatter and append a Log entry naming the blocker. Don't lose visibility — blocked plans should name a concrete unblock condition in the Log.
- **Un-block.** Flip `status:` back to `In-progress` and log the resolution.
- **Refine acceptance criteria.** Edit the **Acceptance criteria** section and log the refinement so the history explains the change. If the refinement is large enough to change what "done" means, consider `close` + `new` instead.

### Steps

1. **Read the plan.** `Read('context/plans/NNNN-*.md')`. Confirm it exists and isn't terminal (`Done` / `Abandoned`). Terminal plans should not be edited — log a new plan instead if the work is resuming.
2. **Make the edit(s)** via `Edit` with precise old/new strings. One edit per change; keep diffs small.
3. **Append a Log entry** for anything non-trivial (checking off a single task may skip the log if it's a small step; status changes and new tasks should always log).
4. **Confirm to the user** with a one-line summary of what changed.

## Workflow — `close`

Triggered by:
- `/planner close <NNNN> done "<closing note>"`
- `/planner close <NNNN> abandoned "<reason>"`

### Steps

1. **Read the plan.** Confirm it's not already terminal.
2. **Verify acceptance criteria** (for `done` only). Walk through the Acceptance criteria checklist. If any are unchecked, ask the user explicitly: "criterion X is unmet — close as `done` anyway, or re-scope?" Don't close with false-done signals.
3. **Flip the frontmatter**: `status:` to `Done` or `Abandoned`, `closed:` to today's date.
4. **Append a final Log entry** with the closing note.
5. **Offer an ADR handoff (only on `Done`).** Ask: "did this plan surface a durable architectural decision worth recording as an ADR?" If yes, invoke the `adr` skill with a pre-populated title drawn from the plan's Goal. If no, move on.
6. **Confirm to the user** with the file path and the terminal status. The SessionStart hook will drop the plan from the next session's index automatically.

## What this skill does NOT do

- Does not write Flux manifests — that is `add-flux-app`.
- Does not make architectural decisions — that is `adr`.
- Does not auto-close stale plans. A `review-by` breach is flagged in `list`; the operator still closes manually.
- Does not duplicate cluster state, Renovate state, or git log. Plans reference these sources; they do not mirror them.
- Does not push, commit, or tag — the user owns git operations.
- Does not delete plans. Terminal plans are append-only history.
- Does not replace auto-memory for ephemeral cross-session hints. Memory stays; plans capture the durable "what's next" layer.

## Related skills and agents

- `adr` — hand off here on `close done` if a durable decision emerged. Link the new ADR back from the plan's References section.
- `cluster-intake-gatekeeper` — may hand off to `planner` (as well as `adr`) when an `Add (learning)` verdict comes with a multi-session rollout plan that needs tracking beyond the ADR's own checklist.
- `debug-flux-reconciliation` / `anton-cluster-health` — reactive; a plan is the *forward-looking* companion to these. If a reactive session surfaces follow-up work that spans sessions, open a plan.

## When a plan is NOT warranted

- Single-commit fixes
- Renovate PR triage — use `anton-upgrade-audit` instead; the Renovate dashboard is ground truth
- Read-only investigations with no committed output
- Work that will finish in the current session
- "I'll probably want to do X someday" — not a plan, that's speculation. Revisit when the work is actually starting.

Rule of thumb: *if I walk away for two weeks, would I need this file to pick up where I left off?* If yes, open a plan. If no, skip it.

## Anti-patterns

- **Opening a plan for work that fits in one commit.** Pure overhead. Skip it.
- **Duplicating memory into a plan, or a plan into memory.** Pick one home per piece of state. The plan is canonical for execution state; memory is canonical for ephemeral hints. When in doubt, promote to plan and delete the memory.
- **Editing the Goal to reflect a pivoted scope.** That erases history. `close abandoned` + `new` instead.
- **Leaving a plan `In-progress` for >30 days with no Log entries.** Either the work died (close as abandoned) or it's actually blocked (flip to `Blocked` and name the blocker). Silent drift is the failure mode this system exists to prevent.
- **Letting the active-plan list grow past ~5.** If you have more concurrent initiatives than that, the bottleneck is focus, not tooling.
