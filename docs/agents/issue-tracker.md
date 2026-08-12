# Issue tracker: Local Markdown

Specs and tickets for this repository live under `.scratch/`.

## Conventions

- Use one directory per feature: `.scratch/<feature-slug>/`.
- Store the specification at `.scratch/<feature-slug>/spec.md`.
- Store tickets under `.scratch/<feature-slug>/issues/`.
- Use one file per ticket.
- Number tickets from `01` in dependency order.
- Record triage state with a `Status:` line.
- Append discussion under a `## Comments` heading.

## Publishing

When a skill publishes a specification, write `.scratch/<feature-slug>/spec.md`.

When a skill publishes tickets, write one file per ticket under the feature's `issues/` directory.

## Fetching work

Read the referenced specification or ticket file in full.

## Dependency edges

Record blocking edges with a `Blocked by:` line.

A ticket becomes ready when every listed blocker has status `resolved`.
