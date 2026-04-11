# ADR template

Canonical anton ADR template. Mirrors `context/adrs/TEMPLATE.md` — keep them in sync. The `adr` skill uses this version when authoring new ADRs; the in-tree copy is the human-facing reference.

Use this exactly. Don't add or reorder sections without updating both copies and `references/conventions.md`.

---

```markdown
---
status: Proposed
date: YYYY-MM-DD
deciders: ['@wcygan']
affects: <storage|observability|databases|registries|demos|networking|security|compute|all>
intent: <concrete-need|learning|unknown>
supersedes: []
superseded-by: null
retrospective: false
---

# NNNN — Title in present tense

> One-sentence summary that makes sense in the injected ADR index.

## Status

`Proposed` | `Accepted` | `Deferred` | `Rejected` | `Reverted` | `Superseded-by NNNN`

## Context

What is the situation that prompts this decision? What forces are at play (technical, organisational, political)? 1–3 paragraphs.

If `retrospective: true`, mark this section "Context (retrospective)" and keep it factual.

## Decision

The decision itself, in active voice. "We will adopt X" / "We will not adopt X" / "We removed X in commit \<sha\>."

## Alternatives considered

- **Do nothing** — what happens if we don't decide?
- **Alternative A** — why rejected
- **Alternative B** — why rejected

For retrospective ADRs, this section is usually `N/A — retrospective record`.

## Consequences

### Accepted costs
- Concrete operational / financial / cognitive cost
- Renovate-PR tax (if a new component)
- Restore-runbook obligation (if stateful)

### Lessons (retrospective only)
- What was learned by trying this and removing it

## Re-adoption guidance (only for `Reverted` status)

Conditions under which this decision could be revisited:

- **Concrete-need reframing** — what would have to change about the cluster's needs
- **Learning-intake reframing** — what new learning angle would justify a timeboxed retry

## Follow-ups

- [ ] Open task / next action
- [ ] Schedule revisit (if applicable)
```

---

## Variant — handoff from `cluster-intake-gatekeeper`

When invoked from `cluster-intake-gatekeeper`, the verdict object substitutes for the interactive interview. The mapping:

| Gatekeeper verdict | ADR `status` | Extra fields | Body emphasis |
|---|---|---|---|
| Add (concrete need) | `Accepted` | — | "Decision" names hand-off skill (`add-flux-app`); "Accepted costs" includes Renovate-PR tax line |
| Add (learning) | `Accepted` | `review-by: YYYY-MM-DD` | "Decision" includes timebox + exit plan; `intent: learning` |
| Defer | `Deferred` | — | Body holds the exact measurable unblock conditions |
| Reject | `Rejected` | — | Body holds the failed gate (1–7) or known-bad pattern, plus reframing suggestion if appropriate |

## Variant — supersession

When `supersede` invokes `new`, the new ADR's frontmatter pre-populates `supersedes: [<old-NNNN>]`. The body should explicitly cite the old ADR in its Context section ("This supersedes ADR <old-NNNN> because…") so the chain is readable from either end.
