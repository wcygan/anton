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

- [x] `image-reflector-controller` and `image-automation-controller` are listed in `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml` `spec.values.instance.components` and reconciled healthy in-cluster.
- [x] The `nu-sync/homepage` GitHub repo exists with: a `Dockerfile`, a `.github/workflows/build.yaml` that publishes `ghcr.io/nu-sync/homepage:main-<sha>` on push to `main`, and a successful first run.
- [x] The GHCR package `ghcr.io/nu-sync/homepage` is **public** (org packages default to private — flip is explicit).
- [x] `kubernetes/apps/default/homepage/` exists in anton with the standard 3-file Flux pattern, an HTTPRoute attached to the chosen gateway, and the three image-automation CRs. The kustomization.yaml `images:` field carries the `# {"$imagepolicy": "default:homepage:tag"}` marker (deviation from original — see Log 2026-05-02).
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
- 2026-05-01: Phase 1 helmrelease edit drafted — added `image-reflector-controller` and `image-automation-controller` to `flux-instance.spec.values.instance.components`. No additional patches; image controllers don't share the `--concurrent` / 1Gi-memory patches targeted at `(kustomize|helm|source)-controller`. Awaiting commit.
- 2026-05-01: Phase 2 GH Actions workflow authored at `homepage/.github/workflows/build.yaml`. Builds on push to `main`, pushes `ghcr.io/nu-sync/homepage:main-<short-sha>` and a moving `:main`. Uses `GITHUB_TOKEN` with `packages: write` — no PAT, no anton write. Dockerfile (already at `homepage` HEAD `090c77b`) is multi-stage Bun → nginx-unprivileged on **port 8080** — Phase 3 Service must target 8080, not 3000.
- 2026-05-02: Phase 2 build green. User pushed; GH Actions run `25240217367` succeeded in 37s. Homepage main now at `123bfe5`. First image is `ghcr.io/nu-sync/homepage:main-123bfe5`. **Still need GHCR package public-flip** (currently private — `gh api .../packages/container/homepage/versions` returned 403, consistent with the org-default-private state ADR 0024 flagged).
- 2026-05-02: Phase 3+4 manifests authored at `kubernetes/apps/default/homepage/`. Layout: `ks.yaml` (Flux Kustomization, targetNamespace=default) + `app/{kustomization.yaml, deployment.yaml, service.yaml, imagerepository.yaml, imagepolicy.yaml, imageupdateautomation.yaml}`. Plain Deployment+Service (no HelmRelease, no Helm chart). 3-file-pattern hook initially complained mid-batch — false positive during in-progress writes; final state matches `kube-system/tailnet-rbac/` shape. **Decision deviation from plan**: image-automation CRs live in `default` namespace, not `flux-system` — Flux's `targetNamespace: default` would override `metadata.namespace: flux-system` anyway, and public GHCR has no shared-Secret reason to centralize. Marker is `default:homepage:tag` (was `flux-system:homepage:tag` in the plan). `newTag` set to `main-123bfe5` to match the first real GHCR build.
- 2026-05-02: **Still NOT committed**: anton-side helmrelease.yaml change (Phase 1) + the new homepage tree (Phase 3+4) + the not-yet-added `./homepage/ks.yaml` line in `kubernetes/apps/default/kustomization.yaml`. HTTPRoute (Phase 3) deferred — gateway choice (`envoy-internal` vs `envoy-external` per ADR 0023) needs user input. GHCR public-flip blocks any cluster pull regardless.
- 2026-05-02: ADR 0024 + this plan's Tick-1 log committed in `69cff348` ("image automation") by user. Cluster-changing files remain uncommitted; that's intentional pending GHCR public-flip and gateway choice. Validated `kubectl kustomize kubernetes/apps/default/homepage/app` — renders all 5 resources cleanly, image-automation CRs use `image.toolkit.fluxcd.io/v1beta2` (Repository, Policy) and `v1beta1` (UpdateAutomation), tag transformer resolves to `ghcr.io/nu-sync/homepage:main-123bfe5`. `docker pull` of that tag still returns `denied` — package is private, blocking step Phase 2 task "Verify anonymous pull works."
- 2026-05-02: **GHCR public-flip confirmed**. Earlier `docker pull` 401 was misleading — even public GHCR requires a token exchange. Verified via `curl https://ghcr.io/token?service=ghcr.io&scope=repository:nu-sync/homepage:pull` then `GET /v2/nu-sync/homepage/manifests/main-123bfe5` with that Bearer → `200`; tags-list also `200`. Phase 2 anonymous-pull criterion is met. Side note: workflow currently builds `linux/amd64` only — fine for anton (MS-01 / amd64) but a multi-arch enable is one `platforms: linux/amd64,linux/arm64` line in the workflow if ever needed for arm64 pull-throughs / development.
- 2026-05-02: **Gateway choice received from user — `envoy-external` at apex `${SECRET_DOMAIN_THREE}` plus `www.${SECRET_DOMAIN_THREE}`.** This is the explicit ADR 0023 approval that envoy-external requires. Subdomains remain free for future apps. Authored `httproute.yaml` (parentRef envoy-external/https, backendRef homepage:80) and `dnsendpoint.yaml` (apex + www CNAME → `external.${SECRET_DOMAIN_THREE}`, the shared cloudflare-tunnel target). Wildcard cert already covers both apex and `*.${SECRET_DOMAIN_THREE}` per `network/envoy-gateway/app/certificate.yaml` — no cert work needed. Added both to `app/kustomization.yaml` resources list. Added `./homepage/ks.yaml` to `kubernetes/apps/default/kustomization.yaml` so Flux will pick the new app up. Final render via `kubectl kustomize` shows 7 resources (Deployment, Service, HTTPRoute, DNSEndpoint, ImageRepository, ImagePolicy, ImageUpdateAutomation) — all commit-ready.
- 2026-05-02: Committed as `ee53db12` ("feat(homepage): adopt image-automation for nu-sync/homepage", 12 files, 205 insertions). User pushed.
- 2026-05-02: **Rollout BLOCKED on pre-existing flux-operator instability — not caused by this plan.** Forced `kubectl annotate gitrepository/flux-system reconcile.fluxcd.io/requestedAt=...`; GitRepository pulled `ee53db12` cleanly; `flux-instance` Kustomization applied the new components into `FluxInstance.spec.components` (verified — shows all 6 controllers). But `FluxInstance.status.components` still shows only the original 4 — flux-operator never finished applying the new ones. Root cause: `flux-operator-559cb46555-pxlmq` in CrashLoopBackOff, **351 restarts over 20h**, dying every ~75s from liveness-probe timeout (`Readiness probe failed: Get http://10.42.1.64:8081/readyz: context deadline exceeded`, 1s timeout). Resource usage is fine (2m CPU, 200Mi memory vs 100m/64Mi-1Gi limits) — this is a probe-timeout / hang-in-steady-state issue, possibly a v0.46.0 controller bug. Downstream effect: `homepage` Kustomization in `default` namespace exists but `False` — `ImagePolicy/default/homepage dry-run failed: no matches for kind ImagePolicy in version image.toolkit.fluxcd.io/v1beta2` because the image-automation CRDs were never installed (the controllers' install bundles install them). **Plan 0012 is paused pending flux-operator triage.** Suggested next steps: open a separate plan or run `debug-flux-reconciliation` / `anton-cluster-health` skill; consider raising flux-operator probe timeoutSeconds; check upstream issues for v0.46.0. Once flux-operator stays up long enough for one full FluxInstance reconcile, image-automation CRDs install → homepage Kustomization unsticks → rollout completes without further commits from this plan.
- 2026-05-02: **Partial unblock.** flux-operator caught a green window long enough to render the FluxInstance — `image-reflector-controller` and `image-automation-controller` Deployments now `1/1` (85s old) and all 3 image CRDs (`imagerepositories`, `imagepolicies`, `imageupdateautomations`) installed at `v1` and `v1beta2`. flux-operator itself is still in restart-loop (now 353 restarts) but no longer blocks downstream. **New blocker, in our scope: `imageupdateautomation.yaml` was authored with `apiVersion: image.toolkit.fluxcd.io/v1beta1`, which doesn't exist in this CRD's served versions** (only `v1` + `v1beta2`). `homepage` Kustomization was failing the dry-run on it. Fixed: bumped to `v1beta2` (matches the other two CRs we authored). Single-line edit; ready for a follow-up commit.
- 2026-05-02: Fix committed as `2280c7ac`, rebased onto Renovate's `3b92f5aa` (mise tool bump landed on origin meanwhile), pushed as `747358c8`. Forced GitRepository reconcile. **Homepage Kustomization went from `False` to `Applied revision: 747358c8` and the workload came up cleanly.** Final cluster state: `deployment.apps/homepage 1/1 Available`, `pod/homepage-786cccf5b8-vvc8j Running` (78s), `service/homepage ClusterIP 10.43.46.173`, `httproute/homepage hostnames=[nu-sync.net, www.nu-sync.net]`, `dnsendpoint/homepage created`, `imagerepository True (scanned 2 tags)`, `imagepolicy True (resolved to main-123bfe5)`, `imageupdateautomation True (repository up-to-date)`. **External end-to-end verified: `curl https://nu-sync.net/` and `curl https://www.nu-sync.net/` both return `200`** through the chain CF edge → cloudflared tunnel → envoy-external → HTTPRoute → homepage Service → pod. (Required `--resolve`-with-1.1.1.1 from this laptop because of a stale local negative-DNS cache; CF DNS itself is correct.) Acceptance criteria 1–4 all met. Criterion 5 (autonomic-redeploy verification) and criterion 6 (notification Alert) remain open — Phases 5 and 6.

## References

- Related ADRs: [0024](../adrs/0024-adopt-image-automation-for-owned-apps.md) (the decision this plan executes), [0015](../adrs/0015-adopt-harbor-as-the-in-cluster-image-registry.md) (Harbor — relevant for the eventual csgoplant follow-up), [0023](../adrs/0023-shared-cloudflare-tunnel-only.md) (gateway / Cloudflare tunnel constraints if homepage uses `envoy-external`).
- Local app working tree: `/Users/wcygan/Development/homepage`.
- Flux image-automation reference: `https://fluxcd.io/flux/components/image/`, `https://fluxcd.io/flux/guides/image-update/`.
- Existing flux-instance HelmRelease: `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`.
- Existing Receiver (will fire on each image-automation commit to anton): `kubernetes/apps/flux-system/flux-instance/app/receiver.yaml`.
- Skills involved: `add-flux-app` (Phase 3), `expose-service` (Phase 3 HTTPRoute), `observability-integrate` (Phase 6 alternative if Prometheus alerting is preferred over chat webhook), `cluster-intake` was **not** run for this plan because ADR 0024 is concrete-need not learning — flag if this proves wrong.
