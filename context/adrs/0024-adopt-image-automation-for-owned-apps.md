---
status: Accepted
date: 2026-05-01
deciders: ['@wcygan']
affects: compute
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0024 — Adopt Flux image-automation-controller for owned apps; GHCR for public, Harbor for private

> Anton splits container-image update flow on two tracks. Upstream artifacts (Helm charts, third-party images, base images) keep using Renovate on the cluster-template-default weekly cadence with PR review. Apps the operator owns and ships ("owned apps") use Flux's `image-reflector-controller` + `image-automation-controller` to poll the source registry, resolve a tag policy, and commit the bump back to anton — fully closed-loop, no cross-repo CI credentials. Public owned apps push to GHCR; private owned apps push to Harbor's private projects.

## Status

Accepted

## Context

Anton was bootstrapped from `onedr0p/cluster-template`, which ships a `.renovaterc.json5` configured to scan every YAML under `kubernetes/` for image and chart references and open weekend-batched PRs for bumps. Auto-merge is reserved for `github-actions` and `mise` tools; container-image bumps land as PRs that the operator reviews and merges. Flux already runs a GitHub webhook `Receiver` (`flux-webhook.${SECRET_DOMAIN}`) so a merge to anton@main reconciles within seconds.

This works well for the artifacts Renovate is designed for: upstream Helm charts, mirrored images (`mirror.gcr.io/...`), GitHub Actions, and base-image digests. It does **not** fit two adjacent use cases that have now arrived:

1. The `nu-sync/homepage` app — a brand-new Bun + TanStack Start static site, public, expected to ship frequently, where "deploys eventually after a code push" is the goal but a weekly Renovate batch is too slow and the merge gate is friction without value.
2. `csgoplant` — an existing private app currently deployed via a local `just deploy` script that bypasses GitOps entirely (builds, pushes to Harbor's anonymous-pull `library/` project, applies manifests via `kubectl`). The script-driven flow is a drift risk and is not how every other anton workload is managed.

Both want a path that is *pull-based* (Flux watches the registry; CI's only job is "build and push"), supports multiple deploys per day, and works at the controller level rather than per-repo.

The 2026-04-30 web research pass showed the homelab community (`onedr0p/home-ops`, `buroa/k8s-gitops`, `szinn/k8s-homelab`, `nickclyde/homelab`, `gabe565/home-ops` and other cluster-template descendants) overwhelmingly skips Flux's image-automation controllers and uses Renovate exclusively, *because* their owned-app deploy frequency is low. anton diverges here only because the homepage and csgoplant deploy cadences are higher than the cluster-template-default Renovate model serves cleanly. Renovate stays for everything else; image-automation is added on top, scoped narrowly to images the operator builds.

The two controllers (`image-reflector-controller` scans registries; `image-automation-controller` writes commits) are first-class Flux components — they slot into the existing `flux-instance.spec.values.instance.components` list, share the same deploy key as the rest of Flux's GitOps loop, and emit events through the existing `notification-controller`. There is no new credential surface beyond per-private-registry pull tokens (which would be needed under any strategy that uses a private registry).

## Decision

Anton will adopt Flux image-automation on a two-track model:

1. **Add `image-reflector-controller` and `image-automation-controller`** to `flux-instance.spec.values.instance.components` in `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`.

2. **Each owned app gets three CRs** in its Flux app directory:
   - `ImageRepository` — registry scan, configurable `interval` (default `5m`)
   - `ImagePolicy` — tag selector (`alphabetical` for `main-<sha>`, `semver` when the app emits semver tags)
   - `ImageUpdateAutomation` — commits the bump to anton@main directly (no PR), authored as `flux@anton`, message `chore(<app>): {{.Updated.Images}}`

3. **The image reference in the app's manifest is marked** with the canonical Flux setter comment so the automation knows where to write:

   ```yaml
   # kustomization.yaml
   images:
     - name: <registry>/<app>
       newTag: <current>  # {"$imagepolicy": "flux-system:<app>:tag"}
   ```

4. **Per-app registry choice follows the privacy boundary**, not the automation tool:
   - **Public owned apps → GHCR.** No `imagePullSecret`, no `secretRef` on `ImageRepository`. The first push from a new repo lands as a private package by default in an org context; flip to public in the org's Packages settings. (Footgun acknowledged; one-time per package.)
   - **Private owned apps → Harbor private project + robot account.** A pull-only Harbor robot's docker-config is mounted via `ExternalSecret` of type `kubernetes.io/dockerconfigjson` for the workload, and a separate `Secret` (also dockerconfigjson) is referenced by `ImageRepository.spec.secretRef` so reflector can list tags.

5. **Renovate's scope is unchanged.** It continues to scan all of `kubernetes/` and open PRs for upstream charts, third-party images, GitHub Actions, and mise tools. Owned-app images covered by image-automation are not Renovate's concern; the two writers edit different image references in different files, so there is no overlap. No `.renovaterc.json5` change is required to keep this clean — the only optional addition would be a `packageRule` excluding owned-app image patterns if it ever creates noise (deferred until observed).

6. **Tracking is layered, not single-source.** The five existing layers (anton's git log filtered to `--author=flux`, `flux get image {repository,policy,update}`, `flux events`, notification-controller `Alert` to a chat webhook, and Prometheus metrics from the new controllers via the existing kube-prometheus-stack PodMonitor) are sufficient. The minimum-viable subset is **git log + a notification-controller `Alert`**; the metrics dashboard is optional and deferred.

The first concrete adopter is `nu-sync/homepage`. `csgoplant` will follow once the existing local `just deploy` script is retired, manifests are migrated into anton (separate work), and a Harbor private project replaces the current `library/` push target.

## Alternatives considered

- **Stay on Renovate only, even for owned apps.** The default homelab pattern. Rejected for owned apps specifically — the weekend batch + manual merge model is wrong for "ship multiple times a day." Aggressive Renovate config (`schedule: ["at any time"]` + `automerge` for owned-app images) is closer but still PR-mediated and bound to Renovate's own poll interval (10–30m typical), and noise-prone. Renovate stays the default for everything *not* owned.

- **CI-commits-tag from each app repo into anton.** GitHub Actions builds, pushes, then `git clone anton`, `yq` edits the kustomization.yaml, commits, pushes. Considered seriously and recommended in an earlier turn of the design conversation. Rejected as the strategic answer because it scales linearly with owned-app count: every app repo needs a deploy key for anton, every workflow has the same N-line "edit anton" step, every credential rotation touches N repos. Image-automation centralizes the credential and the logic at the cluster level. CI-commits-tag remains a viable fallback for one-off cases (e.g. an app whose registry the controllers cannot reach) but is not the default.

- **Keel.** Cluster-side image updater that edits Deployments in-cluster directly. Rejected — it fights GitOps because Flux would revert the in-cluster edit. Only sensible in non-GitOps clusters.

- **Argo CD Image Updater.** Rejected by virtue of running Flux, not Argo.

- **`imagePullPolicy: Always` + scheduled `kubectl rollout restart`.** Rejected — fights immutable-tag discipline, doesn't pick up tag changes Flux can see, and trades GitOps reproducibility for a cron job.

- **Harbor as the universal registry for owned apps (including public ones).** Rejected — for the public homepage there is no privacy benefit, GHCR is free and outside the cluster's failure boundary, and Harbor's authenticated-push realm-URL bug (`kubernetes/apps/registries/CLAUDE.md`) is unfixed. GHCR for public sidesteps both. Harbor remains correct for private owned apps where the privacy is the point.

- **GHCR-private + imagePullSecret as the universal registry.** Rejected for private apps because Harbor already runs, is SeaweedFS-backed, gives free in-cluster pulls via Spegel, and is the registry ADR 0015 already justified.

## Consequences

### Accepted costs

- Two new controllers (`image-reflector-controller`, `image-automation-controller`) running in `flux-system`. Memory cost is small — both are similar in shape to the existing `source-controller`. They share the existing Flux deploy key for writing to anton.

- Per-app configuration tax: three small CRs per owned app (`ImageRepository`, `ImagePolicy`, `ImageUpdateAutomation`) plus the `# {"$imagepolicy": ...}` marker on one line of the kustomization.yaml. Authored once per app, no ongoing maintenance unless the tag scheme changes.

- A new commit author (`flux@anton`) appears on `main`. The existing `.github/workflows/flux-local.yaml` runs on PRs only, so it is unaffected; if a future workflow runs `on: push`, gate it with `if: github.actor != 'flux'` to avoid CI loops on bot commits.

- Commit-loop bug class (fluxcd/flux2#3384, image-automation-controller#482) is real but mitigated by the configuration choices above: deterministic `messageTemplate` (no timestamps), `Setters` update strategy, push directly to `main` (not via a separate branch + PR).

- Per-private-registry pull credentials must be wired via ESO (ExternalSecret → 1Password) before image-automation can scan. For Harbor this is a robot account; for GHCR-private it would be a fine-grained PAT. Same credential surface that any private-pull strategy requires — not a new tax.

### Renovate-PR tax

The controllers themselves are bundled inside `flux-instance.spec.values.instance.components`, not separate HelmReleases or images. Renovate's existing flux-operator PRs already cover Flux upgrades; adding two more components to the existing `flux-instance` HelmRelease does **not** introduce a new chart, repository, or PR cadence. **Tax: none.**

### Restore-runbook obligation

The image-automation CRs are stateless and Flux-managed. If the controllers crash or the cluster is rebuilt, Flux reconciles them from Git like every other resource. Per-app registry pull `Secret`s are recreated by ESO from 1Password. **No new restore obligation.**

### Tracking obligation

Wire a `notification-controller` `Provider` + `Alert` for `ImageRepository` and `ImageUpdateAutomation` events on first adoption. This gives a passive deploy heartbeat (Discord/Slack/etc.) so deploys are observable without `git log` archeology. Recommended; not strictly required.

## Follow-ups

- [ ] Add `image-reflector-controller` and `image-automation-controller` to `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml` `components:` list.
- [ ] Author `kubernetes/apps/default/homepage/` as the first concrete adopter (3-file Flux pattern + the three image-automation CRs + GHCR public package). Use the `add-flux-app` skill.
- [ ] Author the matching `nu-sync/homepage` GitHub repo with a Dockerfile and a GitHub Actions workflow whose only job is "build, push to GHCR, done." No cross-repo write to anton.
- [ ] Wire a `notification-controller` `Provider` + `Alert` for `ImageRepository` / `ImageUpdateAutomation` events on first adoption.
- [ ] After homepage is stable, plan the csgoplant migration: Harbor private project, robot accounts, ExternalSecret for the pull token, manifests into `kubernetes/apps/csgoplant/`, retire `csgoplant/scripts/deploy.py`. Capture as a `planner` plan, not inline here.
- [ ] If Renovate ever opens a noisy PR for an owned-app image (race condition between the two writers), add an exclusion `packageRule` for owned-app image patterns to `.renovaterc.json5`. Defer until observed.
