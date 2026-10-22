---
status: Accepted
date: 2026-04-16
deciders: ['@wcygan']
affects: all
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0011-adopt-in-repo-planning-system
---

# 0011 — Adopt an in-repository planning system

> Track multi-session work in mutable Markdown plans in the repository, alongside immutable ADRs.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

Memory entries and ADRs alone did not preserve active execution state well from one session to the next.

## Decision

Use mutable Markdown plans in the repository for initiatives that span several sessions. A plan tracks its goal, status, tasks, and dated progress. When scope changes substantially, close the plan and open a new one rather than silently changing its goal.

The original implementation included a planning procedure and a session discovery mechanism.

## Alternatives considered

- **Memory and ADRs only:** lose execution state between sessions.
- **External project tools:** separate context from the GitOps source of truth and add overhead for a single-operator cluster.
- **Plain files with no lifecycle or discovery:** simpler at first, but stale plans become invisible.

## Consequences

Plans are mutable execution records. They are not architectural decisions and not evidence about the live cluster. A plan should point to the real source of truth for status and close when its work ends.

The original decision named harness-specific skills and hooks. Those were implementation details and do not constrain current harness-neutral documentation or procedures.
