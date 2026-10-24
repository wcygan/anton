# Deploy Gate journeys

Each journey names its prerequisites, entry point, actions, the observable
result that counts as success, and its last recorded run. Run the helper as
`mise exec -- python3 scripts/verify-deploy-gate.py <journey>` from the
repository root. Evidence records live in the ignored `.private/deploy-gate/`.

| # | Journey | Entry point | Exercised by a command |
|---|---|---|---|
| 1 | [Settled state](#1-settled-state) | `steady` | yes |
| 2 | [Commit to cluster](#2-commit-to-cluster) | push to main, then `follow <sha>` | yes |
| 3 | [Pre-push hook](#3-pre-push-hook) | `hook` | yes, against a local bare remote |
| 4 | [Pull requests validate but never promote](#4-pull-requests-validate-but-never-promote) | `gh pr checks <number>` | read-only |
| 5 | [A failing commit is held back](#5-a-failing-commit-is-held-back) | a real gate failure on main | no: coverage gap |
| 6 | [Break-glass and rollback](#6-break-glass-and-rollback) | operator push | no: operator only |

## 1. Settled state

- **Prerequisites:** `gh` read access, the Anton kube context, `yq`.
- **Action:** `steady` reads the gate runs, fetches `main` and `deploy`, reads
  main's `flux-instance` HelmRelease, the FluxInstance, the `flux-system`
  GitRepository, and every Kustomization.
- **Success:** six checks pass: `intent`, `instance`, `source`, `promotion`,
  `fetch`, `apply`. A `wait` within a few minutes of a push is normal.
- **Last run:** 2026-10-24, pass at `9b9d6744`: all 46 Kustomizations on
  `flux-system` applied `refs/heads/deploy@sha1:9b9d6744…`.

## 2. Commit to cluster

- **Prerequisites:** authority to push the commit to main; journey 1's tools.
- **Action:** push to main, then run `follow <sha>`. It polls the cluster every
  5 s, records when Flux fetched the commit (or a later main commit that
  contains it) and when every Kustomization applied it, then reads that
  commit's gate run once.
- **Success:** Contracts, Render, and Promote succeeded; Flux fetched the
  commit no earlier than Promote's completion (5 s clock allowance); every
  Kustomization on `flux-system` applied it.
- **Last run:** 2026-10-24, `9b9d6744` (`.gitignore` and a test fix), watched
  before the helper existed. Pushed 15:58:04Z; Render 15:58:08–15:58:46;
  Contracts 15:58:08–15:59:26; Promote 15:59:30–15:59:37; Flux fetched
  `deploy@9b9d6744` at 15:59:39; all 46 Kustomizations applied it by 16:00:06.
  Earlier that day Promote fast-forwarded `deploy` past the Renovate
  workflow-file bump `77091a29`, which proves the App token path.

## 3. Pre-push hook

- **Prerequisites:** `mise` with the repository's pinned tools.
- **Action:** `hook` clones this checkout's `HEAD` into a temporary directory,
  removes its `origin`, adds a local bare repository as remote `verify`, pins
  the clone's hooks path, installs the hook with `scripts/install-git-hooks.sh`,
  and pushes four times.
- **Success:** a passing commit reaches `verify/main`; a commit adding
  `docs/docs/verify-deploy-gate-probe.md` (outside the documentation sections)
  is refused by `contracts:fast`; `deploy` without `ANTON_BREAK_GLASS=1` is
  refused; break-glass `deploy` of a main commit is accepted. The temporary
  directory is gone afterwards.
- **Simulated boundary:** the remote is a local bare repository, not GitHub.
  The hook, the validators, and `git push` are the real ones.
- **Last run:** 2026-10-24, pass 4/4 at `9b9d6744`. The probe was refused with
  `verify-deploy-gate-probe.md: outside canonical sections`; the `deploy` push
  with `Refusing to push deploy: the Deploy Gate promotes main commits that pass`.

## 4. Pull requests validate but never promote

- **Action:** `gh pr checks <number> --repo wcygan/anton` on any open pull
  request to main.
- **Success:** Contracts and Render report results; Promote reports `skipping`.
- **Last run:** 2026-10-24 on wcygan/anton#558: Contracts and Render passed,
  Promote skipped.

## 5. A failing commit is held back

Not exercised live: pushing a known-failing commit to main on purpose would
break the main branch for everyone. Static coverage instead:
`scripts/tests/test_deploy_gate.py` pins that Promote needs both checks and
runs only for pushes to main, and `test_verify_deploy_gate.py` covers the
`held` verdicts. When the gate fails on main for real, run `steady` (expect
`promotion` held and the cluster on the last passing commit) and record the
run here.

## 6. Break-glass and rollback

Operator only; agents never push `deploy`. The 2026-10-24 cutover used one
atomic break-glass push of `450ecd17` to `main` and `deploy`; Flux moved to
`deploy@450ecd17` by 15:52:43Z with a single `flux-instance` upgrade and no
switching back. Journey 3 covers the hook side of break-glass. Rolling Flux
back to `main` (commit the old ref and let the gate promote it) is untested.
