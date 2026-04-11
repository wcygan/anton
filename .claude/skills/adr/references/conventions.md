# ADR conventions reference

Mechanical reference for the `adr` skill. This file is loaded on demand from `SKILL.md`; it's not part of the always-on context.

## File location

```
context/adrs/
├── INDEX.md                  # generated table; regenerated on every new/supersede
├── TEMPLATE.md               # canonical anton ADR template (also mirrored at .claude/skills/adr/references/template.md)
├── RE-ADOPTION-RUBRIC.md     # meta-policy preserved from anton-history.md (non-ADR)
└── NNNN-kebab-slug.md        # one ADR per file
```

## Naming convention

`NNNN-kebab-slug.md`

- `NNNN` — 4-digit zero-padded sequential number, allocated as `max(existing) + 1`. Never reuse, never renumber, never gap-fill.
- `kebab-slug` — lowercase, hyphenated. Take 4–6 meaningful words from the title. Drop articles, prepositions, adjectives that add no information.
  - "Adopt Cilium over Calico for the CNI layer" → `adopt-cilium-over-calico-for-cni`
  - "Remove the LGTM observability stack" → `lgtm-observability-stack-removed`
  - "Defer Loki adoption pending consumers" → `defer-loki-pending-consumers`

The slug is human-readable shorthand only; the NNNN is the canonical identifier.

## Frontmatter (mandatory)

```yaml
---
status: <Proposed|Accepted|Deferred|Rejected|Reverted|Superseded-by NNNN>
date: YYYY-MM-DD
deciders: ['@wcygan']
affects: <category>
intent: <concrete-need|learning|unknown>
supersedes: []
superseded-by: null
retrospective: false
---
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | enum | yes | See status enum below |
| `date` | YYYY-MM-DD | yes | When the decision was *made*, not when the ADR was written |
| `deciders` | list of `@handle` | yes | `['@wcygan']` for solo decisions |
| `affects` | string (category) | yes | Pick from the canonical list below or invent a new one if needed |
| `intent` | enum | yes | `concrete-need` / `learning` / `unknown` |
| `supersedes` | list of NNNNs | yes (may be `[]`) | NNNNs of ADRs this one replaces. Each one's status flips to `Superseded-by <this-NNNN>` |
| `superseded-by` | NNNN or `null` | yes | Set automatically when a later ADR supersedes this one |
| `retrospective` | bool | yes | `true` if the ADR was written after the decision was already in effect (e.g., the migrated 0001–0017). `false` for decisions captured at the time |
| `removal-commits` | list of SHAs | optional | For `Reverted` ADRs, the commit(s) that removed the component |
| `review-by` | YYYY-MM-DD | optional | For `Accepted` ADRs with `intent: learning`, the date the experiment is reviewed |

### Status enum

Standard MADR statuses plus anton extensions:

- **`Proposed`** — under discussion; not yet committed to. Rare on anton; usually `Accepted` is the first status.
- **`Accepted`** — the decision is in effect.
- **`Deferred`** — a decision was attempted but cannot be made until specific unblock conditions are met. Body holds the unblock conditions.
- **`Rejected`** — the decision was considered and explicitly declined. Body holds the reason.
- **`Reverted`** — *anton extension*. The decision was originally `Accepted`, the component or pattern was in the cluster for some period, and was then removed. Standard MADR has no status for this. The migrated graveyard ADRs (0001–0017) all use it.
- **`Superseded-by NNNN`** — the decision has been replaced by ADR NNNN. The body never changes; only this status line is updated when supersession happens.

### `affects` category list

The canonical categories used by `cluster-intake` Step 2 for removal-detection lookup. Pick the broadest applicable. Add a new category only if none fit.

- `storage` — anything that holds persistent data on disk
- `observability` — metrics, logs, traces, dashboards, alerting
- `databases` — SQL / NoSQL / streaming / in-memory data services
- `registries` — container registries, image mirroring, signing
- `demos` — throwaway demo apps
- `networking` — CNI, Gateway API, service mesh, DNS, load balancing, tunnels
- `security` — auth, secrets, policy, admission controllers
- `compute` — kubelet, runtime, scheduler, autoscaling
- `all` — cluster-wide decisions that don't slot into one category (e.g., "we use Flux for GitOps")

## Body sections

The template enforces this section order. Do not add or remove sections.

1. **Blockquote summary** (`> ...`) — one sentence right after the H1. This is what appears in `INDEX.md`.
2. **Status** — restates the frontmatter status as a sentence.
3. **Context** — what is the situation that prompts this decision. 1–3 paragraphs. Mark "Context (retrospective)" if `retrospective: true`.
4. **Decision** — active voice. Usually 1–2 sentences.
5. **Alternatives considered** — do-nothing + 1–2 alternatives. One line each, "why rejected." For retrospective ADRs, this is usually `N/A — retrospective record`.
6. **Consequences** — accepted costs, lessons (for `Reverted`), follow-ups.
7. **Re-adoption guidance** — only for `Reverted` status. The conditions under which the decision could be revisited.
8. **Follow-ups** — checklist.

## Immutability rule

Once an ADR has any status other than `Proposed`, the body never changes. The *only* in-place edit allowed is flipping the `status:` line to `Superseded-by NNNN`. Any other revision must go through `supersede`, which writes a new ADR with `supersedes: [<old-NNNN>]`.

This rule is what makes ADRs trustworthy as a decision history — if bodies could change, future-Claude could not rely on the historical record.
