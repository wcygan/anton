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

1. Read `.codex-security/README.md`, its `AGENTS.md`, and `SECURITY.md`. Establish
   the requested stage, revision, scope, and budget before model-backed work.
2. Use the pinned workspace package and frozen lockfile. Use installed CLI help
   for commands and flags. `mise exec -- task security:source-check` is safe in
   the operator checkout: it performs only a dry run without credentials or
   model calls.
3. For scans or validation, establish the disposable public-only VM/container
   described in the README. It must contain only required model authentication,
   with no operator secrets, host mounts, SSH agent, or private cluster access.
   Scanner scope and ignore rules do not confine an agent's shell. If this
   boundary is unavailable, stop the AI-backed stage and report what is missing.

## Execute and assess

Use the README's standard scan first: `scripts/` and an estimated $5 ceiling per
attempt. Widen only to the requested scope; report partial coverage explicitly.
Model cost estimates are not hard spending caps. Keep output outside the Git
worktree in private storage and record Git status before and after the run.
Stop on unexpected edits and preserve them for inspection.

Inspect cited source before accepting a finding. Record confirmed, false
positive, duplicate, fixed, or inconclusive dispositions. Distinguish static
tracing from runtime reproduction. Treat intentional platform privileges as
exceptions to justify and narrow, not automatic vulnerabilities or exclusions.
Check actual action SHAs and image digests for supply-chain findings.

Keep SOPS encrypted. Never read or copy operator credentials or Secret values.
Treat generated findings as sensitive.

## Authority and completion

Run only the requested stage. Patching, PR creation, tracker publication,
Kubernetes/Talos/provider changes, force reconciliation, debug workloads, and
synthetic traffic require their own authorization under Anton's operational
contract. Source scans cannot prove runtime posture; `security:audit` and
`security:audit-images` remain separate workflows and are not scan follow-ups.

After workspace or skill changes, run the frozen install, source dry run,
`git diff --check`, and `mise exec -- task contracts:validate`. Confirm private
outputs remain ignored. Report changed files,
verification results, untested model/runtime behavior, and operator follow-up.
