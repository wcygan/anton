# Dependency Dashboard (Renovate issue #10)

Renovate maintains a master issue in this repo listing every dependency it tracks, including ones it has **not** opened a PR for. This catches the gap between "what Renovate sees" and "what Renovate is willing to PR right now".

Invoked from Step 6 of the main workflow.

## Why it matters

`gh pr list --author app/renovate` shows only PRs that made it through Renovate's config rules. The dashboard exposes everything else:

- **Rate-limited** — Renovate's `prHourlyLimit` / `prConcurrentLimit` throttled itself
- **Scheduled** — a schedule branch blocks the PR until the schedule window opens
- **Group-delayed** — batched into a group that has not opened yet
- **Approval-gated** — `dependencyDashboardApproval: true` held it back pending user check
- **Detected but not eligible** — Renovate found it, but current config says "do not PR"
- **Errors** — Renovate hit a parser or lookup failure worth investigating

Any of these can be a real upgrade that the PR-list view misses entirely.

## Fetch

```sh
gh issue view 10
```

The issue is long. When reading, scan for these section headings (any subset may appear):

- `## Rate-Limited`
- `## Awaiting Schedule`
- `## Open` — already-open PRs (redundant with `gh pr list`, useful for cross-check)
- `## Detected dependencies` — full tracked set by package manager / datasource
- `## Errors` — parser / lookup failures; always investigate
- `## Pending Approval` — held by dashboard config

## What to fold into the report

1. **Rate-Limited and Awaiting Schedule** → note in the report as "coming soon from Renovate", no action needed.
2. **Errors** → report verbatim. These usually mean a `renovate.json` rule is broken or a datasource is unreachable; worth a follow-up config PR.
3. **Pending Approval** → these are intentional gates. Recommend the user decide whether to release the gate.
4. **Detected dependencies that are NOT in any other section** → compare against the nova output from Step 5. If nova flagged drift and Renovate has not even surfaced it, something in `renovate.json` is excluding it.

## Manual re-trigger

The dashboard includes a checkbox near the top: **"Check this box to trigger a request for Renovate to run again on this repository"**. Ticking it forces Renovate to re-scan and re-open PRs.

**Do not tick it from this skill** — that is a mutation. Recommend it in the report if a re-scan seems warranted (e.g., the user just fixed a `renovate.json` rule and wants it to take effect now).

## Re-opened superseded PRs

If a previous run of this skill recommended closing a superseded PR and Renovate later **re-opened it at a different version**, that usually means the newer PR landed and Renovate detected yet another available bump. Normal behavior — treat the re-opened PR as fresh in the next run, do not carry forward the old "superseded" flag.

## Sanity check against the PR list

The dashboard and `gh pr list --author app/renovate` should agree on what is currently open. If they diverge:

- PR open in `gh pr list` but missing from the dashboard → dashboard is stale, will update on next Renovate run
- Item in the dashboard "Open" section but missing from `gh pr list` → someone closed the PR manually; Renovate will re-open on next run unless explicitly ignored

Neither divergence is an emergency, but both are worth noting in the report.
