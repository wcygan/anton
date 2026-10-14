# Anton

Anton is a three-node Talos Kubernetes homelab for public applications, private
services over Tailscale, and contained learning experiments. Flux reconciles
the cluster from Git.

## Routine operations

Start with the [routine operations guide](docs/docs/runbooks/routine-operations.md):

- **Check health:** confirm the Kubernetes context, check Talos, then inspect networking, Flux, and the affected service.
- **Deploy a change:** edit the owning manifests, validate locally, review and merge through the authorized Git workflow, then verify the revision, rollout, and service.
- **Diagnose a failure:** follow source → reconciliation → workload → dependencies → endpoint; stop at the first failing layer.

Discover available commands from the repository root:

```sh
mise exec -- task --list
```

Use `mise exec --` for repository commands so the pinned tools and repository
kubeconfig/talosconfig are selected. Existing operator access requires Tailscale,
the ignored `kubeconfig`, and `talos/clusterconfig/talosconfig`. See
[Talos health and target setup](docs/docs/runbooks/talos-health.md) for remote access.
Restore credentials through the private operator setup; never commit them.

## Source of truth

| Path | Purpose |
| --- | --- |
| `kubernetes/apps/` | Hand-edited Flux application manifests |
| `kubernetes/flux/` | Flux cluster reconciliation roots |
| `talos/talconfig.yaml`, `talos/talenv.yaml`, `talos/patches/` | Talos configuration sources |
| `bootstrap/` | Initial cluster bootstrap configuration |
| `context/` | Decisions, plans, inventory, and historical evidence |
| `docs/docs/` | Operator guides, runbooks, and learning notes |

There is no repository template-render step. Edit committed sources directly;
the old template commands are retired. Talos machine configs are generated
separately with `mise exec -- task talos:generate-config` before an approved
node change.

## Validation and documentation

```sh
mise exec -- task contracts:validate
```

For documentation changes, run from `docs/`:

```sh
bun install --frozen-lockfile
bun run typecheck
bun run build
```

The [docs home](docs/docs/intro.md) links to routine operations and specialist
runbooks. Playground pages preserve learning examples and do not establish what
is currently deployed.

## Bootstrap and maintenance

`bootstrap:talos` and `bootstrap:apps` initialize a cluster; they are not routine
deployment commands. Node replacement, Talos/Kubernetes upgrades, credential
rotation, and destructive recovery use the matching guidance in
[AGENTS.md](AGENTS.md) and `.agents/skills/` before any action.

`mise exec -- task reconcile` forces the root Flux reconciliation. It mutates
live state and requires explicit operator approval; normal deployment uses
Flux's webhook or polling. Reconciliation is not a diagnostic shortcut.

Anton began from [onedr0p/cluster-template](https://github.com/onedr0p/cluster-template).
