---
status: Accepted
date: 2026-04-16
deciders: ['@wcygan']
affects: all
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0011 — Adopt in-repo planning system with `planner` skill

> Plans live at `context/plans/NNNN-kebab-slug.md` as mutable execution state for multi-session initiatives, alongside the immutable ADRs at `context/adrs/`.

## Status

Accepted.

## Context

Anton already has two durable persistence layers and one ephemeral one:

- **ADRs** (`context/adrs/`) — immutable decisions; answer *why the cluster looks like this*.
- **Git log** — immutable commits; answer *what changed*.
- **Auto-memory** — ephemeral cross-session hints; answer *what did I just learn*.

The missing layer is the multi-session initiative — "migrate Tailscale", "adopt Longhorn", "roll out OpenTelemetry". These span many commits and several sessions. Memory is too ephemeral (entries decay as new ones push them out); git log is too coarse (no sense of what's *next*); ADRs are too rigid (decisions, not execution state). The symptom: when a session resumes work on an in-flight initiative, it re-derives context that should have been persisted.

External spec/plan tools (OpenSpec, GitHub's spec-kit, GitHub Issues) were considered and don't fit this repo's shape. OpenSpec and spec-kit assume application/feature development with long-lived feature branches; anton is trunk-based GitOps where the repo *is* the spec. GitHub Issues fragment context off-repo — Claude cannot see active issues without extra tooling, and the solo-operator doesn't need the ceremony of assignees, boards, or labels.

## Decision

We adopt an in-repo planning system that mirrors the ADR pattern:

- **Location**: `context/plans/NNNN-kebab-slug.md`, one file per multi-session initiative.
- **Lifecycle skill**: `.claude/skills/planner/SKILL.md` with four workflows — `new`, `list`, `update`, `close`.
- **Session-start hook**: `.claude/hooks/inject_plans_index.py` scans plan files, filters to active statuses (`Draft` / `In-progress` / `Blocked`), and injects a capped markdown table so every session starts with visibility on what's open.
- **CLAUDE.md**: one-line pointer to the `planner` skill in the Specialized work list. No inline templates in CLAUDE.md — all detail lives in the skill and its `references/`.

Plans are **mutable** where ADRs are immutable: task lists churn, log entries accrue, status flips through the lifecycle. But `Goal` and the `opened:` field are stable — substantial scope changes close the old plan and open a new one, rather than quietly mutating intent.

Plans do not replace memory, Renovate dashboards, or Flux status — they reference those as ground truth. When a memory entry starts looking like an initiative checklist, it gets promoted to a plan and the memory is deleted.

## Alternatives considered

- **Do nothing (rely on memory + ADRs alone)** — rejected. Memory decays and is not self-cleaning; in-flight initiative state gets lost or re-derived session after session. The Tailscale migration memory entry is an existing symptom.
- **OpenSpec / GitHub spec-kit** — rejected. Both tools assume feature/product development with long-lived branches and external state stores. Anton is trunk-based GitOps where the repo is the source of truth; external spec state would fragment context and drift from the cluster.
- **GitHub Issues** — rejected. Splits context off-repo, invisible to Claude at session start without extra tooling, and imposes solo-operator ceremony (assignees, boards, labels) that adds no value for a single-operator cluster.
- **Plain markdown files in `context/plans/` with no skill or hook** — considered. Works fine at 1–2 concurrent plans. Rejected as the committed version because the skill + hook make the system self-sustaining: future sessions discover plans automatically, and the lifecycle discipline (when to close, how to log, memory-to-plan promotion) is documented in one place rather than re-derived per session.

## Consequences

### Accepted costs

- **Surface area**: ~600 lines of skill + references + hook + templates to maintain. Near-mechanical clone of the existing ADR pattern, so maintenance cost is low.
- **Instruction-budget cost**: the SessionStart hook adds ~5–10 lines of context when ≥3 plans are active, ~0 when none are. Capped at `MAX_BODY_LINES = 25` so it cannot balloon.
- **Hygiene burden**: plans must be closed promptly when work completes or dies. The `review-by` flag and anti-patterns section in `SKILL.md` document the failure mode (silent drift into permanent `In-progress`).
- **Renovate-PR tax**: none. No cluster components added.

### Follow-ups

- [ ] Migrate the existing Tailscale migration memory entry to `context/plans/0001-migrate-tailscale-new-tailnet.md` as the first real plan. Delete the memory file once the plan is live.
- [ ] Consider (don't build yet) a `PreToolUse` hook that warns when editing a terminal (`Done` / `Abandoned`) plan — only if silent terminal edits become an observed problem.
- [ ] Revisit this decision after 3 months (around 2026-07-16) to audit whether plans are being closed promptly and whether the active-plan index has stayed useful-sized (≤5 entries). If plans drift unclosed, the system is adding overhead without benefit and should be superseded or simplified.
