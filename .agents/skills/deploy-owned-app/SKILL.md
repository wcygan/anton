---
name: deploy-owned-app
description: Drive the full lifecycle of an owned anton app deployed via Flux image-automation (ADR 0024 / plan 0012). Two modes auto-detected by checking for an existing `ImageRepository`. **Onboard mode** (new app, no ImageRepository found) — guides authoring the Dockerfile + GH Actions workflow in the app repo, flipping the GHCR package public, scaffolding the anton-side manifests (Deployment + Service + HTTPRoute + DNSEndpoint + 3 image-automation CRs), wiring them into the parent kustomization, committing, and watching the first rollout. **Redeploy mode** (ImageRepository exists) — short-circuits the default 5m polling cadence: `flux reconcile image repository/update`, GitRepository fetch, Kustomization apply, deployment rollout watch, public-URL HTTP-200 check. Works for any owned app following the ADR 0024 / plan 0012 pattern (homepage today, others later). On stuck loops, reports where it failed and hands off to `debug-flux-reconciliation`. Keywords — deploy, deploy app, deploy homepage, redeploy, redeploy app, redeploy homepage, onboard app, new owned app, set up app, kick flux, force reconcile, force redeploy, image-automation, image update, GHCR, deploy now, see it live, watch the loop, verify deploy.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
argument-hint: <app-name> [--no-force] [--no-watch] [--no-verify]
---

# Deploy owned app

Anton-local skill for the full lifecycle of an owned-app deploy via Flux image-automation. Two modes auto-detected from cluster state: **onboard** (first-time scaffold) and **redeploy** (kick the loop on an existing app).

## Mode selection

```sh
flux get image repository <app-name> -A
```

- **Found** → redeploy mode (see [redeploy](references/redeploy.md))
- **Not found** → onboard mode (see [onboard](references/onboard.md))
- **Ambiguous (multiple namespaces)** → abort, ask user for `<namespace>/<app-name>` form

The mode split exists because the work each does is qualitatively different. Redeploy is procedural and observational; onboard is creative and writes manifests. Same skill because they share the same downstream verify path (rollout watch + HTTP 200) and the same mental model ("I am the operator of this owned app and I want it to deploy").

## Why this skill exists

Per ADR 0024 / plan 0012, owned apps deploy via Flux image-automation: GH Actions → registry → image-reflector scans → image-automation commits to anton → Flux reconciles. Onboarding a new app touches ~7 files across two repos plus a click in the GHCR org settings; redeploys want sub-minute feedback instead of waiting 5+ minutes for the next poll. This skill drives both flows so the operator stays in one mental model.

It is NOT a recovery tool. If something breaks during either flow, it reports and stops; recovery is `debug-flux-reconciliation`'s job.

## Hard rules

- **Never modifies app-repo code beyond the Dockerfile and `.github/workflows/build.yaml`.** No frontend edits, no dependency changes — onboarding only adds the deployment plumbing.
- **Never bypasses Flux.** No `kubectl rollout restart`, no `kubectl set image`, no `kubectl apply` on owned-app manifests. Every cluster mutation goes through anton's GitOps loop.
- **Never commits or pushes without explicit user confirmation.** Surface the diff, ask, then commit. Same on push.
- **Stops on first error.** Doesn't retry, doesn't auto-recover. Reports where it stopped and what to run next.
- **One app at a time.** No batch flag, no "deploy all owned apps."
- **GHCR public-flip and Cloudflare/external-DNS configuration are user actions** — the skill cannot perform them and must say so explicitly.

## Inputs

- Required: `<app-name>` (positional). Used to look up an `ImageRepository` and to derive default namespace + manifest paths.
- Optional flags (redeploy mode only):
  - `--no-force` — report-only: show CR status, deployment, HTTP, no reconciles
  - `--no-watch` — kick the chain and exit
  - `--no-verify` — skip the public HTTP check
- Default: full force + watch + verify.

## Workflow entry point

1. Run mode-selection query above.
2. Branch:
   - **Redeploy** → load [references/redeploy.md](references/redeploy.md), execute its steps
   - **Onboard** → load [references/onboard.md](references/onboard.md), execute its steps (interview-driven; pauses on each user-action milestone)
3. Both modes converge at:
   - Watch deployment rollout
   - Verify public URL HTTP 200 (skipped if no HTTPRoute or `--no-verify`)
   - Print timing summary

## Reporting format

Always end with a status block. Format depends on mode and outcome.

**Redeploy success**:
```
✅ <app> deployed
   namespace:    <ns>
   image tag:    <new>  (was <old>)   ← or "unchanged — no new build"
   bot commit:   chore(<app>): <tag>  ← or "no commit needed"
   pod:          <pod-name> Running
   url:          https://<host>/  →  200
   total elapsed: <N>s
```

**Onboard success**:
```
✅ <app> onboarded and serving
   anton commit:   feat(<app>): adopt image-automation
   manifests:      kubernetes/apps/<ns>/<app>/  (10 files)
   first image:    <registry>/<app>:<tag>
   pod:            <pod-name> Running
   url:            https://<host>/  →  200
   total elapsed:  <N>s  (commit → 200)
   next step:      push a code change to <app-repo>; loop will redeploy autonomically
```

**Failure** (either mode):
```
❌ <app> deploy stopped at: <stage>
   reason:       <one-line message from the offending object>
   recommend:    /debug-flux-reconciliation
   diagnostic:   <one targeted command the user can run>
```

See [references/troubleshoot.md](references/troubleshoot.md) for the full failure → recommendation table.

## What this skill does NOT do

- Doesn't author app frontend code, dependencies, or business logic.
- Doesn't recover stuck reconciles — `debug-flux-reconciliation`.
- Doesn't run the upstream build — GH Actions does on push.
- Doesn't watch GH Actions itself — `gh run watch` is separate.
- Doesn't redeploy without an actual image-tag change — if the policy resolves to the same tag, exits with "no new image."
- Doesn't work for Renovate-managed images (those go through PR review, not image-automation).
- Doesn't create GitHub repositories — operator does that out-of-band.
- Doesn't flip GHCR package visibility — operator does that in the GHCR UI; the skill verifies via anonymous pull.
- Doesn't approve the use of `envoy-external` per ADR 0023 — operator must explicitly choose the gateway.

## Related skills and agents

- `add-flux-app` — useful for the manifest scaffold during onboarding; this skill calls it for shared bits (namespace + ks.yaml convention) but adds the image-automation CRs and `images:` setter marker on top.
- `expose-service` — author the HTTPRoute + DNSEndpoint during onboarding. This skill defers gateway choice to the user since `envoy-external` requires ADR 0023 approval.
- `debug-flux-reconciliation` — what to run when this skill stops on a stuck reconcile.
- `anton-cluster-health` — when the failure looks cluster-wide rather than app-specific.
- `observability-integrate` — wire a deploy-frequency / image-automation-success panel after the first successful onboard.
- ADRs/plans: [`0024`](../../../context/adrs/0024-adopt-image-automation-for-owned-apps.md) (decision), [`0012`](../../../context/plans/0012-image-automation-homepage-rollout.md) (homepage as canonical example), [`0023`](../../../context/adrs/0023-shared-cloudflare-tunnel-only.md) (shared tunnel; gateway constraint).

## Anti-patterns

- **Running redeploy every minute hoping the build will arrive.** If you're tempted, `gh run watch` in the app repo first — the build hasn't pushed.
- **Using onboard to migrate a Renovate-managed image to image-automation.** Different patterns; that's a deliberate architectural change worth its own ADR/plan.
- **Skipping the GHCR public-flip step** — the skill *will* fail loudly at the cluster-pull stage, but the failure is avoidable with one click before you start.
- **Adding HTTPRoute manifests for `envoy-external` without ADR 0023 approval.** The skill asks; honor the answer.
- **Running the skill while flux-system is unhealthy.** Run `anton-cluster-health` first; this skill assumes a working Flux.

## Example sessions

User: `/deploy-owned-app homepage` (already exists in cluster)

Skill detects ImageRepository → redeploy mode → kicks chain → watches rollout → verifies HTTPS 200 → reports "32s end-to-end."

User: `/deploy-owned-app newproject` (no ImageRepository found)

Skill detects no ImageRepository → onboard mode → asks: app repo path, registry (GHCR/Harbor), gateway choice, hostname → scaffolds 10 files → presents diff → on user confirm, commits + pushes → watches first reconcile → verifies HTTPS 200 → reports "onboarded in 4m12s."

User: `redeploy homepage` (description-triggered)

Skill detects existing ImageRepository → redeploy mode → same as `/deploy-owned-app homepage`.

User: `/deploy-owned-app homepage --no-force`

Status print only — no reconciles fired. Useful when paired with a tail of `flux events` to passively observe.
