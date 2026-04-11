---
name: anton-upgrade-audit
description: Upgrade triage for Anton — walks open Renovate PRs, flags supersessions, proposes a tiered merge order (patches → minors → CI majors → cluster majors), reads the Renovate Dependency Dashboard, and runs live-cluster deprecation audits with kubent/pluto/nova. Read-only. Use when asking "what can we upgrade", "check renovate PRs", "upgrade audit", "is anything outdated", "audit chart versions", "k8s deprecation scan", "what should we merge next", "are there superseded PRs". Hands Talos or Kubernetes version pin bumps off to upgrade-talos-or-k8s. Keywords — renovate, upgrade, audit, outdated, dependency dashboard, helm chart, kubent, pluto, nova, deprecation, chart drift, PR triage, merge order, supersede, bump, renovate bot
allowed-tools: Read, Bash
---

# Anton upgrade audit

Read-only triage for what can be upgraded in Anton — GitHub side (Renovate PRs + Dependency Dashboard) and cluster side (deprecated APIs, chart drift). Never mutates the repo or the cluster: no merges, no applies, no commits. Output is a prioritized, risk-tiered plan the user executes deliberately.

## Scope

| Concern | Owner | Output |
|---|---|---|
| Open Renovate PRs | **this skill** | Classification + tiered merge order |
| Renovate Dependency Dashboard (issue #10) | **this skill** | Items surfaced but not yet PR'd |
| Live-cluster deprecated APIs | **this skill** | `kubent` findings |
| Rendered-manifest deprecated APIs | **this skill** | `pluto` findings |
| Helm release drift vs. upstream | **this skill** | `nova` findings |
| Mise toolchain drift | **this skill** | `mise outdated` |
| Executing a Talos OS or Kubernetes version bump | **`upgrade-talos-or-k8s`** | Rolling upgrade workflow |
| Executing a chart / image bump | GitOps (merge → Flux reconcile) | out of scope |
| Cluster liveness after a merge lands | **`anton-cluster-health`** | out of scope |

## Hard rules

- **Never merge, close, or comment on a PR.** This skill recommends; the user acts.
- **Never run mutating commands** — no `kubectl apply`, `flux reconcile`, `talosctl apply`, `gh pr merge`, `gh pr close`, or `git push`. Read-only only.
- **Never bump `talosVersion` or `kubernetesVersion`** directly. Recommend the bump and hand off to `upgrade-talos-or-k8s` — that skill owns the rolling upgrade and the etcd-quorum health gates.
- **Never install audit tools** (kubent, pluto, nova, trivy). Report them missing and keep going.

## Green-path one-liner

If you have 30 seconds and want a single pulse on "is there anything to upgrade":

```sh
gh pr list --author app/renovate --limit 50 \
  --json number,title,labels \
  --jq '[.[] | {n: .number, t: .title, tier: ([.labels[].name] | map(select(startswith("type/"))) | .[0] // "type/unknown")}] | group_by(.tier) | map({tier: .[0].tier, count: length})'
```

One row per `type/patch|minor|major` with counts. Zero rows does **not** mean "nothing to upgrade" — the Dependency Dashboard (issue #10) and the cluster deprecation audit both catch things Renovate does not PR.

## Full workflow

### Step 1 — Enumerate the GitHub surface

Pull the PR list, the dashboard, and current Talos / Kubernetes pins in parallel:

```sh
gh pr list --author app/renovate --limit 50 \
  --json number,title,labels,headRefName,mergeable,updatedAt,createdAt
gh issue view 10
cat talos/talenv.yaml
```

Classification rules, label meanings, supersession detection → [pr-triage](references/pr-triage.md).

### Step 2 — Classify every open PR

For each PR, read the `type/{patch,minor,major}` label and the `area/*` labels, then assign to a tier. PRs with no `type/*` label (pin-dependencies runs, group PRs) default to Tier 2 minor. Branch prefixes like `renovate/<component>-<major>.x` identify the component for supersession detection.

Details → [pr-triage](references/pr-triage.md).

### Step 3 — Detect supersessions

Same component, two open PRs, lower version is superseded. Recommend closing the older PR. Do not close it yourself.

Example patterns seen in this repo:
- A major-version bump PR supersedes an older minor-version bump PR for the same chart.
- A newer PR touching the same `headRefName` prefix supersedes the older one.

Details → [pr-triage](references/pr-triage.md).

### Step 4 — Propose a tiered merge order

Four tiers, each with a different verification profile. Never collapse tiers — batching a patch with a cluster major destroys your ability to bisect a regression.

1. **Tier 1 — Patches.** Safe to batch; one Flux reconcile cycle between each.
2. **Tier 2 — Minors.** Serial; watch HelmRelease status after each.
3. **Tier 3 — CI-action majors.** Safe to batch; blast radius limited to GitHub Actions.
4. **Tier 4 — Cluster-impacting majors.** One at a time, release notes read first, deprecation audit must be clean.

Full heuristics, Talos-area pairing rules, and "never batch" exceptions → [merge-order](references/merge-order.md).

### Step 5 — Run the live-cluster deprecation audit

Renovate sees version bumps. It does **not** see "you are using an API the new version removed." Run before recommending any Tier 4 cluster major:

```sh
kubent --context "$(kubectl config current-context)" 2>&1 | tail -40
pluto detect-files -d kubernetes/ --target-versions k8s=$(yq '.kubernetesVersion' talos/talenv.yaml) 2>&1 | tail -40
pluto detect-helm -A --target-versions k8s=$(yq '.kubernetesVersion' talos/talenv.yaml) 2>&1 | tail -40
nova find --format table 2>&1 | tail -40
mise outdated 2>&1
```

If a tool is not installed, report it missing and continue — do not install from the skill. Interpretation, known false positives, target-version rules → [deprecation-audit](references/deprecation-audit.md).

### Step 6 — Read the Dependency Dashboard

Issue #10 lists everything Renovate tracks, including items it decided NOT to PR yet (rate-limited, schedule-gated, awaiting approval, group-delayed). Fetch it, scan the Detected / Errors / Pending Approval sections, and fold anything new into the report.

Details → [dependency-dashboard](references/dependency-dashboard.md).

### Step 7 — Return a single structured report

- **Superseded (recommend close)** — PR numbers with the winning PR that replaces each
- **Tier 1 — patches (safe batch)** — PR numbers in chronological order
- **Tier 2 — minors (serial)** — PR numbers with any CRD-upgrade callouts
- **Tier 3 — CI majors (batch)** — PR numbers, plus any pin-dependencies PR to merge last
- **Tier 4 — cluster majors (evaluate)** — PR numbers with specific release-note concerns and audit findings
- **Cluster audit findings** — deprecated APIs, blocked majors, missing tools
- **Dependency Dashboard extras** — items from issue #10 not covered above
- **Talos / Kubernetes pin status** — current vs. latest; hand off to `upgrade-talos-or-k8s` if a bump is available

## What this skill does NOT do

- Does not merge, close, rebase, or comment on PRs
- Does not run `kubectl apply` / `flux reconcile` / `talosctl apply` / `gh pr merge`
- Does not bump `talosVersion` / `kubernetesVersion` — hand off to `upgrade-talos-or-k8s`
- Does not re-trigger failing CI on a Renovate PR
- Does not scan running images for CVEs — that needs `trivy k8s`, not yet installed in this repo
- Does not verify cluster health after a merge — that is `anton-cluster-health`
- Does not install missing audit tools

## Related skills

- Executing a Talos OS or Kubernetes rolling upgrade → `upgrade-talos-or-k8s`
- Verifying the cluster after a chart or image bump lands → `anton-cluster-health`
- Triaging a Flux sync stuck on a new chart version → `debug-flux-reconciliation`
- Reaching nodes from off-LAN for a Talos bump → `anton-remote-access`
