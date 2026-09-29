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

The check runs three `scan --dry-run` commands: scripts, public exposure, and
the application configuration/prompt. The application configuration check uses
this tooling directory as a harmless placeholder target; check the actual
application input separately before its scan. These checks do not load
credentials, invoke a model, or access the cluster.
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

## Review public application source

`public-app-review.yaml` and `public-app-review.md` review one whole website
repository, including its container and build boundary. Run each application
separately; this is not another scan of Anton's manifests. Prepare source-only
inputs in the isolated environment above. Do not mount local application
checkouts or copy their ignored files or authentication.

From that environment's Anton checkout, select one exact deployed source
revision (these identifiers were observed on 2026-09-29):

| Application | Source repository | Source identifier in deployed image |
| --- | --- | --- |
| Bakery | `wcygan/kneadybynaturebakery` | `cc273ca` |
| Food site | `wcygan/food-site` | `65d6411` |
| Homepage | `nu-sync/homepage` | `9d7a0a2` |

These repository identifiers returned 404 to anonymous requests at review time;
do not assume they can be cloned without authentication. To prepare a new
snapshot from an existing local application checkout, run from the operator's
Anton checkout (this exports source only, with no model calls):

```sh
mise exec -- task security:source-export \
  REPOSITORY=/Users/wcygan/Development/food-site \
  REVISION=65d6411
```

Select the revision you want to assess; use a freshly verified deployed source
identifier for a deployment review, or `REVISION=HEAD` to review latest committed
source. Local edits are always excluded. The dated identifiers above are examples,
not a command to keep scanning an old deployment forever.

The command prints paths to a revision-named archive and JSON manifest under
ignored `.private/security-review/source-bundles/`, with owner-only file
permissions. It includes only committed `src/`, `public/`, container/workflow
files, package/lock files, and serving/build configuration. It excludes local
edits, `.git`, dependencies, operator manifests, docs, and ignored files. It
rejects links, submodules, and recognized credential-like filenames before
reading their payloads. The manifest records the full original source revision,
actual file list, and archive digest. Review these before transfer: an allowlist
does not detect secrets embedded in ordinary source files. No source is published.

Transfer only the reviewed source archives into the disposable environment
without host mounts or GitHub credentials. For example, transfer both printed
files to `/review-inputs/` inside that environment. From its Anton checkout:

```sh
mkdir ../food-site-source-65d6411ce999
tar -xzf /review-inputs/food-site-65d6411ce999.tar.gz -C ../food-site-source-65d6411ce999
cp /review-inputs/food-site-65d6411ce999.json ../food-site-source-65d6411ce999/REVIEW_SOURCE.json
pnpm --dir .codex-security exec codex-security scan "$(pwd)/../food-site-source-65d6411ce999" \
  --config "$(pwd)/.codex-security/public-app-review.yaml" \
  --auth chatgpt \
  --scan-prompt-file "$(pwd)/.codex-security/public-app-review.md"
```

Append `--dry-run` to check scope and configuration without model work. Use a
fresh extraction directory for each snapshot; do not overlay older contents.
Replace the archive/manifest names and revision for the other applications.
Inspect each report
before starting the next. Bundle scans do not include Git history or excluded
operator manifests; compare the files before and after scanning and stop on
unexpected changes. These use the configured model without a scanner
cost cap; they require model authentication inside the isolated environment.
Source identifiers in image tags are leads, not cryptographic build provenance.
Runtime image/package scanning and provider/router reviews remain separate.

The reusable setup is complete when the frozen install and all three profile
checks pass. A particular security review is complete only after its reports,
coverage gaps, remediation, and applicable runtime acceptance are assessed.
The inactive files in `proposals/` and outstanding runtime/provider/RBAC work
are separate from scanner setup; they do not prevent future source scans.

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
