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

Anton extends standard MADR with **`Reverted`** — "originally accepted, then later removed." Use it for any decision that was once live in the cluster and is now gone.

## Context

What is the situation that prompts this decision? What are the forces at play (technical, organisational, political)? Keep this 1–3 paragraphs. If this is a `retrospective: true` migration record, mark the section "Context (retrospective)" and keep it factual.

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

## Re-adoption guidance (for `Reverted` status only)

Conditions under which this decision could be revisited:

- **Concrete-need reframing** — what would have to change about the cluster's needs
- **Learning-intake reframing** — what new learning angle would justify a timeboxed retry

## Follow-ups

- [ ] Open task / next action
- [ ] Schedule revisit (if applicable)
