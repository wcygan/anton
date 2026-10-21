---
name: planner
description: Create, inspect, update, and close private Anton execution plans for work spanning multiple sessions. Use for migrations, rollout tracking, unresolved acceptance criteria, and resuming an initiative. Architectural choices belong in public ADRs, not execution logs.
---

# Private execution plans

Plans live at repository-root-relative `../anton-private/docs/operations/platform-work/plans/NNNN-kebab-slug.md`. Read that repository's `AGENTS.md` before writing. If the private checkout or records are unavailable, report the missing access; do not create a public substitute or infer there is no active work.

Use a plan when someone returning after two weeks would need it to resume. Ordinary single-session changes do not need a permanent execution record.

## Create

1. List existing plans and allocate `max(ID) + 1`; never reuse IDs. Check protected local legacy records for collisions during the documentation transition.
2. Establish the goal, two to five observable acceptance criteria, initial tasks, authority boundaries, related ADRs, and review date. Use known session context instead of interviewing for information already supplied.
3. Use the [template](references/template.md). The [status enum](references/statuses.txt) is canonical: active Draft, In-progress, Blocked; terminal Done, Abandoned. Learning plans require a review date and exit path.
4. Add a dated opening log entry. Keep sensitive evidence private and reference sources rather than copying runtime inventories.

## Inspect and update

List active plans by default, or all plans when requested. Read the source before relying on a status. Show overdue reviews and invalid statuses explicitly. `mise exec -- python3 scripts/documentation-index.py plans` prints a bounded active index without contacting the cluster.

Update tasks and append dated log entries as work progresses. Preserve the original goal and acceptance criteria unless scope changes explicitly. For a substantial pivot, abandon the old plan with rationale and create a replacement. Preserve uncertainty and pending gates; an old In-progress status is not proof work continues.

## Close

For Done, verify every acceptance condition against actual evidence. If one is unmet, retain it as open or record an explicitly authorized scope change; never silently claim completion. For Abandoned, record the reason and successor if any. Set `closed` and append a dated outcome.

Staleness prompts review, not automatic completion or abandonment. The documentation migration retained historical status and unchecked tasks except where explicit retirement evidence established supersession.

When work ends, update the current public guide, record any architectural choice through the `adr` skill, and keep a brief public-safe record when there is a useful lesson. Keep the full execution log private; do not create agent-specific memory copies.

## Temporary tickets

Feature tickets can live beside private plans under `docs/operations/platform-work/issues/<feature>/`. Keep a short specification and numbered issues with Status, acceptance criteria, and explicit blocking edges. Preserve unresolved criteria when archiving. Existing local untracked scratch material stays with its owner until deliberately migrated.

No plan update authorizes commits, pushes, provider changes, or live operations. Follow the task's existing authority and matching operational procedure.
