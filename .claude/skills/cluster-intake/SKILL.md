---
name: cluster-intake
description: Intake gate for adding new system or infrastructure components to Anton. Asks the user to declare intent (concrete need, honest learning, or both), then applies the matching rubric — full production rubric for concrete need, contained-learning rubric for learning intake — and returns add / defer / reject with an ADR-ready summary. Welcomes honest learning intake (anton is partly a learning cluster; "things that don't scale" are okay when declared) but rejects completionism dressed as need. Read-only — never scaffolds manifests, never applies to the cluster. Use when asking "should I add X", "can I run X on the cluster", "is X worth adopting", "I want to try X", "I want to learn X", "evaluate new component", "vet this helm chart", "cluster intake", "new app decision", before scaffolding a new Flux app, or when tempted by a shiny project on HN. Hands passing candidates off to add-flux-app. Keywords — intake, adopt, install, new component, new app, evaluate, should I run, worth it, learning, experiment, try out, helm chart decision, bring in, stand up, self-host decision, sustainability, vet, gate, rubric, reject, defer, ADR, timebox, exit plan.
allowed-tools: Read, Bash, Grep, Glob, WebFetch, WebSearch
---

# Cluster intake

Read-only decision gate for "should this component join the anton cluster?" Walks hard vetoes first, then a weighted soft score, then returns an add / defer / reject recommendation with an ADR-ready summary. Never scaffolds files, never applies manifests, never commits — that is what `add-flux-app` is for, *after* this skill says yes.

## Why this skill exists

Anton has paid real tuition on loose intake — Rook-Ceph, the full LGTM observability stack, CloudNativePG, Dragonfly, TiDB, Scylla, Redpanda, and Harbor were all installed and later removed. But not every removal was a mistake. Some of those components (TiDB, Scylla, Redpanda) were honest learning experiments that served their purpose: tried it, learned it, moved on. Anton is partly a learning cluster, and "things that don't scale" are explicitly welcome when that's the point.

This skill is a gate, not a wall. It catches the *wrong* kind of intake — completionism dressed up as need, speculative production patterns, and adds that will quietly accrete into maintenance debt — while making space for honest learning intake with a declared timebox and an exit plan.

## Three intents, three rubrics

Every intake decision starts with **what is this for?** The user must pick one:

| Intent | Example sentence | Rubric applied |
|---|---|---|
| **Concrete need** | "I need this because right now I cannot ___." | Full production rubric — hard gates + sustainability + full soft score |
| **Honest learning** | "I want to learn ___; I know it may be removed; my timebox is ___; my exit plan is ___." | Contained-learning rubric — blast-radius / reversibility / integration / secrets gates only + timebox + exit plan |
| **Completionism-as-need** | "Every real cluster has ___." / "My stack feels incomplete without ___." | Reject. The pattern is what produced the LGTM removal. |

The skill's job is to accept the first two honestly and reject the third honestly. It does **not** lecture the user on whether a learning experiment is "worth it" — that's their call. The gate's job is to make sure learning intake is *contained* (can't take down the rest of the cluster) and has a *known exit* (won't accidentally become permanent).

## Scope

| Concern | Owner | Output |
|---|---|---|
| Evaluate a candidate component | **this skill** | add / defer / reject + ADR summary |
| Scaffold a new Flux app | **`add-flux-app`** | 3-file manifests |
| Expose a service | **`expose-service`** | HTTPRoute + DNSEndpoint |
| Secret store choice (SOPS vs ESO) | **`anton-repo-conventions`** | reference |
| Cluster health before/after add | **`anton-cluster-health`** | triage |
| Remove / retire an existing component | out of scope | — |

## Hard rules

- **Never scaffold files** during intake. The rubric runs *before* any `add-flux-app` invocation. If intake passes, hand off explicitly.
- **Never run mutating commands** — no `kubectl apply`, `flux reconcile`, `sops -e -i`, `git commit`, `helm install`, `gh pr merge`.
- **Never recommend adding anything already in the removal graveyard** without the user stating an explicit delta: what changed about the component, what changed about the cluster's need, OR that the intent this time is declared learning (which is itself a valid delta from a prior concrete-need attempt).
- **Never skip the containment gates.** Gates 1–5 (license, blast radius, reversibility, integration fit, secrets model) apply under every intent. A learning experiment that forks the secrets story or takes out Cilium is still a reject.
- **Never lecture the user on whether their learning experiment is worthwhile.** The gate's job is containment and honest intent declaration, not judging the educational value of the user's choices. If the user declares honest learning intent with a timebox and an exit plan, your job is to help them run it safely, not to argue them out of it.
- **Never accept "concrete need" from a completionism sentence.** If the user's "I cannot ___" resolves to "my stack feels incomplete" or "every real cluster has this," ask once whether they want to reframe as a learning intake. If they insist it's concrete need when it isn't, reject under Gate 7.

## Green-path: the 30-second heuristics

Apply the short-circuit filter first. If any fire, stop — do not run the full rubric, do not fill a matrix. Details → [heuristics](references/heuristics.md).

## Full workflow

### Step 1 — Frame the candidate and declare intent

Restate in one paragraph, filling any gap by asking the user:

- **What is it?** Name, project URL, helm chart source.
- **What intent?** One of:
  - **Concrete need** — "I need this because right now I cannot ___."
  - **Honest learning** — "I want to learn ___; I know it may be removed; my timebox is ___; my exit plan is ___." All four blanks must be filled.
  - **Both** — there's a real need AND a learning angle. Apply the concrete-need rubric; the learning angle is a bonus, not a softener.
- **What is the current alternative?** "Do nothing" or an existing component or a SaaS — name it explicitly.
- **What state does it own?** Stateless, ephemeral PVC, persistent PVC, cluster-wide CRDs, mutating webhooks.
- **Who uses it?** You alone, family, public internet.

If the user cannot pick an intent, or picks "concrete need" but can't complete the sentence, ask once: **is this actually a learning intake?** It's legitimate to say yes — honest learning intake is an accepted path on anton. What is **not** legitimate is smuggling completionism in as concrete need; if the "I cannot ___" sentence turns out to be "my stack feels naked without it," it's completionism — reject under Gate 7.

Intent is the axis that decides which rubric applies:

- **Concrete need or both** → full production rubric (all 7 hard gates + sustainability + full soft score)
- **Honest learning** → contained-learning rubric (gates 1, 2, 3, 4, 5 only; skip sustainability gating; require a timebox and exit plan)
- **Completionism-as-need** → reject, cite pattern #10 in [known-bad-patterns](known-bad-patterns.md)

### Step 2 — Check the removal graveyard (now in `context/adrs/`)

Before anything else, check if this component or its category is already in anton's removal history. The removal graveyard has been migrated into the ADR system:

```sh
git log --oneline --all --grep='remove\|rip\|drop\|abandon\|descope' -i | head -50
```

Then query the ADR index for prior `Reverted` decisions:

- `Glob('context/adrs/0[0-9][0-9][0-9]-*.md')` — list all ADRs
- For each, read the frontmatter and filter for `status: Reverted`
- Surface any whose `affects:` matches the candidate's category, *or* whose title clearly references the same component
- Read each matched ADR's "Re-adoption guidance" section — that holds the conditions under which a re-attempt would be valid
- Read `context/adrs/RE-ADOPTION-RUBRIC.md` for the policy on which categories require an explicit intent declaration before re-adopting

If the candidate or its category matches a `Reverted` ADR, demand an explicit delta from the user (concrete-need reframing) **or** an explicit learning-intake declaration with timebox + exit plan (learning-intake reframing). The matched ADR's Re-adoption guidance section spells out the acceptable forms. If neither path applies, reject under the matched ADR's lesson.

### Step 3 — Run the hard vetoes (any red = reject, no override)

Seven gates. Each is pass/fail, measured in ≤2 minutes. Full measurement procedure → [rubric](references/rubric.md#hard-gates).

Under **learning intent**, only gates 1–5 are evaluated (the containment gates — they protect the rest of the cluster regardless of intent). Gates 6 and 7 are replaced by the learning-specific checks described in [rubric → Contained learning variant](references/rubric.md#contained-learning-variant).

1. **License & exit cost** — permissive OSS; uninstall is `flux suspend` + `kubectl delete ns` without orphaned finalizers or CRDs you still need. *(Applies to all intents.)*
2. **Blast radius** — failure degrades *only* the component's own app, not CNI/DNS/storage/auth/ingress. *(Applies to all intents.)*
3. **Reversibility** — removable in <30 min with no data-migration ritual. *(Applies to all intents.)*
4. **Integration fit** — speaks Gateway API + ESO + Prometheus + SOPS. No parallel ingress / secret / cert / monitoring stack. *(Applies to all intents — a learning experiment that forks the secrets story is still a mess.)*
5. **Secrets model** — pulls from 1Password via ESO. No hardcoded admin passwords. No sealed-secrets or its-own-secret-CRD. *(Applies to all intents.)*
6. **Tested restore runbook (stateful, concrete-need only)** — written *before* install. Untested backups are folklore. Under learning intent, a stateful component is allowed without a restore runbook **if and only if** the user explicitly acknowledges the data is throwaway — see the contained-learning variant.
7. **Honest intent (concrete-need only)** — the user's "I need this because right now I cannot ___" sentence resolves to a real present-day problem, not completionism in disguise. Under learning intent, this gate is replaced by the timebox + exit-plan check.

### Step 4 — Skim sustainability signals

Five-minute budget on the project's GitHub. Red flags do not auto-fail but flow into the soft score. Full signal list → [sustainability-signals](references/sustainability-signals.md).

Minimum skim:
- Commits in last 30 days
- Release in last 6 months
- More than one active maintainer
- Official helm chart in-repo (not community; k8s-at-home/charts is **deprecated** — treat community charts as yellow at best)
- CNCF sandbox / incubating / graduated status (prior, not a gate)
- Median time-to-first-response on open issues

### Step 5 — Fill the weighted soft score *(concrete-need intent only)*

Score `2` / `1` / `0` across 7 attributes, weighted. Reject if total < 22/34. Full matrix → [rubric](references/rubric.md#soft-scoring).

Under **learning intent**, skip this step and instead fill the contained-learning checklist → [rubric → Contained learning variant](references/rubric.md#contained-learning-variant). The focus is containment (namespace isolation, Tier-0 non-interference, predictable blast radius), not sustainability — it's fine if the project has two stars and one maintainer, as long as the user is going into it with eyes open and a timebox.

### Step 6 — Do-nothing tiebreaker *(concrete-need intent only)*

Score "do nothing" on the same matrix. If the candidate is within 4 points of do-nothing, reject — the intake tax is worth ~4 points by itself.

Under learning intent, the tiebreaker does not apply. Learning has value that do-nothing doesn't — the whole point is the user wants to touch it.

### Step 7 — Known-bad pattern check

Cross-check against well-known homelab landmines. → [known-bad-patterns](references/known-bad-patterns.md). Any match that is **not** a declared learning intake is an auto-reject. Several patterns (HA Postgres on 3 nodes, full LGTM observability, self-hosted email) have an explicit "learning-intake variant is okay if…" carve-out; read the pattern's learning note before auto-rejecting.

### Step 8 — Return a structured recommendation, then hand off to `adr`

Every verdict — Add, Defer, or Reject — is recorded by handing off to the **`adr` skill** (`/adr new`). That skill owns the canonical anton ADR template (`.claude/skills/adr/references/template.md`), allocates the next NNNN, and writes the ADR file under `context/adrs/`. Do not stop at "ADR-ready" — the verdict must land in `context/adrs/`.

The four verdict shapes:

- **Add (concrete need)** — all 7 hard gates pass, soft score ≥22, do-nothing clear, no known-bad match. Hand off to `adr` skill with `status: Accepted`, `intent: concrete-need`. Then hand off to `add-flux-app` to scaffold manifests.
- **Add (learning)** — gates 1–5 pass, the contained-learning checklist is complete (timebox, exit plan, containment verified), the user has consciously accepted the sustainability / resource trade-offs. Hand off to `adr` skill with `status: Accepted`, `intent: learning`, and `review-by:` set to the declared review date (a learning intake without a review date is just permanent intake with extra steps — if missing, downgrade to Defer). Then hand off to `add-flux-app`.
- **Defer** — a blocking prerequisite is missing (e.g., no timebox declared for a learning intake, no tested restore runbook for stateful concrete-need intake, marginal soft score under concrete need). Hand off to `adr` skill with `status: Deferred` — the ADR's body holds the exact conditions to unblock. No further hand-off; the ADR *is* the durable record.
- **Reject** — any containment gate (1–5) fails, completionism-as-need detected, known-bad match without a learning-intake carve-out, or historical-removal match without stated delta. Hand off to `adr` skill with `status: Rejected` — the ADR's body explains which gate and why, and — if appropriate — whether reframing as a declared learning intake would change the answer. No further hand-off.

## What this skill does NOT do

- Does not write manifests — that is `add-flux-app`
- Does not expose services — that is `expose-service`
- Does not pick between SOPS and ESO — that is `anton-repo-conventions`
- Does not verify cluster health — that is `anton-cluster-health`
- Does not install the thing, ever
- Does not make unsolicited recommendations for components the user has not named

## Related skills

- `add-flux-app` — run *after* this skill returns **Add**
- `anton-repo-conventions` — for SOPS vs ESO decisions once a candidate is accepted
- `anton-cluster-health` — verify before and after adding anything non-trivial
- `anton-upgrade-audit` — every new component raises the future Renovate-PR tax; pair intake with upgrade cadence

## Anti-patterns

- **Rejecting honest learning intake.** If the user has declared learning intent with a timebox and exit plan, and the candidate passes gates 1–5, do not veto it for being "speculative" or "doesn't solve a present-day problem" — that's the whole point of a learning cluster.
- **Accepting completionism disguised as need.** The user says "I need this" but the sentence that completes "I cannot ___" is really "my stack feels naked." Ask once to reframe; reject if they don't.
- **Running Step 5 before Step 3.** Soft-scoring a candidate that will fail a containment gate is wasted work.
- **Making exceptions to containment gates (1–5).** The word for that is "regret." These protect the rest of the cluster regardless of intent.
- **Skipping Step 2 (the removal graveyard).** History is the cheapest teacher anton has. But note that a graveyard hit under declared learning intent with a stated delta is valid — "I want to actually learn Rook-Ceph this time, timebox 30 days, exit plan is delete the namespace" is an honest learning intake.
- **Lecturing the user on whether their learning is "worth it."** Not your call.
- **Evaluating components the user did not ask about.** This skill is reactive, not speculative.
