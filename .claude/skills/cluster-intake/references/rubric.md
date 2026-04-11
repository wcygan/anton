# Intake rubric

The full scoring procedure invoked from Steps 3, 5, and 6 of the main workflow. Structure depends on intent (declared in Step 1):

- **Concrete need**: [Hard gates](#hard-gates) (all 7) → [Soft scoring](#soft-scoring) → [Do-nothing tiebreaker](#do-nothing-tiebreaker).
- **Honest learning**: [Hard gates](#hard-gates) (gates 1–5 only — the **containment** gates) → [Contained learning variant](#contained-learning-variant). No soft score, no do-nothing tiebreaker.
- **Completionism-as-need**: Skip straight to reject.

The containment gates (1–5) run under every intent because they protect the rest of the cluster regardless of why the candidate is being evaluated.

## Hard gates

Seven gates. Every one is pass/fail. Any red rejects the candidate — soft-score is not evaluated at all. Do **not** rationalize around these.

### Gate 1 — License & exit cost

**Green** — Apache 2.0, MIT, BSD, MPL, GPL family. Data stored in open formats (Postgres, SQLite, plain JSON/YAML, object storage). Uninstall is `flux suspend kustomization X` + `kubectl delete ns X`.

**Red** — Proprietary core / "open core" with critical features behind a license. Data locked in a custom binary format. Uninstall leaves orphaned CRDs that other apps still reference, dangling finalizers, or data that must be exported via a vendor tool.

**Measure in 2 minutes**: read `LICENSE` in the upstream repo; grep the helm chart for `CustomResourceDefinition` and cross-reference against what other apps use.

### Gate 2 — Blast radius

**Green** — Failure degrades one feature. The component is an app, not infrastructure: losing it does not take down DNS, CNI, storage, ingress, cert issuance, or secret resolution.

**Red** — Sits on the data path for everything else (CNI replacement, CSI driver, mutating admission webhook, cluster DNS provider, auth proxy in front of other apps). A bad upgrade at 2am takes the cluster with it.

**Measure**: does the helm chart install a `MutatingWebhookConfiguration` or `ValidatingWebhookConfiguration` that matches `*`? Does it replace an existing Tier-0 component (Cilium, cert-manager, envoy-gateway, external-dns, ESO)? If yes, red.

### Gate 3 — Reversibility

**Green** — Removable in under 30 minutes with zero data-migration ritual. PVCs can be deleted or re-attached elsewhere. CRDs are scoped to this component or removable independently.

**Red** — Requires a dedicated data export step before uninstall. Installs CRDs shared with other components. Leaves finalizers that block namespace deletion. Uses a storage class that other apps have now started depending on.

**Measure**: read the upstream "uninstall" docs. If there isn't one, that is itself a red. If the section is longer than the install section, that is a red.

### Gate 4 — Integration fit

**Green** — Speaks Gateway API (not `Ingress`), reads secrets from `Secret` objects (ExternalSecret-compatible), exposes `/metrics` in Prometheus format, accepts config from a mounted file or env vars. Ships a `ServiceMonitor` or has a chart option for one.

**Red** — Ships its own ingress controller, its own cert issuer, its own secret CRD, its own monitoring sidecar, or its own DNS server. Anton already has one of each; a second forks the story and doubles the maintenance surface.

**Measure**: grep the chart's default values for `ingress:`, `cert:`, `sealed`, `tls.autoGenerate`. Any of these that aren't off-by-default are a yellow flag; any that are structural are red.

### Gate 5 — Secrets model

**Green** — All secrets arrive via `Secret` objects, which means ExternalSecret can populate them from 1Password via the `onepassword-connect` ClusterSecretStore. Admin credentials are generated on first-run or supplied via secret, never baked into values.

**Red** — Default values include a hardcoded admin password. Ships its own secret CRD (sealed-secrets, vault-secrets-operator) that you would have to operate in parallel with ESO. Requires a pre-created Kubernetes `ServiceAccount` token stuffed into a config file.

**Measure**: scan `values.yaml` for `password:`, `secretKey:`, `token:`, `clientSecret:`. Any non-empty default is a red.

### Gate 6 — Tested restore runbook *(concrete-need, stateful only)*

**Applies to**: concrete-need intent with stateful data. Does **not** apply under learning intent (see the contained-learning variant below for how learning handles state).

**Green** (stateless) — Not applicable, gate auto-passes.

**Green** (stateful) — A written runbook exists *before* install that covers: what backs up the data, where it is stored, how to restore into a fresh namespace, and the runbook has been executed end-to-end at least once on a throwaway instance.

**Red** — "I'll figure out backups after it's running." "Velero will handle it." "I'll set it up next weekend." Every homelabber who has lost data said this first.

**Measure**: ask the user for the runbook path. If it doesn't exist, gate fails. No exceptions. See critic findings — untested backups are folklore.

### Gate 7 — Honest intent *(concrete-need only)*

**Applies to**: concrete-need intent. Does **not** apply under learning intent (see the contained-learning variant for the equivalent check).

**Green** — The user's "I need this because right now I cannot ___" sentence resolves to a concrete, present-day, specific failure mode. Not "my dashboards are ugly" but "I can't see why app X latency spiked yesterday because I have no logs." Not "I need HA" but "app X went down for 45 minutes last Tuesday and I need to be able to survive a single-node reboot during an OS upgrade."

**Red** — The "I cannot" resolves to completionism ("my stack feels incomplete"), social proof ("everyone runs this"), or speculation ("for when I scale," "industry standard"). These are all patterns the LGTM-stack removal commit is made of.

**Ask-once protocol** — if the user's sentence smells like completionism, ask exactly once: *"Is this actually a learning intake? That's a valid path — you'd just need to declare a timebox and exit plan."* If they say yes, re-enter the workflow at Step 1 with learning intent. If they insist it's concrete need when it isn't, reject under this gate.

**Not failure modes of this gate** (these are legitimate concrete need):
- "I want HA Postgres because my primary crashed last month and restore took four hours" → concrete incident.
- "I need a metrics stack because I had an outage and couldn't diagnose it" → concrete incident.
- "I need Harbor because I want to rebuild images inside my network" → concrete requirement.

These would have passed Gate 7 even under the strict framing. The gate is only catching completionism-as-need.

## Contained learning variant

Runs under **honest learning intent** as a replacement for gates 6–7 and the soft score. The containment gates (1–5) still apply.

The goal of this section is **not** to judge whether the learning is "worth it" — that's the user's call. It's to make sure the learning experiment is contained and has a known end, so it doesn't quietly become permanent or take down something else when it fails.

### Required declarations

The user must state, before install:

1. **What they want to learn** — one sentence. "I want to understand how distributed Ceph placement groups work" is fine. "I want to try Rook-Ceph" is fine. "Because I saw it on HN" is not.
2. **Timebox** — an explicit review date. 7 days, 30 days, 90 days — user picks, but it must be a date, not "eventually." Default to 30 days if the user doesn't pick.
3. **Exit plan** — the exact command sequence to remove the component. Usually `flux suspend kustomization X && kubectl delete ns X`, plus any finalizer handling. The exit plan has to fit in the ADR body.
4. **Containment acknowledgement** — an explicit "this lives in its own namespace, it does not replace any Tier-0 component, I accept that if it breaks I will delete it rather than fix it." Get this on the record.

If any of the four is missing, the verdict is **Defer** until the user provides it. No soft-scoring, no arguing.

### Containment checks

These are *different* from the production hard gates — they are sanity checks specifically about the experiment's blast radius.

- **Namespace-isolated?** The component lives in its own namespace and does not need cluster-wide RBAC beyond standard chart install. Green if yes.
- **Tier-0 non-interference?** The component does not modify Cilium, cert-manager, ESO, envoy-gateway, external-dns, or cloudflared. Green if yes. (A learning experiment that replaces the CNI is not a learning experiment, it's a cluster rebuild — handle via the `add-or-replace-node` / rebuild path instead.)
- **Resource ceiling set?** The chart's `resources.limits` are set to sane values (not `{}`, not 8Gi). You can tolerate the experiment using up to those limits on each node; if it hits the ceiling it OOMs and you notice. Green if limits are explicitly set.
- **Stateful data throwaway?** If the component holds data, the user has explicitly acknowledged the data is throwaway OR has a one-line manual-backup plan (not a full tested restore runbook — this is a learning experiment, not production). Green if acknowledged.

Any red here → Defer until the user addresses it. Do not escalate to reject — these are fixable.

### What learning intake does NOT require

Explicitly called out so the gate does not overreach:

- **No weighted soft score.** Project stars, release cadence, community depth, observability hooks — none of these gate learning intake. A three-star project by one maintainer is fine if the user wants to learn it.
- **No do-nothing tiebreaker.** Learning has value do-nothing doesn't. The user touching the thing *is* the win.
- **No tested restore runbook** for stateful data (gate 6). The throwaway acknowledgement replaces it.
- **No concrete present-day problem** (gate 7). The learning intent replaces it.
- **No sustainability signal check.** Abandoned, pre-1.0, hobby projects are all fair game for learning intake if the user goes in knowing that.

### What learning intake still requires

Gates 1–5 (license, blast radius, reversibility, integration fit, secrets model). These protect the rest of the cluster. A learning experiment that forks the secrets story or takes out DNS is still a reject — the user can learn it, just not at the cost of the things that already work.

### The decision

- **Add (learning)** — gates 1–5 pass, all four declarations present, all four containment checks green. Record the timebox and exit plan in the ADR so the review date is visible.
- **Defer** — a containment check is red or a declaration is missing. List what's missing.
- **Reject** — a gate 1–5 failure. Learning intent doesn't soften containment.

### Review trigger

When the timebox expires, the user should re-run intake with a new question: *"is this still a learning experiment, or has it become something else?"* Three possible outcomes:

1. **Learning done, remove it** — the user learned what they wanted; remove per the recorded exit plan. This is intake working as intended. Most of anton's database-operator removals were this pattern.
2. **Learning done, now it's concrete need** — the user found a real use. Re-run intake under concrete-need intent against the full production rubric. If it fails, remove anyway and revisit when the gap closes.
3. **Extend the timebox** — okay once, with a stated reason. "Extend the timebox" is a yellow flag if it happens more than once — that's how learning experiments quietly become permanent.

## Soft scoring

Runs only after all seven hard gates pass. Score each attribute `2` (green) / `1` (yellow) / `0` (red). Multiply by weight. Reject if weighted total < **22 / 34**.

| Attribute | Weight | Green (2) | Yellow (1) | Red (0) |
|---|---|---|---|---|
| Project liveness | ×3 | commits in last 30d, release in last 6mo, >1 active maintainer | sporadic commits, single maintainer, or last release 6–12mo | no commits in 90d OR no release in 12mo |
| Maintenance burden | ×3 | clear semver, no breaking change in last 3 minors, CHANGELOG readable | occasional breaking changes with migration notes | frequent breaking changes, CRD schema churn, or undocumented majors |
| Resource footprint | ×2 | <200Mi RAM and <100m CPU steady-state per replica, single replica is fine | 200–500Mi or multi-replica by default | >500Mi per replica, requires HA (3 replicas), or has OOM-related open issues |
| Docs quality | ×2 | official install works copy-paste on Talos+Flux, has upgrade guide and troubleshooting | docs exist but gaps in upgrade path | docs missing, wiki-only, or contradict chart behavior |
| Storage requirements | ×2 | stateless OR single small PVC (<5Gi) on existing CSI | single larger PVC or multiple small PVCs | HA storage, RWX, or demands a specific storage class anton doesn't have |
| Community depth | ×1 | >500 stars OR active Discord/Slack OR present in home-operations / cluster-template ecosystem | 100–500 stars, quiet community, or niche audience | <100 stars, no community channel, no ecosystem presence |
| Observability hooks | ×1 | ships `/metrics` + `ServiceMonitor` chart option, structured JSON logs | `/metrics` only, no ServiceMonitor option | no metrics endpoint, unstructured logs, or requires agent sidecar to observe |

**Weighted total**: sum of (score × weight) across 7 rows, max **34**.

**Reject threshold**: < 22 / 34.

### Matrix template to copy

```
Candidate: <name>
Project URL: <url>

Hard gates (pass/fail):
  [ ] License & exit cost
  [ ] Blast radius
  [ ] Reversibility
  [ ] Integration fit
  [ ] Secrets model
  [ ] Tested restore runbook  (N/A if stateless)
  [ ] No speculative scaling

Soft score (2/1/0):
  Project liveness       × 3 = __
  Maintenance burden     × 3 = __
  Resource footprint     × 2 = __
  Docs quality           × 2 = __
  Storage requirements   × 2 = __
  Community depth        × 1 = __
  Observability hooks    × 1 = __
  ─────────────────────────────
  Total                       = __ / 34

Do-nothing delta: __  (reject if <4)

Known-bad pattern match: <none | which one>

Verdict: ADD | DEFER | REJECT
Reason: <one sentence>
```

## Do-nothing tiebreaker

Score "do nothing" — i.e., the status quo without this component — on the same matrix. Do-nothing's scores are often genuinely high because the status quo is stable, zero-maintenance, and zero-resource.

**Rule**: if `candidate_total - do_nothing_total < 4`, reject. The intake tax (upgrade toil, secret lifecycle, release-note reading, Renovate PR triage, one more line in `flux get hr -A`) is empirically worth about 4 points. If the candidate isn't decisively better than doing nothing, doing nothing wins by default.

## Notes on measurement speed

- Budget: 15 minutes for the whole rubric, end-to-end. If it's taking longer, the answer is almost always defer or reject.
- Never gold-plate scoring. `2/1/0` captures enough signal; finer granularity is false precision.
- If two reasonable observers would score the same attribute differently, score the lower value. Be pessimistic — this is the gate that catches the mistakes you keep making.
