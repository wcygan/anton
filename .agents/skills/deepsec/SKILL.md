---
name: deepsec
description: Run and interpret Anton's committed DeepSec project. Use when Codex is asked to run or scan Anton with DeepSec, process or revalidate findings, inspect or export DeepSec reports, configure DeepSec project context, or add or review custom matchers.
---

# DeepSec for Anton

Goal: Run the requested DeepSec stage against Anton's repository source without exposing operator secrets or changing the live cluster.

Success means:
- Commands run from `/Users/wcygan/Development/anton/.deepsec` with project id `anton`.
- AI-backed work starts with an explicit small budget.
- Reported findings are checked against the cited source and given an evidence-based disposition.
- Generated state remains ignored, and only hand-maintained DeepSec files are eligible to commit.
- No Kubernetes, Flux, Talos, deployment, or other live-cluster mutation occurs.

Stop when: the requested scan, report, export, processing pass, revalidation, context update, or matcher review is complete. Do not automatically fix findings. Do not commit, push, or modify Kubernetes or Talos source unless the user separately requests it.

## Project boundary

- The committed project lives at `/Users/wcygan/Development/anton/.deepsec`; run local regex scans and inspection commands there. AI-backed stages use the isolated exception below.
- The configured project id is `anton`; pass `--project-id anton` explicitly.
- The target repository is the parent directory, `..`, as declared in `deepsec.config.ts`.
- Read `.deepsec/README.md`, `.deepsec/AGENTS.md`, and the relevant installed doc before running or changing DeepSec. Treat `.deepsec/node_modules/deepsec/dist/docs/` as the CLI source of truth because flags and defaults can change.

Before `scan`, confirm `.deepsec/data/anton/config.json` exists and keeps Anton's ignored credential and runtime paths in `ignorePaths`. DeepSec's scanner does not automatically inherit `.gitignore`; without this config it can read ignored files that match a matcher glob. Stop instead of scanning if the guard is missing or excludes less than the current operator-secret surface.

DeepSec reviews repository source and committed GitOps intent. It does not prove that the live Kubernetes cluster matches Git or has a secure runtime posture. Do not run `kubectl apply`, `flux reconcile`, Talos mutations, deploys, or any other cluster change as part of this workflow. Anton's separate `scripts/security-audit.sh` Trivy/Kubescape path covers live posture; do not invoke it merely because a DeepSec task fired.

## Safe ad hoc workflow

Run only the stages the user requested. Local regex scans and inspection commands use the committed workspace:

```sh
cd /Users/wcygan/Development/anton/.deepsec
pnpm install --frozen-lockfile
pnpm deepsec scan --project-id anton
pnpm deepsec report --project-id anton
pnpm deepsec export --project-id anton --format md-dir --out ./findings
```

`scan` is local and regex-only; it makes no model calls. `process` and `revalidate` are AI-backed and consume model or subscription quota. Run those AI stages only from `.deepsec` inside a disposable environment containing the public tracked Anton checkout, only required model authentication, and no Anton operator credentials:

```sh
pnpm install --frozen-lockfile
pnpm deepsec scan --project-id anton
pnpm deepsec process --project-id anton --agent codex --model gpt-5.5 --concurrency 1 --limit 10
pnpm deepsec revalidate --project-id anton --agent codex --min-severity MEDIUM --concurrency 1 --limit 10
pnpm deepsec report --project-id anton
pnpm deepsec export --project-id anton --format md-dir --out ./findings
```

Start with the 10-file commands above, or use `--limit 20` as the first ceiling, then inspect the results before increasing the budget. Run the unbounded `pnpm deepsec process --project-id anton --agent codex --model gpt-5.5` only after the sample is reviewed and the user wants the full pass.

Use `--concurrency 1` for a first revalidation pass too. If the finding set is already known to be small, the requested revalidation command may omit the limit but retains the concurrency guard: `pnpm deepsec revalidate --project-id anton --agent codex --min-severity MEDIUM --concurrency 1`. Interrupted `process` and `revalidate` runs are resumable; do not delete run state as recovery.

`--limit` applies to each invocation, not to the lifetime total. If the first `--limit 10` pass completes and the intended cumulative ceiling is 20, run a second `--limit 10` pass; following it with `--limit 20` can process 30 files total.

Do not rely on DeepSec's read-only wording as a filesystem control. The installed local Codex backend has used a `workspace-write` sandbox with network disabled, so an AI stage can still read outside the target and write inside it; scanner `ignorePaths` do not confine that shell. Never run `process` or `revalidate` in the credential-bearing Anton checkout. Use the disposable public-only environment above, preserve the `anton` project id and parent-target relationship, and stop as blocked if that boundary is unavailable. Record `git status --short` before and after the AI stage and stop on any unexpected source edit. Never erase or revert pre-existing work.

## Codex authentication

Local, non-sandbox DeepSec runs may reuse the authenticated Codex CLI subscription. That is a local convenience, not a portable CI credential: never assume a GitHub Actions runner can reuse the local subscription. Local authentication does not mean local inference; relevant source excerpts are still sent to the selected model provider.

Never commit `.env.local`, any `.env*.local` file, provider keys, tokens, or other credentials. If authentication is unavailable, report the blocked AI-backed stage; do not search for or expose another credential source.

## File and secret safety

Commit only configuration and hand-maintained project context when the task calls for it, such as:

- `.deepsec/deepsec.config.ts`, package metadata, and lockfiles;
- `.deepsec/README.md` and `.deepsec/AGENTS.md`;
- `.deepsec/data/anton/INFO.md`, `SETUP.md`, and `config.json`; and
- confirmed custom matchers under `.deepsec/matchers/`.

Never commit:

- `.deepsec/node_modules/` or `.deepsec/.env*.local`;
- `.deepsec/data/*/files/`, `runs/`, or `reports/`;
- `.deepsec/data/*/project.json` or `tech.json`; or
- `.deepsec/findings/`.

Do not decrypt SOPS files. Do not read, copy, report, or expose kubeconfig, `age.key`, deploy keys, tunnel credentials, token files, or other operator secrets. Treat generated findings and exports as sensitive because they can contain source excerpts and repository paths.

## Interpret findings

Treat every DeepSec finding as a lead until it is revalidated. For each finding in scope:

1. Open the cited repository file and line and inspect the surrounding control flow or manifest directly.
2. Record a disposition: true positive, false positive, fixed, duplicate, or uncertain. Preserve uncertainty when the repository alone cannot prove runtime behavior.
3. Distinguish a repository security defect from an expected privileged infrastructure pattern. Talos, CNI, storage, logging, monitoring, and bootstrap components can legitimately use host access, elevated capabilities, or broad bootstrap privileges; verify that the scope is necessary rather than dismissing or accepting it automatically.
4. For container and action supply-chain findings, check the committed reference itself and record whether GitHub Actions use immutable commit SHAs and container images use immutable digests.

Revalidation improves confidence but does not replace direct inspection. Do not remediate, edit GitOps source, or open follow-up work unless the user separately asks.

## Context and custom matchers

Keep `.deepsec/data/anton/INFO.md` short, architecture-focused, and safe for a public repository. Do not put credentials, private endpoints, IP addresses, literal tailnet names, or operator-only access details in it. Preserve the distinction between committed intent and live state. Follow `.deepsec/data/anton/SETUP.md` and `.deepsec/node_modules/deepsec/dist/docs/configuration.md` when updating context.

Do not add a custom matcher speculatively. Add one only after a confirmed true positive demonstrates a reusable Anton-specific pattern that built-in matchers do not cover. Before authoring it:

1. Read `.deepsec/node_modules/deepsec/dist/docs/writing-matchers.md`, `.deepsec/node_modules/deepsec/dist/config.d.ts`, and the shipped sample matchers.
2. Confirm the built-in matcher set or `.deepsec/node_modules/deepsec/dist/docs/supported-tech.md` does not already cover the pattern.
3. Use tight file globs and the narrowest useful regex; avoid broad noisy sweeps.
4. Wire the matcher through `deepsec.config.ts`, run `pnpm deepsec scan --project-id anton --matchers <slug>`, and inspect representative candidates in the target source.

Commit only the matcher and hand-maintained configuration, never the generated candidate data.

## Validation and report

After changing this skill or the DeepSec project:

```sh
uv run --with pyyaml /Users/wcygan/Development/dotfiles/config/codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/deepsec

cd /Users/wcygan/Development/anton/.deepsec
pnpm deepsec status --project-id anton
```

From the repository root, confirm the worktree scope and ignore rules:

```sh
git status --short
git check-ignore -v \
  .deepsec/node_modules/ \
  .deepsec/.env.local \
  .deepsec/data/anton/files/example.json \
  .deepsec/data/anton/runs/example.json \
  .deepsec/data/anton/reports/example.md \
  .deepsec/data/anton/project.json \
  .deepsec/data/anton/tech.json \
  .deepsec/findings/example.md
```

Review the final diff to confirm the skill contains no secret values or machine-specific credentials. Report changed files, exact validation commands and results, unresolved findings, and explicitly state that no live-cluster mutation occurred.
