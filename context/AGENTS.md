# context/

Goal: Maintain durable Anton decision and execution records.

Success means:
- ADRs capture decisions and remain immutable after acceptance.
- Plans capture mutable execution state and append logs as work progresses.
- New records use the next available number and the local templates.

Stop when: the decision or plan can be found by future agents without mining chat history.

## ADRs

ADRs live in `context/adrs/NNNN-kebab-slug.md`. Allocate the next number by listing existing ADRs. Keep accepted ADR bodies immutable. To revise a decision, write a new ADR with `supersedes: [NNNN]` and update only the old ADR status to `Superseded-by NNNN`.

Use `Reverted` for decisions that were accepted and later removed. Use `context/adrs/RE-ADOPTION-RUBRIC.md` when a removed component is reconsidered.

## Plans

Plans live in `context/plans/NNNN-kebab-slug.md`. They are mutable execution records. Update tasks and append dated log entries as work progresses. Use `context/plans/TEMPLATE.md` for shape and status values.

## Validation

```sh
rg -n "^status:" context/adrs context/plans
rg -n "Superseded-by|supersedes" context/adrs
```
