---
name: Intake history 2026
description: Running log of cluster-intake-gatekeeper verdicts — candidate, declared intent, decisive factor, ADR number. Used to spot intent drift and recurring containment failures.
type: project
---

Anton's intake decisions in 2026, oldest first. Tight one-line entries; prune when an ADR's status changes.

- **2026-05-04 — ntfy (self-hosted) — concrete need — Add.** Decisive factor: ADR 0007 Trigger 4 explicitly authorized; 2026-05-04 flux-operator postmortem provided empirical proof of detection gap (3d14h CrashLoopBackOff into receiver `"null"`). Single dominant upstream maintainer flagged as yellow; throwaway PVC accepted. ADR number TBD (next allocation by `adr` skill).

**Why:** Track whether intake intents stay honest over time and whether the same containment gates keep being the trouble spot. If "concrete need" entries start lacking paper trails, the gate is drifting toward completionism.

**How to apply:** Read this before declaring intent on a new candidate. If the operator has a string of vague concrete-need intakes, raise the bar on the "I cannot ___" sentence in Step 1.
