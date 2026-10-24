---
name: verify-deploy-gate
description: >-
  Verify Anton's Deploy Gate end to end: a main commit passes Contracts and
  Render, Promote fast-forwards `deploy`, and Flux applies only what `deploy`
  holds. Use for "did my push deploy?", "is the gate working?", after changing
  the gate workflow, `promote-deploy.py`, the pre-push hook, or the
  FluxInstance sync ref, and when `flux-system` is Ready but behind main.
---

# Verify the Deploy Gate

The outcome is a verdict for each journey you run (pass, wait, or fail) and a
JSON evidence record that shows why. The gate itself is described in
[the deploy guide](../../../docs/docs/guides/deploys.md) and
[ADR 0045](../../../docs/docs/decisions/0045-deploy-only-validated-commits.md).

## Before you start

Run everything from the repository root through `mise exec --`. You need:

- `gh` signed in with read access to `wcygan/anton`;
- the Anton kube context (see `anton-remote-access`); and
- the `origin` remote pointing at GitHub.

The helper `scripts/verify-deploy-gate.py` only reads Git, GitHub, and the
cluster, except that `hook` pushes to a throwaway local bare repository. It
never pushes `deploy`, reconciles Flux, or changes the cluster. Pushing a
commit to `main` for the `follow` journey is an ordinary repository change and
needs the usual authority. Break-glass pushes belong to the operator.

## Run the journeys

| Journey | Command | Proves |
|---|---|---|
| Settled state | `steady` | main's sync ref, the FluxInstance, and the `flux-system` source all name `deploy`; `deploy` is at main; Flux applied it |
| Commit to cluster | `follow <sha>` after pushing `<sha>` to main | the cluster fetched `<sha>` from `deploy` only after the gate's Promote job finished, and every Kustomization applied it |
| Pre-push hook | `hook` | the hook passes a good commit, refuses one that fails `contracts:fast`, refuses `deploy` without break-glass, and accepts break-glass for a main commit |

```sh
mise exec -- python3 scripts/verify-deploy-gate.py steady --evidence .private/deploy-gate/$(date -u +%Y%m%dT%H%M%SZ)-steady.json
```

Use the same form for `follow <sha>` and `hook`. `follow` polls the cluster
every 5 s for up to 15 min; expect two to three minutes from push to verdict.
`hook` runs `contracts:fast` three times in a throwaway clone and takes a few
minutes. [references/journeys.md](references/journeys.md) lists every journey,
including the ones no command exercises, with the last recorded run.

## Read the verdict

The helper exits 0 for pass, 3 for wait (not settled yet), and 1 for fail. Each
line names the failing check:

| Check | Fail or wait means | Next step |
|---|---|---|
| `intent` | main's `flux-instance` HelmRelease names another ref | Restore `ref: "refs/heads/deploy"` with a commit on main |
| `instance`, `source` | Flux reads another branch, so commits skip the gate | Compare the FluxInstance with main's HelmRelease; use `debug-flux-reconciliation` |
| `promotion` held | the gate failed for main's head; `deploy` keeps the last passing commit | Fix forward on main; see "When the gate fails" in the deploy guide |
| `promotion` diverged | `deploy` has commits main lacks | Operator only: "Recover a diverged deploy branch" in the deploy guide |
| `fetch` wait | Flux has not fetched the newest `deploy` commit yet | Re-run after a minute; it is not a failure |
| `apply` | a Kustomization is still applying (wait) or failed (fail) | Use `debug-flux-reconciliation` for the named object |
| `follow` bypass | the cluster fetched the commit before Promote finished | Treat as an incident: Flux is not gated |

Never reconcile Flux to "fix" a commit that `deploy` does not hold yet; a
reconcile cannot fetch it. Read `mise exec -- task deploy:status` first.

## Keep evidence and clean up

Write evidence under `.private/deploy-gate/`, which Git ignores. A record holds
the verdict, every check or case, the gate run and job times for `follow`, the
checkout commit, and only the first label of the kube context. `steady` and
`follow` create nothing else. `hook` deletes its throwaway clone even when a
case fails; with `--keep` it prints the clone's path, and you delete it after
debugging.
