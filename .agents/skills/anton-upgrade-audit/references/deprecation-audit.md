# Deprecation audit

Renovate sees version bumps. It does **not** see "you are using an API the new version removed." This audit is the gate before recommending any Tier 4 cluster-impacting major. Invoked from Step 5 of the main workflow.

## Tools

| Tool | Scope | Install (do NOT run from skill) |
|---|---|---|
| `kubent` | Live cluster: in-use API versions vs. removal schedule | `brew install kubent` |
| `pluto` | Rendered manifests + installed Helm releases | `brew install FairwindsOps/tap/pluto` |
| `nova` | Helm release versions vs. upstream latest | `brew install FairwindsOps/tap/nova` |
| `mise outdated` | Toolchain pins in `.mise.toml` | already in toolchain |

As of April 2026, `kubent`, `pluto`, and `nova` are **not** installed in Anton's toolchain. Report them missing and continue — do not install them from this skill. Recommend adding them to `.mise.toml` or a `brew` bundle as a follow-up.

## Commands

Target the k8s version currently pinned in `talos/talenv.yaml` so the audit matches reality:

```sh
K8S_VERSION=$(yq '.kubernetesVersion' talos/talenv.yaml)

# Live-cluster API deprecations
kubent --context "$(kubectl config current-context)" 2>&1

# Rendered manifests — check what is in the repo
pluto detect-files -d kubernetes/ --target-versions k8s="${K8S_VERSION}"

# Installed Helm releases — check what is actually in the cluster
pluto detect-helm -A --target-versions k8s="${K8S_VERSION}"

# Helm release drift vs. upstream latest
nova find --format table

# Toolchain drift (read-only — does not install)
mise outdated
```

## Interpreting output

### kubent

Output rows list an in-use API, the version that deprecated it, and the version that removes it. **Action thresholds**:

- **`REMOVED IN` ≤ current k8s + 1 minor** → **blocker**. Fix before merging any k8s bump, and block the corresponding `upgrade-talos-or-k8s` hand-off.
- **`REMOVED IN` ≤ current k8s + 2 minors** → warning. Include in the report; the next Tier 4 kube bump PR depends on it.
- **`REMOVED IN` > current k8s + 2 minors** → informational.

Empty output is the desired state.

### pluto

`detect-files` scans rendered manifests under `kubernetes/`. `detect-helm` scans installed Helm releases in the cluster. They can disagree — the cluster may have stale releases from before a chart refactor. Trust `detect-helm` for what the cluster will actually break on, `detect-files` for what will break on re-render.

**Known false positives in Anton**:

- Rook-Ceph CRDs were removed in commit `889a9662` but leftover manifests may still exist in archived paths. Confirm no active HelmRelease references them before treating as real.
- `flux-local` CI pre-validates manifests with a different target version than your local `K8S_VERSION`. Trust the skill's output (which uses `talenv.yaml`), not flux-local's.

### nova

Reports chart drift even when Renovate has not opened a PR yet — Renovate rate-limits and group-delays PRs, nova reads the live cluster against upstream immediately. This is the second-most-valuable output of the audit (after kubent) because it catches the "Renovate does not know about this yet" gap.

Cross-reference nova's output against the Tier 1–4 PR list:

- Drift **matching** an open PR → expected, no action
- Drift **not matching** any open PR → check the Dependency Dashboard (issue #10), it may be rate-limited or grouped

### mise outdated

The `.mise.toml` pins tools. Output shows any tool where the pinned version is newer than the installed version — this usually means "local install is stale, run `mise install`", not "the pin itself is out of date". For the pin-out-of-date signal, rely on the Renovate `area/mise` PRs instead.

## Reporting format

When writing up Step 5 results, group findings by severity:

- **Blockers** — kubent rows in the "current+1" zone; block any k8s bump
- **Warnings** — kubent "current+2" zone, pluto rendered-manifest warnings
- **Info** — nova drift that already has an open PR (expected)
- **Missing tools** — list any of kubent/pluto/nova/trivy not installed, with the one-line install hint

If all audits are clean AND the mise/pin checks are clean, state explicitly: *"Deprecation audit clean — Tier 4 majors evaluated individually below are safe from API-removal perspective, but still require release-note reads."*
