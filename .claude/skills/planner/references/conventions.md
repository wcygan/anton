# Plan conventions reference

Mechanical reference for the `planner` skill. This file is loaded on demand from `SKILL.md`; it's not part of the always-on context.

## File location

```
context/plans/
├── TEMPLATE.md               # canonical anton plan template (mirrored at .claude/skills/planner/references/template.md)
└── NNNN-kebab-slug.md        # one plan per file
```

## Naming convention

`NNNN-kebab-slug.md`

- `NNNN` — 4-digit zero-padded sequential number, allocated as `max(existing) + 1`. Never reuse, never renumber, never gap-fill. Numbers allocated here are independent of ADR numbers (plan 0001 and ADR 0001 coexist).
- `kebab-slug` — lowercase, hyphenated. 4–6 meaningful words from the title. Drop articles, prepositions, adjectives that add no information.
  - "Migrate Tailscale to the new tailnet" → `migrate-tailscale-new-tailnet`
  - "Adopt Longhorn as replicated block storage" → `adopt-longhorn-block-storage`
  - "Roll out kube-prometheus-stack" → `rollout-kube-prometheus-stack`

The slug is human-readable shorthand; the NNNN is the canonical identifier.

## Frontmatter (mandatory)

```yaml
---
status: <Draft|In-progress|Blocked|Done|Abandoned>
opened: YYYY-MM-DD
closed: <YYYY-MM-DD|null>
affects: <category>
intent: <concrete-need|learning|unknown>
related-adrs: []
review-by: <YYYY-MM-DD|null>
---
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | enum | yes | See status enum below |
| `opened` | YYYY-MM-DD | yes | When the plan was created |
| `closed` | YYYY-MM-DD or `null` | yes | Set on `close`; `null` while active |
| `affects` | string (category) | yes | Same canonical list as ADRs |
| `intent` | enum | yes | `concrete-need` / `learning` / `unknown` |
| `related-adrs` | list of NNNNs | yes (may be `[]`) | ADRs that scope this plan |
| `review-by` | YYYY-MM-DD or `null` | required for `intent: learning`, optional otherwise | Date to re-evaluate the plan |

### Status enum

- **`Draft`** — plan is being shaped; Goal and Acceptance criteria are not yet stable. Counts as active in the index.
- **`In-progress`** — work is active. Default status for new plans.
- **`Blocked`** — progress stopped pending a named condition. The Log *must* contain a recent entry naming the blocker and the unblock condition. Counts as active so the blocker stays visible.
- **`Done`** — all Acceptance criteria met and the plan is closed. Terminal.
- **`Abandoned`** — work stopped without meeting Acceptance criteria. The Log's final entry must name the reason. Terminal.

Active statuses appear in the SessionStart injection. Terminal statuses are historical and don't show in the active-plan table.

### `affects` category list

Same canonical list as ADRs (see `.claude/skills/adr/references/conventions.md`):

- `storage`, `observability`, `databases`, `registries`, `demos`, `networking`, `security`, `compute`, `all`

Pick the broadest applicable. For meta/workflow plans that don't fit cluster categories, use `all`.

## Body sections

The template enforces this section order. Do not add or remove sections.

1. **Blockquote summary** (`> ...`) — one sentence right after the H1.
2. **Goal** — what "done" looks like. One paragraph.
3. **Acceptance criteria** — 2–5 outcome bullets as a checkbox list.
4. **Tasks** — actionable checklist, append-only as work uncovers more steps.
5. **Log** — append-only timeline. Format: `- YYYY-MM-DD: <sentence>`. Never rewrite past entries.
6. **References** — pointers to ground truth (related ADRs, Renovate, Flux, memory).

## Mutability rules

Plans differ from ADRs on mutability. The specifics:

| Field / section | Mutability |
|---|---|
| `NNNN` (filename) | Never changes |
| `opened` | Never changes |
| `related-adrs` | Append-only (only add, never remove) |
| `status` / `closed` | Flip via normal lifecycle transitions |
| `review-by` | Can be extended once with a Log entry citing why; further extensions should trigger a re-scope conversation |
| Goal | Stable. Substantial scope change = close-and-new, not silent rewrite |
| Acceptance criteria | Can be refined; refinements must be logged. Wholesale rewrite = scope change, see Goal rule |
| Tasks | Fully mutable — add, check, remove |
| Log | **Append-only**. Never rewrite or delete past entries |
| References | Fully mutable |

## Active vs. terminal

The SessionStart hook surfaces only active plans (`Draft` / `In-progress` / `Blocked`) to conserve instruction budget. Terminal plans (`Done` / `Abandoned`) stay on disk as history but are out of the always-on context. Use `/planner list --all` to see them.

## Interaction with memory

- Auto-memory is for ephemeral, unpredictable cross-session hints ("the last time I hit X, the fix was Y"). Retains because future-me will re-encounter X unexpectedly.
- Plans are for structured, predictable initiative state ("here's what's left on the Longhorn rollout"). Retained because future-me needs to resume deliberately.

When a memory entry starts looking more like a plan (checklist, multiple sessions, acceptance criteria), promote it: open a plan and delete the memory. Don't maintain both.

## Interaction with ADRs

- Plans may be opened *from* an ADR (the Accepted decision triggers the rollout). `related-adrs:` cites the source.
- Plans may surface an ADR *during* execution (a durable decision emerges from the work). Hand off to the `adr` skill on `close done` and link the new ADR in the plan's References.
- Plans never replace ADRs. If something is "we will do X forever" it's a decision → ADR. If it's "here's how we're rolling X out over three weeks" it's a plan.
