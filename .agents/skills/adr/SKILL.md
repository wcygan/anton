---
name: adr
description: Anton ADR lifecycle — author new architectural decision records, list existing ones by status or affects-category, and mark old decisions superseded. Use when capturing a decision (especially after `cluster-intake-gatekeeper` returns an ADD/DEFER/REJECT verdict), when reviewing prior decisions before changing direction, when checking if a candidate component has been removed before, or when promoting a decision out of memory into a durable record. ADRs live in `context/adrs/` and are immutable — supersession is the only way to change a decision. The ADR index is built by scanning ADR files directly and injected into every Codex session by `.Codex/hooks/inject_adr_index.py`. Keywords — ADR, architecture decision record, decision log, supersede, decision history, why did we, prior decision, recorded decision, MADR, immutable, intake handoff, cluster-intake-gatekeeper handoff, removal graveyard, reverted decision.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# ADR

Anton-local skill for the architectural decision record lifecycle. Owns three workflows: **new**, **list**, **supersede**. ADRs live at `context/adrs/NNNN-kebab-slug.md` and are immutable — once accepted, the body never changes. Supersession is the only way to revise a decision.

## Why this skill exists

Anton needs **one durable home** for architectural decisions so that:
- `cluster-intake-gatekeeper` has somewhere to hand off its ADD/DEFER/REJECT verdicts (instead of stopping at "ADR-ready").
- Future Codex sessions can discover prior decisions automatically via the SessionStart hook (`.Codex/hooks/inject_adr_index.py`) without the operator typing them in.
- `cluster-intake` Step 2 can query past `Reverted` decisions by category instead of grepping a single shared file.
- The operator (and future-Will) can recover *why* the cluster looks the way it does without mining `git log`.

The skill is anton-local and has **no runtime dependency** on `~/.Codex/skills/context-repo-adr` — the format is intentionally compatible with the global context-repo conventions, but invoking this skill never delegates to that one.

## Hard rules

- **ADRs are immutable.** Once an ADR's `status:` is `Accepted` (or `Reverted` / `Rejected` / `Deferred`), the body never changes. The *only* edit allowed on an existing ADR is flipping the `status:` line to `Superseded-by NNNN`. Any other change must go through `supersede`.
- **Numbers are never reused.** The next number is always `max(existing) + 1`, zero-padded to four digits, regardless of whether earlier numbers were superseded.
- **`Status: Reverted`** is anton-specific. Use it for any decision that was once live and is now removed. Standard MADR has no equivalent.

References:
- Field reference and immutability rule → [conventions](references/conventions.md)
- Canonical template for new ADRs → [template](references/template.md)

## Workflow — `new`

Triggered by:
- The user says "create an ADR" / "record this decision" / `/adr new "<title>"`
- `cluster-intake-gatekeeper` hands off an ADD / DEFER / REJECT verdict (the verdict object substitutes for the interactive interview — see "Handoff from intake" below)

### Steps

1. **Allocate the next number.** `Glob('context/adrs/0[0-9][0-9][0-9]-*.md')`. Sort. The next number is `max + 1`, zero-padded to 4 digits. Never reuse a number.

2. **Generate the slug.** Lowercase the title, kebab-case it, drop articles and prepositions, take the first 4–6 meaningful words. Example: "Adopt Cilium over Calico for CNI" → `adopt-cilium-over-calico-for-cni` → file `0018-adopt-cilium-over-calico-for-cni.md`.

3. **Interview the user** (skip this when invoked from intake — see Handoff from intake). Ask only the questions whose answers aren't already known:
   - Title (one short sentence)
   - One-sentence summary (the blockquote after the H1)
   - `status` — usually `Accepted` for forward-looking decisions; `Deferred` / `Rejected` / `Reverted` if known
   - `affects` — pick the broadest applicable category from: `storage`, `observability`, `databases`, `registries`, `demos`, `networking`, `security`, `compute`, `all`, or a new category if none fit
   - `intent` — `concrete-need` / `learning` / `unknown`
   - `supersedes` — list of NNNNs being superseded by this one (usually empty)
   - **Context** (1–3 paragraphs — what situation prompts this decision, what forces are in play)
   - **Decision** (active voice, one or two sentences — "We will adopt X" / "We will not")
   - **Alternatives considered** (do-nothing + 1–2 alternatives, with a one-line "why rejected" each)
   - **Consequences** — accepted costs, lessons (if `Reverted`), follow-ups

4. **Write the ADR file** at `context/adrs/NNNN-slug.md` using the shape from [template](references/template.md). Frontmatter is mandatory; missing frontmatter fields default to the template's defaults.

5. **If `supersedes:` is non-empty**, also flip the `status:` line of each superseded ADR to `Superseded-by NNNN`. This is the *only* allowed in-place edit on an existing ADR. Use `Edit` with a precise old/new string for the status line only — never touch the body.

6. **Confirm to the user** with the file path and the new ADR number.

### Handoff from intake

When `cluster-intake-gatekeeper` invokes this skill at the end of its evaluation, it passes the verdict object directly. Map the verdict to ADR fields without re-interviewing:

| Gatekeeper verdict | ADR `status:` | Notes |
|---|---|---|
| Add (concrete need) | `Accepted` | `intent: concrete-need`. Decision section names the hand-off skill (`add-flux-app` / `flux-app-author`). Consequences section includes the Renovate-PR tax line. |
| Add (learning) | `Accepted` | `intent: learning`. Consequences section *must* include the timebox, exit plan, and review date — these are load-bearing under the contained-learning rubric. The frontmatter should add a `review-by:` field with the review date. |
| Defer | `Deferred` | Body holds the exact measurable unblock conditions (what would have to be true to convert to Accepted). |
| Reject | `Rejected` | Body holds the failed gate (1–7) or known-bad pattern, and — if appropriate — whether reframing as a learning intake would change the answer. |

After writing the ADR, return to the gatekeeper with the ADR number so it can include it in its memory append.

## Workflow — `list`

Triggered by:
- `/adr list` or `/adr list --status Reverted` or `/adr list --affects databases`
- `cluster-intake` Step 2 (the removal-detection lookup) — internally invokes this with `--status Reverted --affects <candidate-category>` to find prior reverts

### Steps

1. `Glob('context/adrs/0[0-9][0-9][0-9]-*.md')`.
2. For each file, read the frontmatter and extract `status`, `date`, `affects`, `intent`, and the H1 title.
3. Apply filters:
   - `--status <X>` → keep only ADRs whose `status:` matches `X` (case-insensitive)
   - `--affects <X>` → keep only ADRs whose `affects:` contains `X`
   - With no filter, return all
4. Format as a markdown table sorted by NNNN (columns: #, Title, Status, Date, Affects, Intent).
5. If used as the data source for `cluster-intake` Step 2: also read the matching ADRs' "Re-adoption guidance" section so the intake can surface the conditions under which a re-attempt would be valid.

## Workflow — `supersede`

Triggered by:
- `/adr supersede <NNNN> "<reason>"` — the user wants to revise an existing decision

### Steps

1. **Verify the target exists.** `Read` `context/adrs/NNNN-*.md`. If missing, abort with a clear error.
2. **Verify the target's current status.** If it is already `Superseded-by NNNN`, abort — supersession chains exist (NNNN can be superseded by MMMM which is superseded by PPPP), so the user must supersede the *latest* in the chain.
3. **Author the replacement** by invoking the `new` workflow with `supersedes: [<NNNN>]` pre-populated. Walk the interview as normal.
4. **Flip the old ADR's status line** — and *only* the status line — from `Accepted` (or whatever it was) to `Superseded-by <new NNNN>`. Use `Edit` with the precise old/new strings. Do not touch the body, the date, or any other field.
5. **Confirm to the user** with both ADR numbers (old → new) and the file paths.

## What this skill does NOT do

- Does not write Flux manifests — that is `add-flux-app`.
- Does not run cluster intake — that is `cluster-intake` (which hands off here).
- Does not edit ADR bodies after the fact. Ever. Use `supersede`.
- Does not auto-detect when a decision should be superseded. Manual via `/adr supersede`.
- Does not push, commit, or tag — the user owns git operations.
- Does not delete ADRs. ADRs are append-only forever, even superseded ones.

## Related skills and agents

- `cluster-intake` / `cluster-intake-gatekeeper` — the dominant authoring path. Hand off here on every verdict.
- `add-flux-app` / `flux-app-author` — invoked *after* an `Accepted` ADR that involves new manifests.
- `~/.Codex/skills/context-repo-adr` (user-level) — format-compatible but not invoked at runtime. If the user adopts the full context-repo convention later, the existing ADRs will Just Work.

## Anti-patterns

- **Editing an ADR body to reflect a changed decision.** That's what `supersede` is for. Editing in place destroys the historical record.
- **Re-using a number after a delete.** ADRs are never deleted, so this shouldn't come up — but if it does, allocate the next number, never the gap.
- **Authoring an ADR before the decision is actually made.** ADRs document decisions that happened, not aspirations. If the user is still considering, they're not ready for an ADR.
- **Verbose ADRs.** One screen of body is the target. If the decision genuinely needs more context, link to a doc — don't inline it.
