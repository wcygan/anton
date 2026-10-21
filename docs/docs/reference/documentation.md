---
title: Documentation and maintenance
---

# Documentation and maintenance

This site is the public home for understanding and operating Anton. Agent procedures that apply across harnesses live in the repository's `.agents/skills/`.

## Where content belongs

| Collection | Answers | Contains |
| --- | --- | --- |
| Overview | What does the platform provide? | Capabilities, architecture, boundaries |
| Guides | How do I do this task? | Operator steps and checks |
| Reference | What rules apply? | Stable facts and contracts |
| Decisions | Why did we choose this? | Numbered architecture decisions |
| Records | What did we learn? | Short, dated outcomes and open questions |

## Keep it public-safe

Every page and asset here is public, including pages that are not in the navigation. Keep these out of the documentation tree:

- credentials and secret values
- exact node endpoints, private hostnames, and the tailnet name
- hardware serials and private workload identities
- detailed inventories and raw operational evidence

Moving material to a private archive later does not remove it from Git history.

Public pages must make sense on their own. Link to public decisions and guides, not to private file paths. Keep committed intent and dated observations clearly apart; this site is not a live health dashboard.

## Keep it current

| When | Do |
| --- | --- |
| Behavior changes | Update the guide that describes it |
| A durable architecture choice is made | Write an ADR under the [decision policy](decisions-policy.md) |
| An investigation or incident closes | Write a short record: trigger, findings, outcome, uncertainty, and the resulting decision or repair |
| Work is planned | Keep plans and tickets in private execution records |

Keep raw evidence only where recovery or reproduction needs it. Do not call a migration complete because files moved; carry unfinished criteria forward. When work closes, update the current guidance and leave a brief outcome rather than another permanent log.

## Diagrams

Use the [visual design system](visual-design.md) for diagrams, theme tokens, and component examples. The production build enforces its rules.

## Verify a change

From the repository root:

```sh
mise exec -- python3 scripts/validate-documentation.py
mise exec -- bun run --cwd docs typecheck
mise exec -- bun run --cwd docs build
```

Look at changed diagrams in light and dark themes and at phone width. Changes to shared safety policy also need `mise exec -- task contracts:validate`. Publishing the site needs separate authorization.
