# ADR-ready output template

The format the skill (and the `cluster-intake-gatekeeper` subagent) emits at Step 8 of the workflow. Four verdict shapes — **Add (concrete need)**, **Add (learning)**, **Defer**, and **Reject** — each with its own template below.

The goal is that the user can drop the output straight into `docs/docs/decisions/` (or wherever they keep architecture notes) without reformatting.

## Common header (always present)

```markdown
# Cluster intake: <candidate name>

- **Date**: <YYYY-MM-DD>
- **Verdict**: ADD (concrete need) | ADD (learning) | DEFER | REJECT
- **Intent declared**: concrete need | honest learning | both
- **Evaluated by**: cluster-intake skill (or cluster-intake-gatekeeper agent)
- **Project URL**: <upstream repo URL>
- **Helm chart**: <chart source, or "n/a">
- **State owned**: stateless | ephemeral PVC | persistent PVC | cluster-wide CRDs | mutating webhook
```

## Verdict: ADD (concrete need)

```markdown
## Status: Accepted — concrete need

## Context

<One paragraph. What problem does this solve right now? What is the current
alternative (do-nothing, existing component, SaaS)? Why is the current
alternative insufficient? Must include the user's present-day sentence
"I need this because right now I cannot ___.">

## Hard gates

- [x] License & exit cost: <one-line evidence>
- [x] Blast radius: <one-line evidence>
- [x] Reversibility: <one-line evidence>
- [x] Integration fit: <one-line evidence>
- [x] Secrets model: <one-line evidence>
- [x] Tested restore runbook: <"n/a — stateless" OR path to runbook>
- [x] No speculative scaling: <one-line evidence>

## Soft score

| Attribute            | Weight | Score | Weighted | Notes                    |
|----------------------|--------|-------|----------|--------------------------|
| Project liveness     | 3      |       |          |                          |
| Maintenance burden   | 3      |       |          |                          |
| Resource footprint   | 2      |       |          |                          |
| Docs quality         | 2      |       |          |                          |
| Storage requirements | 2      |       |          |                          |
| Community depth      | 1      |       |          |                          |
| Observability hooks  | 1      |       |          |                          |
| **Total**            |        |       | __ / 34  |                          |

Do-nothing delta: **__** (must be ≥4 to accept)

## Known-bad pattern check

None matched. (Or: "Checked against patterns 1–10 in known-bad-patterns.md; no match.")

## Sustainability signals

<Brief bullet-form notes from Step 4 — commit recency, release cadence, bus
factor, helm chart ownership, values schema stability, CNCF status if any.>

## Consequences

**Accepted costs**:
- <one or two bullets — e.g., "one more chart in the Renovate rotation", "one more HelmRelease in flux get hr -A", "~150Mi additional memory">

**Hand-off**:
- Scaffold via `add-flux-app` skill → namespace `<ns>`, source `<oci|helm|git>`.
- Secret source: <SOPS | ESO ClusterSecretStore onepassword-connect | none>
- Exposure: <none | HTTPRoute on envoy-internal | HTTPRoute on envoy-external + DNSEndpoint>
- Post-install verification: `anton-cluster-health` after first reconcile.

## Revisit triggers

Reopen this decision if:
- The component becomes a recurring source of Flux reconcile failures.
- A breaking minor upgrade requires manual intervention more than once.
- Resource usage exceeds the estimate by >50%.
- A better-supported alternative emerges.
```

## Verdict: ADD (learning)

```markdown
## Status: Accepted — learning intake

## Context

<One paragraph. What does the user want to learn? What's the specific thing
they want to understand about this component? "I want to learn X" not
"I want to try X." Cite the user's own words from Step 1.>

## Intent declaration

- **Learning goal**: <one sentence — what specifically to understand>
- **Timebox**: <YYYY-MM-DD review date, default +30 days from install>
- **Exit plan**: <exact command sequence to remove — usually `flux suspend kustomization X && kubectl delete ns X`, plus any finalizer handling>
- **Containment acknowledgement**: <quote the user's statement that this is its own namespace, not replacing any Tier-0 component, and they accept that if it breaks they will delete rather than fix>
- **State handling**: stateless | throwaway data acknowledged | one-line manual backup plan (for learning-intake state, a full tested restore runbook is not required)

## Containment gates (1–5)

- [x] License & exit cost: <one-line evidence>
- [x] Blast radius: <one-line evidence — namespace-scoped, does not touch Tier-0>
- [x] Reversibility: <one-line evidence>
- [x] Integration fit: <one-line evidence — does not fork secrets/ingress/cert story>
- [x] Secrets model: <one-line evidence — reads from standard Secret via ESO or uses throwaway creds in-namespace>

## Containment checks

- [x] Namespace-isolated
- [x] Tier-0 non-interference
- [x] Resource ceiling set: <chart `resources.limits` values>
- [x] Stateful data throwaway (or N/A for stateless)

## What is NOT being evaluated under learning intent

For transparency — these are intentionally not gates here, and that is by
design:

- Project liveness / maintainer count / release cadence — not a factor.
- Community depth / star count — not a factor.
- Observability hooks — nice to have, not required.
- Tested restore runbook — replaced by throwaway acknowledgement.
- Concrete present-day problem — replaced by stated learning goal.

The user is going in with eyes open. Do not treat any of the above as a
reason to downgrade this verdict.

## Consequences

**Accepted costs for the timebox**:
- <one or two bullets — e.g., "~400Mi memory for the duration", "one extra HelmRelease in flux get hr -A">

**Hand-off**:
- Scaffold via `add-flux-app` skill → namespace `<ns>`, source `<oci|helm|git>`.
- Secret source: <SOPS | ESO | throwaway in-namespace>
- Exposure: <none | HTTPRoute on envoy-internal — public exposure is a yellow flag for learning intake, prefer internal-only>
- Calendar reminder: set a review for **<review date>**.

## Review trigger (IMPORTANT)

This verdict expires on **<YYYY-MM-DD>**. At that date, re-run intake with the question: "is this still a learning experiment, or has it become something else?" Outcomes:

1. **Learning done, remove it** — delete per the exit plan above. This is success.
2. **Learning done, now it's concrete need** — re-evaluate under the full production rubric. If it passes, convert to Add (concrete need). If not, remove anyway.
3. **Extend the timebox** — allowed once with a stated reason. A second extension is a yellow flag that this is quietly becoming permanent.

Do not let this decision drift past the review date without a re-evaluation.
Set the calendar reminder now.
```

## Verdict: DEFER

```markdown
## Status: Deferred

## Context

<What was proposed. Why it's not a clear reject, but also not yet ready.>

## What's blocking acceptance

List the exact conditions that would flip this to **Add**:

1. <specific unblock condition — e.g., "user writes and executes a restore runbook">
2. <specific unblock condition — e.g., "a concrete present-day app needs the backing store">
3. <specific unblock condition — e.g., "project ships a 1.0 release with stable values schema">

Each must be a measurable state, not a feeling.

## Hard gate status

- [ ] Failed gate (if any): <name + why>
- [x] Passed gates: <list>

## Sustainability signals worth noting

<If any are yellow/red, note them here so a future re-evaluation has context.>

## What do-nothing looks like in the interim

<One sentence: what is the user going to do until the unblock conditions are met?>

## Revisit trigger

Re-run intake when <specific unblock condition #1> is met. Until then, do not re-evaluate — repeating the same decision with the same inputs is a waste of the user's time.
```

## Verdict: REJECT

```markdown
## Status: Rejected

## Context

<What was proposed and why it was evaluated.>

## Reason for rejection

Choose one (or more):

- **Failed hard gate**: <gate name and specific failure — e.g., "Gate 4 integration fit — chart hard-requires ingress-nginx, would force a second ingress controller alongside envoy-gateway">
- **Known-bad pattern match**: <pattern number and name from known-bad-patterns.md, with the specific reasoning>
- **Historical removal without delta**: <commit SHA from anton-history.md + category — e.g., "previously removed in 889a9662 (Rook-Ceph), no stated delta in scale, maturity, or concrete need">
- **Soft score below threshold**: <total>/34, with the 2 or 3 attributes that dragged it down
- **Do-nothing tiebreaker**: candidate scored <n>, do-nothing scored <m>, delta <4

## What would change this

What, specifically, would need to be different for a future re-evaluation to succeed? Be concrete. "Better project" is not an answer; "project reaches CNCF Incubating" or "adds a stable helm chart to its upstream repo" is.

## Alternatives considered

- **Do nothing** — the current state. What does the user lose by not having this component?
- **<alternative component>** — if one was mentioned or obvious.
- **<SaaS / external tool>** — if applicable.

## Why this isn't a defer

A reject is distinct from a defer: there is no near-term event that would flip this decision. If there is, downgrade the verdict to Defer and list the unblock conditions instead.
```

## Notes on emitting the output

- Write the verdict header first, *then* the body. Forcing yourself to commit to the verdict before rationalizing prevents the matrix-rigging failure mode.
- Keep the whole document under one screen if possible. An ADR nobody reads is worse than no ADR.
- Cite specific commits from `anton-history.md` by SHA when relevant. History is the cheapest teacher.
- Never emit an **Add (concrete need)** verdict without naming the hand-off skill (`add-flux-app`) and the next verification step (`anton-cluster-health`).
- Never emit an **Add (learning)** verdict without recording the timebox, exit plan, and the explicit review date in the ADR. A learning intake without a review date is just permanent intake with extra steps.
- When downgrading from a user's requested ADD verdict, do not lecture. Explain the specific gate that failed and — if appropriate — offer the alternative framing. For example: "This fails Gate 7 under concrete-need framing, but if you wanted to reframe this as learning intake with a 30-day timebox and an exit plan, it would pass the contained-learning variant." Let the user choose.
