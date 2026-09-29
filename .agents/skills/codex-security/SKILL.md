---
name: codex-security
description: Scan Anton repository source with Codex Security, validate or inspect findings, and maintain its pinned scanner configuration.
---

# Codex Security for Anton

Goal: Review Anton's committed source with reproducible scope and evidence,
without exposing operator credentials or changing the live cluster.

Success means the requested stage finishes with revision, tool versions,
coverage, findings, and unresolved limitations recorded. Stop after that stage;
scanning does not authorize remediation, publication, or deployment.

## Prepare

1. Read the [workspace guide](../../../.codex-security/README.md), its
   `AGENTS.md`, and `SECURITY.md`. Establish the requested stage, branch,
   revision, dirty state, scope, and budget before model-backed work.
2. Use the pinned workspace package and frozen lockfile. Use installed CLI help
   for commands and flags. `mise exec -- task security:source-check` is safe in
   the operator checkout: it performs only a dry run without credentials or
   model calls, checking the scripts, exposure, and application profiles.
   For application source snapshots, use `security:source-export` with explicit
   `REPOSITORY` and `REVISION`; review its allowlisted file manifest before
   transfer. Include `REVIEW_SOURCE.json` in a fresh extraction directory.
   Exported snapshots exclude local edits and Git history; an allowlist does
   not detect credentials embedded in ordinary code.
3. For scans or validation, establish the disposable public-only VM/container
   described in the README. It must contain only required model authentication,
   with no operator secrets, host mounts, SSH agent, or private cluster access.
   Scanner scope and ignore rules do not confine an agent's shell. If this
   boundary is unavailable, stop the AI-backed stage and report what is missing.

## Execute and assess

Choose the saved profile matching the question:

| Question | Inputs in `.codex-security/` |
| --- | --- |
| Operator scripts and repository helpers | Default `codex-security.yaml` scope |
| Internet entry points and lateral movement through Kubernetes | `public-exposure-review.md` with the README's exposure command |
| Website visitor input, serving code, container/build boundary | `public-app-review.yaml` and `public-app-review.md`, targeting one application input |

Read the pinned package, configuration, and installed CLI help for current
versions, model, scope, and supported flags. Pass the trusted config explicitly;
the CLI's default model may differ. CLI `--path` replaces configured scope.
Run an exact-input dry run before model work; the application-profile preflight
uses a placeholder and does not validate a particular application archive.
If pricing estimation is unsupported, report the lack of an enforced cost cap
and establish scope before running; changing models merely to make estimates
work changes the assessment. Widen scope only as requested.

Keep raw scan output outside the entire Git worktree in private storage. Record
source state before and after each run; for exported inputs, compare their
files because Git metadata is absent. Stop on unexpected edits and retain the
diff. A stopped or budget-exceeded run is partial evidence, not a clean review.

Before interpreting saved results or reviewing public exposure/application
findings, read [scan review lessons](references/scan-review-lessons.md). Finish
triage with current-run findings, historical repeats, coverage, attacker
prerequisites, and evidence strength accounted for separately.

Inspect cited source before accepting a finding. Record confirmed, false
positive, duplicate, fixed, or inconclusive dispositions. Distinguish static
tracing from runtime reproduction. Treat intentional platform privileges as
exceptions to justify and narrow, not automatic vulnerabilities or exclusions.
Check actual action SHAs and image digests for supply-chain findings.

Keep SOPS encrypted. Never read or copy operator credentials or Secret values.
Treat generated findings as sensitive.

For prior finding dispositions and open follow-ups, use QMD's `anton-context`
collection and retrieve the source record. Start with the
[September remediation record](../../../context/notes/2026-09-29-codex-security-remediation.md).
Historical records are leads; recheck current source and applied state before
claiming a previously fixed finding has returned or a follow-up is complete.

## Authority and completion

Run only the requested stage. Patching, PR creation, tracker publication,
Kubernetes/Talos/provider changes, force reconciliation, debug workloads, and
synthetic traffic require their own authorization under Anton's operational
contract. Source scans cannot prove runtime posture; `security:audit` and
`security:audit-images` remain separate workflows and are not scan follow-ups.

When remediation is authorized, repair the smallest authoritative owner and
validate that change. Record source remediation, applied configuration, and
runtime acceptance separately. Draft policies in `.codex-security/proposals/`
have no deployment effect until wired into Flux. Let normal reconciliation
proceed; obtain exact operator approval for live mutations or traffic tests.
Retain existing authorization for repository work and avoid asking for it again.

After workspace or skill changes, run the frozen install, source dry run,
`git diff --check`, and `mise exec -- task contracts:validate`. Confirm private
outputs remain ignored. Report changed files,
verification results, untested model/runtime behavior, and operator follow-up.
Distinguish reusable scanner setup completion from closure of a particular
security review; passing preflights does not resolve outstanding findings.
