# Merge order heuristics

How to turn a classified PR list into an actionable, batched merge plan. Invoked from Step 4 of the main workflow.

## The four tiers

### Tier 1 — Patches (safe batch)

- Merge multiple in one sitting; Flux reconciles between each
- Wait for `flux get hr -A --status-selector ready=false` to return empty before moving on
- Typical examples: CoreDNS, Cilium, cert-manager, external-secrets, Reloader, k8s-gateway patch bumps

**Ordering rule**: merge in chronological order (oldest `createdAt` first). This lets rebase-on-main conflicts resolve in the order Renovate expected.

**Exception — Talos patches.** Even at patch level, `ghcr.io/siderolabs/installer` and `ghcr.io/siderolabs/kubelet` bumps require the rolling upgrade workflow. Pair them, hand off to `upgrade-talos-or-k8s`, and do not include in a Tier 1 batch.

### Tier 2 — Minors (serial)

- One PR at a time
- After each merge: watch Flux reconcile, confirm the target HelmRelease goes `Ready=True`, glance at the component's pods for `CrashLoopBackOff`
- Typical examples: external-dns, app-template, envoy-gateway minor, Spegel, flux-operator group, kube-prometheus-stack minor

**CRD upgrade warning.** Flux does **not** auto-upgrade CRDs for HelmReleases. If a minor bump is on a chart that owns CRDs — envoy-gateway, cert-manager, kube-prometheus-stack, external-secrets — flag it in the report so the user can check whether manual `kubectl apply` of the chart's CRDs is required. Renovate does not check this.

**Read the CHANGELOG.** Renovate does not summarize upstream release notes. For any Tier 2 minor on a CRD-owning chart, recommend a manual release-notes read.

### Tier 3 — CI-action majors (batch)

- Blast radius limited to GitHub Actions workflows — cluster state is untouched
- Safe to batch; CI failures surface immediately and can be reverted as a group
- Typical examples: `actions/checkout`, `actions/github-script`, `actions/deploy-pages`, `actions/configure-pages`, `jdx/mise-action`, `mshick/add-pr-comment`, `ghcr.io/allenporter/flux-local`

**Pin-dependencies PR ordering.** If Renovate has an open "pin dependencies" PR (it re-pins all action SHAs to the latest release tag), merge it **last** in the CI batch — it needs to re-pin against the already-bumped majors, otherwise the pins go stale immediately.

### Tier 4 — Cluster-impacting majors (evaluate individually)

- One at a time
- **Must** be preceded by the Step 5 deprecation audit being clean for the target chart
- **Must** include a read of upstream release notes before merging
- Separate back-to-back Tier 4 merges by at least one full Flux reconcile cycle and a `flux get hr -A` check

**Risk-amplified examples** (patterns that recur — check current repo state each run):

| Pattern | Why high-risk |
|---|---|
| kube-prometheus-stack jumping multiple majors | CRD schema changes, dashboards break, alerting rules move |
| Helm CLI major bump (v3→v4) | Affects `helmfile`, `talhelper`, and bootstrap scripts — verify each still works |
| envoy-gateway / Gateway API minor+ | Gateway API is versioned independently; can break HTTPRoute attachment |
| TypeScript / node-tooling majors | Only risky if something in this repo actually runs TS; check first |
| cloudflared major | Tunnel protocol / config format can change — cross-check against the recent QUIC→HTTP/2 fix in commit `42822fc3` |

## Never batch across tiers

- **Never** merge a Tier 1 patch and a Tier 4 major in the same sitting. If cluster health degrades after the batch, bisecting which one caused it is painful.
- **Never** merge two Tier 4 majors back-to-back. Separate them with a full Flux reconcile cycle + cluster health check.
- **Never** batch a Tier 2 CRD-chart minor with anything else. CRD upgrades on envoy-gateway, cert-manager, or kube-prometheus-stack are single-PR-per-batch events.

## The "golden hour" rule

After merging a Tier 2 minor or a Tier 4 major, do not close the tab for at least 15 minutes. Flux reconciles on a default interval; symptoms of a bad chart upgrade (failing HelmRelease, webhook timeouts, CRD schema rejection) can take one or two reconcile cycles to surface. Running `anton-cluster-health` 10–15 minutes after the merge catches most of these.
