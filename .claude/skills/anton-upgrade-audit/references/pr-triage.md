# PR triage

How to classify an open Renovate PR, assign it a tier, and detect supersessions. Invoked from Steps 2–3 of the main workflow.

## Labels Renovate applies

Renovate attaches three label families to every PR it opens in Anton:

1. **`type/{patch,minor,major}`** — semver impact. Drives tier assignment.
2. **`area/{bootstrap,kubernetes,templates,mise,github,talos}`** — where in the repo the bump lands. Drives verification strategy.
3. **`renovate/{container,github-action}`** — datasource. Distinguishes Helm chart / OCI image bumps from GitHub Action bumps.

A PR with no `type/*` label is either a pin-dependencies run or a Renovate group PR. Default these to Tier 2 minor and flag for manual review.

## Tier assignment table

| Labels | Tier | Rationale |
|---|---|---|
| `type/patch` + `area/kubernetes` | Tier 1 | Chart/image patches; Flux rolls cleanly |
| `type/patch` + `area/bootstrap` | Tier 1 | Same, for bootstrap-managed components |
| `type/patch` + `area/talos` | **Special** | Pair installer + kubelet, hand off to `upgrade-talos-or-k8s` |
| `type/minor` + `area/kubernetes` | Tier 2 | Serial merge, watch HelmRelease |
| `type/minor` + `area/bootstrap` | Tier 2 | Same |
| `type/minor` + `renovate/github-action` | Tier 3 | CI-only blast radius |
| `type/major` + `renovate/github-action` | Tier 3 | CI-only blast radius |
| `type/major` + `area/mise` | Tier 3 | Toolchain-only; local impact |
| `type/major` + `area/kubernetes` or `area/bootstrap` | Tier 4 | Read release notes, run audit first |
| `type/major` + `area/talos` | **Special** | Hand off to `upgrade-talos-or-k8s` — never merge directly |
| no `type/*` label | Tier 2 | Default conservative; flag for manual look |

## Supersession detection

Two open Renovate PRs can target the same component at different versions. The older / lower one is superseded and should be closed — but the user closes it, not this skill.

**Signal**: Renovate encodes the target major in the branch name as a suffix, e.g. `renovate/<component>-83.x` or `renovate/<component>-v9.x`. Strip that suffix to get the component key and group PRs on it.

```sh
gh pr list --author app/renovate --limit 50 \
  --json number,title,headRefName,createdAt \
  --jq '
    map(. + {component: (.headRefName | sub("-[0-9]+\\.x$"; "") | sub("-v[0-9]+(\\.x)?$"; ""))})
    | group_by(.component)
    | map(select(length > 1))
    | map({component: .[0].component, prs: [.[] | {n: .number, t: .title, created: .createdAt}]})
  '
```

Any component with >1 PR is a supersession candidate. The newest PR (by `createdAt`) is the winner; recommend the rest for closure.

## Known supersession shapes

- **Major vs. earlier minor on the same chart.** A new `type/major` bump for a chart makes an older open `type/minor` PR on the same chart redundant — Renovate sometimes leaves both open until the major lands.
- **Two PRs on the same chart at different target majors.** Renovate's `separateMajorMinor` config can open both `-79.x` and `-83.x` branches for the same chart. The higher one is the winner.
- **TypeScript-style toolchain majors.** When a `type/major` bump exists (`-6.x`), any older `type/minor` on `-5.x` is superseded.

## Stale PRs

A Renovate PR untouched for >30 days with `mergeable=UNKNOWN` usually has a merge conflict or a failing CI job that Renovate auto-rebased itself into a corner on. Include it in the report with a "stale — investigate manually" note. Do not attempt to resolve the conflict from this skill.

## Talos-area PRs are always a hand-off

Any PR with `area/talos` bumps `ghcr.io/siderolabs/installer` or `ghcr.io/siderolabs/kubelet`. Those are the two version pins backing `talos/talenv.yaml`. Merging one directly without running the rolling upgrade leaves the repo and the cluster in disagreement. **Always recommend `upgrade-talos-or-k8s` for these** — never Tier 1/2/3/4.
