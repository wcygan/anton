# Domain docs

Anton uses one domain context.

## Read before exploration

Use QMD to search the `anton-context` collection when work depends on historical records.

Read the relevant source after finding it:

- `context/adrs/` contains durable architecture decisions.
- `context/plans/` contains mutable execution records.
- `context/software.md` contains the software inventory.
- `context/hardware.md` contains the hardware inventory.
- `context/incidents/` and `context/postmortems/` contain operational evidence.

Use `rg` for exact current repository state.

## Decision rules

Accepted ADR bodies are immutable.

Write a replacement ADR when a decision changes.

Plans can change as execution progresses.

Append dated plan log entries instead of rewriting historical entries.

## Vocabulary

Use terms defined by the relevant ADRs and plans.

Do not replace established terms with new synonyms.

Use `domain-modeling` when an important term remains unclear.

## ADR conflicts

State any conflict with an accepted ADR before proposing a change.

Do not silently override an accepted decision.
