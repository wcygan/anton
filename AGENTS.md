# AGENTS.md

Goal: Work safely in the **anton** Talos Kubernetes homelab repo.

Success means:
- Read the matching subsystem guidance before changing manifests, Talos config, scripts, plans, or docs.
- Preserve GitOps source-of-truth files and the existing Claude Code setup.
- Protect secrets, SOPS encryption, cluster context, and tailnet privacy.
- Verify changes with the narrowest command that proves the edited surface.

Stop when: the requested change is implemented, validation evidence is recorded, and any live-cluster or destructive action is left for explicit operator approval.

## Repo Model

Anton is a hand-edited Talos + Flux cluster. `kubernetes/`, `talos/`, and `bootstrap/` are committed directly; there is no render step. Talos machine configs are generated from `talos/talconfig.yaml` plus `talos/talenv.yaml` with talhelper. Flux owns cluster convergence after bootstrap.

## Instruction Files

Read the file that matches the area you touch:

| Area | Read |
|---|---|
| Flux apps | [kubernetes/apps/AGENTS.md](kubernetes/apps/AGENTS.md) |
| Network, gateways, Multus, storage VXLAN | [kubernetes/apps/network/AGENTS.md](kubernetes/apps/network/AGENTS.md) |
| Longhorn and SeaweedFS | [kubernetes/apps/storage/AGENTS.md](kubernetes/apps/storage/AGENTS.md) |
| CNPG and Dragonfly operators | [kubernetes/apps/databases/AGENTS.md](kubernetes/apps/databases/AGENTS.md) |
| Harbor registry | [kubernetes/apps/registries/AGENTS.md](kubernetes/apps/registries/AGENTS.md) |
| Talos config and patches | [talos/AGENTS.md](talos/AGENTS.md) |
| Bootstrap Helmfile | [bootstrap/AGENTS.md](bootstrap/AGENTS.md) |
| Shared scripts | [scripts/AGENTS.md](scripts/AGENTS.md) |
| Task wrappers | [.taskfiles/AGENTS.md](.taskfiles/AGENTS.md) |
| ADRs and plans | [context/AGENTS.md](context/AGENTS.md) |
| Docusaurus docs | [docs/AGENTS.md](docs/AGENTS.md) |

The `.claude/` tree is still authoritative precedent during the Codex migration. Use it as source material, and keep it intact.

## Commands

```sh
task --list
task qmd:bootstrap
task reconcile
task talos:generate-config
task talos:apply-node IP=<ip> MODE=auto
task talos:upgrade-node IP=<ip>
task talos:upgrade-k8s
flux get ks -A
flux get hr -A
```

The repo sets `KUBECONFIG`, `SOPS_AGE_KEY_FILE`, and `TALOSCONFIG` through `Taskfile.yaml` and `.mise.toml`.

## QMD Context Search

Use QMD early when work depends on Anton's accumulated operating context: ADRs, plans, incidents, postmortems, hardware/software inventory, or investigation notes under `context/`.

The repo-local collection is `anton-context`, configured in `.qmd/index.yml` and rooted at `context/**/*.md`. The generated SQLite index stays local and git-ignored. If the index is missing or stale, rebuild it with:

```sh
task qmd:bootstrap
```

Search with QMD before broad manual browsing when the question is historical, conceptual, or decision-oriented:

```sh
qmd search "platform dependsOn rule" -c anton-context -n 5
qmd query "why did we adopt multus for longhorn storage traffic" -c anton-context
qmd get qmd://anton-context/adrs/0027-platform-dependson-rule.md
```

Treat search snippets as leads only. Retrieve the source with `qmd get` or `qmd multi-get` before making factual claims, and cite the actual `context/` path in summaries. Use `rg` for exact code/manifests and QMD for context recall; QMD does not replace reading the files you change.

## Safety Rules

- Keep the literal tailnet name out of committed files. Use `<tailnet-name>.ts.net`.
- Keep existing `*.sops.*` files encrypted. Edit them with `sops <file>` and verify with `sops filestatus <file>`.
- Keep bootstrap credentials out of edits: `age.key`, `github-deploy.key`, `cloudflare-tunnel.json`, and token files.
- Use read-only cluster commands for investigation: `kubectl get/describe/logs`, `talosctl get/read/logs/health`, `flux get/logs`.
- Ask for explicit operator approval before live-cluster mutations, credential rotation, Talos reset/upgrade/apply, namespace deletion, Flux suspend/uninstall, or recursive deletion.
- Verify kube/talos context before mutating cluster state. The expected Kubernetes context is the Tailscale operator proxy, with `admin@anton` only as fallback.

## Development Loop

1. Read the subsystem `AGENTS.md` and representative sibling files.
2. Edit the committed source of truth directly.
3. For Talos source edits, run `task talos:generate-config`.
4. For SOPS files, verify encryption with `sops filestatus`.
5. Run the narrowest relevant validation: YAML parse, skill/hook fixture, Docusaurus check, or Flux/Talos read-only status.
6. Summarize changed files, validation output, and any operator-only follow-up.

## Codex Enablement

Repo-local Codex work is tracked in [context/plans/0017-codex-usage-parity.md](context/plans/0017-codex-usage-parity.md). Add Codex skills under `.agents/skills/`, Codex project config and hooks under `.codex/`, and keep each port scoped to a proven Claude precedent.
