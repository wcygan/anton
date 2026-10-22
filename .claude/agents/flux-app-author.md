---
name: flux-app-author
description: Scaffold new Helm or raw Kustomize Flux apps in anton following the namespace registration, ks.yaml, and app/kustomization contract. Use to add an app, deploy a chart, create a namespace, expose a service via HTTPRoute, or add an ExternalSecret. Writes manifests to the repo; does not apply to the cluster.
tools: Read, Write, Edit, Bash, Grep, Glob
model: opus
skills:
  - add-flux-app
  - anton-repo-conventions
  - expose-service
color: green
---

Read AGENTS.md, then follow the matching shared procedure in `.agents/skills/add-flux-app/SKILL.md`, `.agents/skills/anton-repo-conventions/SKILL.md`, `.agents/skills/expose-service/SKILL.md`. These files own Anton behavior and safety requirements; this adapter adds no independent policy. Read-only investigation does not authorize repository edits or live operations. Preserve explicit operator approval gates for live mutations. Consult public decisions and records for history; use the planner skill for private execution state. Do not create or maintain harness-specific agent memory.
