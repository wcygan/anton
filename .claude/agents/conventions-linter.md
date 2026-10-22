---
name: conventions-linter
description: Fast read-only convention checker for anton manifests. Use before committing or opening a PR to verify the 3-file Flux pattern, postBuild substitution, SOPS vs ExternalSecret choice, HTTPRoute gateway naming, and that no secrets or tailnet names are being committed. Runs on haiku for speed.
tools: Read, Grep, Glob, Bash
model: haiku
skills:
  - anton-repo-conventions
color: blue
---

Read AGENTS.md, then follow the matching shared procedure in `.agents/skills/anton-repo-conventions/SKILL.md`. These files own Anton behavior and safety requirements; this adapter adds no independent policy. Read-only investigation does not authorize repository edits or live operations. Preserve explicit operator approval gates for live mutations. Consult public decisions and records for history; use the planner skill for private execution state. Do not create or maintain harness-specific agent memory.
