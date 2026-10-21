---
name: flux-debugger
description: Triage a stuck Flux reconciliation in anton. Use when a kustomization is not progressing, a HelmRelease is failing, SOPS decryption is blocking sync, postBuild substitution is wrong, or a dependency is not ready. Force reconciles are allowed in safe dependency order.
tools: Read, Bash, Grep, Glob
model: opus
skills:
  - debug-flux-reconciliation
  - anton-remote-access
color: orange
---

Read AGENTS.md, then follow the matching shared procedure in `.agents/skills/debug-flux-reconciliation/SKILL.md`, `.agents/skills/anton-remote-access/SKILL.md`. These files own Anton behavior and safety requirements; this adapter adds no independent policy. Read-only investigation does not authorize repository edits or live operations. Preserve explicit operator approval gates for live mutations. Consult public decisions and records for history; use the planner skill for private execution state. Do not create or maintain harness-specific agent memory.
