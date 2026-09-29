# Codex Security for Anton

This workspace pins the Codex Security CLI for repository source reviews
and supplies Anton's security context through `SECURITY.md`.
Trivy/Kubescape remain the separate cluster-posture and image-audit workflow.

## Install and check configuration

From the repository root:

```sh
mise exec -- pnpm --dir .codex-security install --frozen-lockfile --ignore-scripts
mise exec -- task security:source-check
```

The check runs `scan --dry-run`: it validates local configuration and paths,
without loading credentials, invoking a model, or accessing the cluster.
Node requirements and the exact CLI version are recorded in `package.json`.
Actual scans also require Python 3.10+ and an account with Codex Security access.

## Run a source review

Run AI-backed commands only inside a disposable VM/container containing a
public-only Anton checkout and the required model authentication. Clone the
public repository at the exact revision being reviewed; do not bind-mount this
operator checkout, the host home directory, a container-engine socket, or
operator credential directories. The environment must have no route to Anton's
private control plane and no kubeconfig, talosconfig, SOPS key, provider tokens,
or SSH agent. A fresh directory on the operator host is not sufficient isolation.
Keep provider access limited to what the selected scanner requires.

Inside that environment, install with the frozen lockfile, then:

```sh
cd .codex-security
pnpm exec codex-security login
pnpm check
git status --short
pnpm exec codex-security scan .. --config codex-security.yaml --auth chatgpt
git status --short
```

For CI, provision `OPENAI_API_KEY` through the runner's secret store and use
`--auth api-key`; do not copy local authentication into CI. No CI scan is enabled
by this migration. Source excerpts are sent to the selected model provider.

The initial scan covers `scripts/` in standard mode using `gpt-6-luna`.
This is partial repository coverage, not a whole-repository security assessment.
There is no scanner cost limit: CLI 0.1.31 cannot estimate GPT-6 Luna costs.
Confirm the intended run scope before scanning and review the first results
before widening scope or repeating scans. To select a different
bounded scope, add `--path kubernetes/apps/<namespace>/<app>` to the scan command;
CLI scope selection replaces the configured scope. Keep configuration from a
trusted revision outside the assessed checkout when reviewing untrusted PRs.

Scanning is report-only; omit patching, PR creation, publishing, and post-scan
automation. Stop on unexpected source changes and retain the diff for review.

## Public exposure review

Use the saved `public-exposure-review.md` prompt to trace unauthenticated
Internet access through Cloudflare, Envoy, routes, and public workloads, then
assess possible access to private resources after a workload compromise.
This replaces the initial scripts scope with `kubernetes/apps`; application
source in other repositories and live Cloudflare settings remain separate
review work. It uses the configured `gpt-6-luna` in standard mode with no cost
cap. It runs one scan to completion, not an indefinite scan or repair loop.

From `.codex-security` in the isolated environment described above:

```sh
pnpm exec codex-security scan .. \
  --config codex-security.yaml \
  --auth chatgpt \
  --path kubernetes/apps \
  --scan-prompt-file public-exposure-review.md
```

Append `--dry-run` to validate these inputs without starting model work.
Results remain in the scanner's private state directory outside the checkout.

## Review and retain evidence

Use the installed CLI to discover saved-result commands:

```sh
pnpm exec codex-security scans --help
pnpm exec codex-security findings --help
pnpm exec codex-security validate --help
pnpm exec codex-security export --help
```

Validation is AI-backed and uses the same isolation boundary. Classify each
finding as confirmed, false positive, duplicate, fixed, or inconclusive after
inspecting the cited source. Separate static evidence from runtime reproduction;
a failed environment setup is inconclusive, not a disproven vulnerability.

Record the revision, CLI/plugin versions, scope, coverage gaps, cost, and finding
dispositions. Keep results private outside the entire Git worktree. The CLI
defaults to its private persistent state; `CODEX_SECURITY_STATE_DIR` can select
a private persistent directory in the isolated environment. Retain needed
artifacts securely before disposing of the environment. Never publish raw
reports or credentials. Exit 2 indicates an error or incomplete coverage, not a
clean scan; inspect coverage even on successful completion.

Fixes require a separately requested remediation task. A source fix does not
prove deployment: follow Anton's GitOps verification contract to close a live
finding. See the repository skill for operational boundaries.

References: [CLI documentation](https://learn.chatgpt.com/docs/security/cli/reference),
[project configuration](https://github.com/openai/codex-security/blob/main/docs/project-configuration.md).
