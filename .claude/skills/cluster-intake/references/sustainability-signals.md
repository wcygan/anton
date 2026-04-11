# Sustainability signals for OSS projects

How to judge whether an OSS project is safe to adopt long-term. Used in Step 4 of the main workflow to inform (not gate) the soft score in Step 5. Budget: 5 minutes per candidate.

None of these are hard gates on their own — they feed `Project liveness` and `Maintenance burden` in the rubric. But red flags here multiply: a project with 3 red signals is almost always a future removal commit.

## Stronger than stars

Stars are a popularity signal, not a sustainability signal. A 20k-star project abandoned two years ago is still 20k stars. Prefer signals that require ongoing work.

### 1. Commit recency and cadence *consistency*

Not just "are there commits" but "are there commits on a predictable schedule." Steady monthly commits from multiple contributors beats a burst of 100 commits one week and silence for three months.

- **Green**: commits in the last 30 days, no 60-day gaps in the last 12 months.
- **Yellow**: sporadic bursts, multi-month quiet periods, or maintenance-only commits (bumps, no features or fixes).
- **Red**: no commits in 90 days, or only commits from dependency bots (Dependabot/Renovate).

Where to look: GitHub `Insights → Contributors`, `Insights → Commit activity`.

### 2. Release cadence

Stable releases are the contract with downstream (Renovate + Flux). Absence of releases means every upgrade is a gamble on `main`.

- **Green**: tagged release in the last 6 months, clear semver, CHANGELOG in repo.
- **Yellow**: releases exist but are infrequent, or tag-only with no release notes.
- **Red**: no tagged release in 12 months, or "use latest commit" as the documented install path.

Where to look: `/releases` tab on GitHub; look at spacing between tags on `/tags`.

### 3. Bus factor > 1

More than one active committer from more than one organization. Single-maintainer projects are not disqualified, but they carry explicit risk — burnout, job change, life events all terminate the project.

- **Green**: 3+ active committers, at least 2 from different orgs, or a foundation home (CNCF, Apache, Linux Foundation).
- **Yellow**: 1–2 committers, all from one company or one individual.
- **Red**: single individual with no succession plan, no `MAINTAINERS` file, no `ADOPTERS` file.

Where to look: `Insights → Contributors` for the last year, `CODEOWNERS`, `MAINTAINERS.md`, `GOVERNANCE.md`.

### 4. Median time-to-first-response on issues

How long does it take for a new issue to get a human response? This is a better signal than star count because it requires ongoing attention.

- **Green**: <48 hours median, maintainer comments visible on most recent 10 issues.
- **Yellow**: 3–14 days, or responses only on issues from big-name contributors.
- **Red**: most recent issues have no response, or only bot responses.

Where to look: scan the last 10–20 issues on the repo's issue tracker.

### 5. Breaking change discipline

Does the project manage breaking changes responsibly, or does every minor break something?

- **Green**: documented deprecation policy, breaking changes gated to major versions only, migration guides in release notes.
- **Yellow**: occasional breaking changes in minors but documented clearly.
- **Red**: breaking changes hidden in minors, no migration guides, "just read the release notes" is the entire upgrade strategy.

Where to look: skim the last 5 release notes for `BREAKING`, `MIGRATION`, `⚠️`.

## Deployment-surface signals

### 6. Official Helm chart in-repo vs. community chart

The chart *is* the deploy contract. Who owns it matters.

- **Green**: helm chart in the upstream repo, maintained by the project team, OCI or in-repo chart source published on every release.
- **Yellow**: chart in a well-maintained third-party repo (Bitnami, official org repo). Note: Bitnami's helm chart licensing and hosting shifted recently — double-check the current state.
- **Red**: chart only in `k8s-at-home/charts` (deprecated), in a long-dead community repo, or no chart at all (raw manifests / Kustomize only).

The **k8s-at-home/charts** deprecation is the cautionary tale. When a community chart repo dies, every user has to either switch to an official chart (usually incomplete) or vendor the last working version themselves. Treat community-only as yellow at best.

### 7. Values schema stability

Renovate + Flux only work cleanly if `values.yaml` doesn't churn. Every schema change is a silent upgrade break.

- **Green**: values schema stable across the last 3 minors; deprecated keys warned for one release before removal.
- **Yellow**: occasional renames with backward compat.
- **Red**: values shape rewritten without notice between minors.

Where to look: diff `values.yaml` between the last 3 releases.

### 8. Does it ship observability hooks?

A project that ships `/metrics` and a `ServiceMonitor` chart option has thought about being operated. A project that doesn't hasn't.

- **Green**: `/metrics` in Prometheus format, `ServiceMonitor` chart option, structured JSON logs.
- **Yellow**: `/metrics` only, no chart option for ServiceMonitor.
- **Red**: no metrics endpoint, unstructured log output, expects you to write your own exporter.

## Ecosystem and governance signals

### 9. CNCF project maturity ladder

CNCF status is a prior, not a gate. It signals that the project has passed external review on governance and sustainability.

- **CNCF Graduated**: highest confidence — requires committers from multiple orgs, documented governance, security audit. Treat as green absent contradicting evidence.
- **CNCF Incubating**: stable enough for production per CNCF's criteria, but expect some API churn. Yellow-to-green.
- **CNCF Sandbox**: innovator's bet. Adoption is plausible but sustainability is not yet proven.
- **Not in CNCF**: not a red flag on its own — many great projects aren't in CNCF, and many CNCF sandbox projects get abandoned. Use other signals.

### 10. Funding and commercial backing

Pure hobby projects aren't disqualified but carry explicit bus-factor risk. Funded projects have skin in the game.

- **Green**: foundation-hosted OR company-backed with open governance OR GitHub Sponsors with real monthly numbers.
- **Yellow**: single-company project with an open-source edition and a commercial edition — fine, but track whether critical features migrate behind the paywall.
- **Red**: "side project" status, maintainer publicly burned out, no funding in place.

## Quick reference: 5-minute walk

1. Open the GitHub repo.
2. `Insights → Contributors` — check last 12 months. (Bus factor.)
3. `/releases` — last release date, tag cadence. (Release consistency.)
4. Last release notes — skim for BREAKING. (Breaking-change discipline.)
5. Last 10 issues — scan for maintainer responses. (Issue responsiveness.)
6. Find the helm chart — is it in the upstream repo? (Deploy contract ownership.)
7. `values.yaml` — does it have sane defaults, `resources:`, `serviceMonitor:`? (Observability and footprint.)

If any two of these come back red, don't bother with the full rubric. Default to defer.

## What to ignore

- **Star count** — popularity ≠ sustainability
- **Downloads per month** — same problem
- **"Production-ready" claims in the README** — every project claims this
- **Benchmark numbers** — almost always ideal-case, almost never homelab-applicable
- **Hacker News sentiment** — selection bias toward novelty
