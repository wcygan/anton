---
status: Accepted
date: 2026-10-23
deciders: ['@wcygan']
affects: all
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
slug: /decisions/0045-deploy-only-validated-commits
---

# 0045 — Deploy only commits that pass the deploy gate

> Flux reconciles a `deploy` branch that CI fast-forwards to each `main` commit that passes the contract suite and a full render.

## Context

Flux reconciled `main` directly, so a push was live within about a minute. Nothing checked a commit on the way. The contract suite ran only when someone remembered to run it locally, and the flux-local render check ran only on pull requests, while most commits are pushed straight to `main`. Renovate's branch automerges land on `main` without checks too.

In October 2026 a change reached the cluster while a piped validation command hid a failing exit code. The failure was a flaky test, but nothing would have stopped a real one.

Several writers reach `main`: the operator, agent sessions, merged pull requests, and Renovate. A gate that depends on every writer following a procedure leaves a gap for each of them.

## Decision

Flux reconciles `refs/heads/deploy` instead of `main`. The Deploy Gate workflow runs on every push to `main`: the full contract suite in one job and a flux-local render of every Kustomization and HelmRelease in another. When both pass, it fast-forwards `deploy` to that commit. Pull requests run the same two checks without promoting.

- **Fast-forward only.** A late run for an older commit cannot rewind `deploy`. If `deploy` ever holds commits that `main` lacks, promotion stops until an operator reconciles the branches.
- **Promotion credential.** The default workflow token cannot move a branch past changes to workflow files, which Renovate makes routinely. A dedicated GitHub App, limited to this repository's contents and workflows, mints a short-lived token for each promotion. Its key lives in a `deploy` environment that admits only `main`.
- **Break glass.** When the gate itself is broken, the operator fast-forwards `deploy` by hand to a commit that is already on `main`. The local hook requires `ANTON_BREAK_GLASS=1` for that push.
- **Local hook.** An optional pre-push hook runs the static validators against each pushed commit in a few seconds. It catches mistakes before they become public history. The gate does not depend on it.

## Alternatives considered

- **Do nothing:** unvalidated pushes keep reaching the cluster within a minute.
- **Protect `main` with required checks and auto-merge:** every change, including Renovate's branch automerges, would need a pull request. The operator administers the repository, so an emergency bypass would also bypass the gate for routine pushes, the path that caused the incident. Checks would validate a pull request's merge preview rather than the squashed commit that deploys, and personal repositories have no merge queue to close that gap.
- **Publish validated OCI artifacts for Flux:** the cleanest separation, but every Kustomization's source reference would change and a registry would join the deploy path.
- **Pre-push hook alone:** easy to skip, and it never sees Renovate's commits.
- **SSH deploy key instead of a GitHub App:** simpler to create, but the key never expires and rulesets cannot single it out from other deploy keys.

## Consequences

- A push takes about two to three minutes to go live instead of one.
- `main` can hold a failing commit. `deploy` then stays at the last passing commit until a fix lands, and the commits in between deploy together. GitHub notifies whoever pushed the failing commit. A failure from a Renovate automerge notifies no one, so `task deploy:status` is the place to look.
- The GitHub App key is one more credential to rotate.
- A break-glass push skips validation. It shows as `deploy` ahead of the newest passing gate run.
- The cutover from `main` to `deploy` must push the same commit to both branches at once; otherwise Flux alternates between them until the gate promotes the switch.
- The authenticated auxiliary source still deploys directly from its own repository. This gate covers only this repository.
