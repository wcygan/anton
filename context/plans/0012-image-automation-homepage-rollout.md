---
status: In-progress
opened: 2026-05-01
closed: null
affects: compute
intent: concrete-need
related-adrs: [0024]
review-by: null
---

# 0012 — Roll out Flux image-automation with nu-sync/homepage as first adopter

> Concretely adopt the two-track auto-deploy strategy from ADR 0024 by (a) installing the two image-automation controllers into the existing `flux-instance`, (b) standing up `nu-sync/homepage` as the first GHCR-public owned-app adopter, and (c) verifying the loop: push to `nu-sync/homepage@main` → image-automation commits a tag bump to anton → Flux reconciles → new pod serves the change. csgoplant migration is explicitly **not** in this plan; it will be a separate plan once homepage is stable.

## Goal

End-state: a GitHub repo at `nu-sync/homepage` (already exists at `https://github.com/nu-sync/homepage` per the user's intent — local dev tree at `/Users/wcygan/Development/homepage`) builds a container on every push to `main`, publishes it to `ghcr.io/nu-sync/homepage`, and has its tag automatically bumped in anton by `image-automation-controller`. The homepage workload runs under `kubernetes/apps/default/homepage/` in anton with the standard 3-file Flux pattern plus the three image-automation CRs (`ImageRepository`, `ImagePolicy`, `ImageUpdateAutomation`). A minimal observability hook (notification-controller `Alert` to a chat webhook) gives a passive heartbeat that deploys are firing. From the operator's perspective, "deploy the homepage" reduces to `git push` in the homepage repo; everything else is autonomic.

## Acceptance criteria

- [ ] `image-reflector-controller` and `image-automation-controller` are listed in `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml` `spec.values.instance.components` and reconciled healthy in-cluster.
- [ ] The `nu-sync/homepage` GitHub repo exists with: a `Dockerfile`, a `.github/workflows/build.yaml` that publishes `ghcr.io/nu-sync/homepage:main-<sha>` on push to `main`, and a successful first run.
- [ ] The GHCR package `ghcr.io/nu-sync/homepage` is **public** (org packages default to private — flip is explicit).
- [ ] `kubernetes/apps/default/homepage/` exists in anton with the standard 3-file Flux pattern, an HTTPRoute attached to the chosen gateway, and the three image-automation CRs. The kustomization.yaml `images:` field carries the `# {"$imagepolicy": "flux-system:homepage:tag"}` marker.
- [ ] End-to-end loop verified: a trivial change pushed to `nu-sync/homepage@main` results in an updated pod serving the change, with the only manual step being the original `git push`. Observed time-to-pod is recorded in the Log.
- [ ] A `notification-controller` `Provider` + `Alert` is wired to a chat webhook and a deploy event has been observed firing in the channel.

## Tasks

### Phase 1 — Add the controllers to flux-instance

- [ ] Read `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml` and confirm the current `components:` list.
- [ ] Add `image-reflector-controller` and `image-automation-controller` to `components:`. No other changes to the HelmRelease (no patches needed for default config).
- [ ] Commit, push, let Flux reconcile. Verify both controllers are running: `kubectl -n flux-system get deploy image-reflector-controller image-automation-controller`.
- [ ] Verify metrics endpoint is being scraped by the existing kube-prometheus-stack PodMonitor (`kubectl -n flux-system get podmonitor` should already match — confirm).

### Phase 2 — Stand up nu-sync/homepage

- [ ] Confirm the repo exists at `https://github.com/nu-sync/homepage`. If not, create it with the user's input (this skill does not create GitHub repos).
- [ ] In `/Users/wcygan/Development/homepage`, author a multi-stage `Dockerfile` for the Bun + TanStack Start app. Test locally: `docker build -t homepage:test . && docker run --rm -p 3000:3000 homepage:test`. Verify the page serves.
- [ ] Author `.github/workflows/build.yaml`: on push to `main`, login to GHCR with `GITHUB_TOKEN` (`permissions: { packages: write }`), build, push as `ghcr.io/nu-sync/homepage:main-<short-sha>` (and optionally `:main` as a moving tag). Workflow has **no cluster credentials**, no anton write — building and pushing is its only job.
- [ ] Push to GitHub. Verify the workflow runs green and the package appears under `https://github.com/orgs/nu-sync/packages`.
- [ ] **Flip the package to public.** In `nu-sync` org Packages settings → `homepage` → Package settings → Change visibility → Public. (The "GHCR org-private-by-default" footgun acknowledged in ADR 0024.)
- [ ] Verify anonymous pull works from a laptop: `docker pull ghcr.io/nu-sync/homepage:main-<sha>` without `docker login`.

### Phase 3 — Scaffold homepage in anton

- [ ] Use the `add-flux-app` skill to scaffold `kubernetes/apps/default/homepage/`: `namespace.yaml` (or reuse existing `default` namespace — `default` already has apps under it), `ks.yaml` (Flux Kustomization with `postBuild.substituteFrom: cluster-secrets`, `interval: 1h`), `app/kustomization.yaml`, `app/deployment.yaml`, `app/service.yaml`. **Plain Kubernetes manifests, no HelmRelease** — homepage is too simple to need a chart. Initial `image:` reference is `ghcr.io/nu-sync/homepage:main-<sha>` pinning the most recent build from Phase 2.
- [ ] Use the `expose-service` skill to author `app/httproute.yaml`. Decide gateway: `envoy-internal` for LAN-only, or `envoy-external` (Cloudflare tunnel — requires explicit user approval per ADR 0023). Author the matching `DNSEndpoint` if the hostname is on a non-primary domain.
- [ ] Add the `images:` block to `app/kustomization.yaml`:
  ```yaml
  images:
    - name: ghcr.io/nu-sync/homepage
      newTag: main-<sha>  # {"$imagepolicy": "flux-system:homepage:tag"}
  ```
- [ ] Commit, push. Verify Flux applies the Kustomization, the Deployment comes up, and the pod is `Running` and pulls the image from GHCR.

### Phase 4 — Add the image-automation CRs

- [ ] Author `app/imagerepository.yaml` (`ImageRepository`, `image: ghcr.io/nu-sync/homepage`, `interval: 5m`, no `secretRef` since the package is public).
- [ ] Author `app/imagepolicy.yaml` (`ImagePolicy`, `filterTags.pattern: '^main-(?P<sha>[a-f0-9]+)$'`, `policy.alphabetical: { order: asc }` — works because hex SHAs sort sensibly with the same prefix).
- [ ] Author `app/imageupdateautomation.yaml` (`ImageUpdateAutomation`, `interval: 5m`, `sourceRef: { kind: GitRepository, name: flux-system }`, `update.path: ./kubernetes/apps/default/homepage`, `update.strategy: Setters`, `commit.author: { email: flux@anton, name: flux }`, `commit.messageTemplate: 'chore(homepage): {{range .Updated.Images}}{{println .}}{{end}}'`, `push.branch: main`).
- [ ] Add the three new files to `app/kustomization.yaml` resources list.
- [ ] Commit, push. Verify with `flux get image repository -A`, `flux get image policy -A`, `flux get image update -A`.

### Phase 5 — Verify the end-to-end loop

- [ ] Make a trivial visible change to homepage (e.g. update the page title), commit, push to `main`.
- [ ] Watch GH Actions complete (`gh run watch`).
- [ ] Watch image-reflector pick it up: `flux get image policy homepage -n flux-system --watch`.
- [ ] Watch image-automation commit: `git -C anton log --author=flux --oneline -5` should show a new `chore(homepage): ...` commit shortly after the policy resolves.
- [ ] Watch Flux reconcile and the pod roll: `kubectl -n default rollout status deployment/homepage`.
- [ ] Verify the new content is served. **Record total elapsed time in the Log** (push → pod serving change).

### Phase 6 — Wire notification-controller alert

- [ ] Decide the chat webhook destination (Discord / Slack / Telegram). Provision the webhook (out-of-band).
- [ ] Author `kubernetes/apps/flux-system/flux-instance/app/notifications.yaml` (or sibling) with a `Provider` (referencing a `Secret` for the webhook URL — SOPS-encrypt) and an `Alert` selecting `kind: ImageRepository, name: '*'` and `kind: ImageUpdateAutomation, name: '*'`, `eventSeverity: info`.
- [ ] Commit, push. Trigger another homepage change. Confirm an alert lands in the channel.

### Phase 7 — Document the pattern

- [ ] Update `kubernetes/apps/CLAUDE.md` (or `kubernetes/apps/default/CLAUDE.md` if it exists; create one if not) with a short section on the image-automation pattern, citing ADR 0024 and pointing at homepage as the canonical example.
- [ ] Consider whether `add-flux-app` should grow a flag for "scaffold image-automation CRs too." Defer the actual skill change to a follow-up plan if the pattern is reused for csgoplant. For now, just note the option in the Log.

### Phase 8 — Decide on follow-up

- [ ] Decide whether to immediately open a sibling plan for the csgoplant migration, or pause to gather operational experience first. Either way, do not extend this plan to cover csgoplant — `close done` and start a new plan when ready.

## Log

- 2026-05-01: Plan opened from ADR 0024. First adopter is `nu-sync/homepage` (public, GHCR). csgoplant migration is explicitly out of scope — sibling plan when this one closes. Local working tree for the homepage app is at `/Users/wcygan/Development/homepage`.

## References

- Related ADRs: [0024](../adrs/0024-adopt-image-automation-for-owned-apps.md) (the decision this plan executes), [0015](../adrs/0015-adopt-harbor-as-the-in-cluster-image-registry.md) (Harbor — relevant for the eventual csgoplant follow-up), [0023](../adrs/0023-shared-cloudflare-tunnel-only.md) (gateway / Cloudflare tunnel constraints if homepage uses `envoy-external`).
- Local app working tree: `/Users/wcygan/Development/homepage`.
- Flux image-automation reference: `https://fluxcd.io/flux/components/image/`, `https://fluxcd.io/flux/guides/image-update/`.
- Existing flux-instance HelmRelease: `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`.
- Existing Receiver (will fire on each image-automation commit to anton): `kubernetes/apps/flux-system/flux-instance/app/receiver.yaml`.
- Skills involved: `add-flux-app` (Phase 3), `expose-service` (Phase 3 HTTPRoute), `observability-integrate` (Phase 6 alternative if Prometheus alerting is preferred over chat webhook), `cluster-intake` was **not** run for this plan because ADR 0024 is concrete-need not learning — flag if this proves wrong.
