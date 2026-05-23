# Onboard mode — first-time scaffold for a new owned app

Triggered when `flux get image repository <app-name> -A` returns no rows. The app exists somewhere as source code and (probably) a GitHub repo; the goal is to land it in anton with the full image-automation pattern, end at "https URL serves 200."

This mode is interview-driven and pauses on each user-action milestone (commits, pushes, GHCR public-flip, gateway approval). The skill doesn't perform actions outside the operator's control — it surfaces them clearly.

## Pre-flight interview

Ask, in order, only what isn't already known from context:

1. **App repo path on disk** — local working tree (e.g. `/Users/wcygan/Development/<repo>`). Used to author Dockerfile + workflow.
2. **GitHub repo slug** — `<owner>/<repo>` (e.g. `nu-sync/<repo>`). Used to derive the GHCR image ref `ghcr.io/<owner>/<repo>`.
3. **Registry** — GHCR (default for public) or Harbor (`192.168.1.106/<project>/<name>` for private). Per ADR 0024.
4. **Target namespace in anton** — usually `default` for simple apps; can be a new one. Check `kubectl get ns` for current list.
5. **Gateway choice** — `envoy-internal`, `envoy-external`, or "no ingress yet."
   - `envoy-external` requires explicit ADR 0023 approval — confirm with operator before scaffolding.
6. **Hostname(s)** — required if any gateway chosen. Use repo-convention `${SECRET_DOMAIN_*}` placeholders, never literals (per CLAUDE.md hard rule). Look up which `SECRET_DOMAIN_*` corresponds to the operator's domain via memory or by asking.
7. **Tag scheme** — `main-<sha>` (default for owned apps; works with the skill's regex), or semver, or both. Affects the `ImagePolicy.spec.filterTags`.

## Phase A — App-side scaffold

### A1. Dockerfile (skip if exists)

Read `<app-repo>/Dockerfile`. If it exists, skip. If not, generate one based on the stack:

- **Bun + TanStack Start (static)**: multi-stage Bun build → nginx-unprivileged on 8080. Reference: `/Users/wcygan/Development/homepage/Dockerfile`.
- **Node app (server)**: multi-stage Node build → distroless on 3000.
- **Go**: scratch + static binary.
- **Other**: ask the operator and use a sensible default.

### A2. GH Actions workflow

Author `<app-repo>/.github/workflows/build.yaml`. Reference shape: `/Users/wcygan/Development/homepage/.github/workflows/build.yaml`. Key constraints:

- Trigger: `push: branches: [main]` plus `workflow_dispatch: {}`
- `permissions: { contents: read, packages: write }`
- Login to `ghcr.io` with `${{ secrets.GITHUB_TOKEN }}` — no PAT, no anton write access
- Tag with `main-${SHORT_SHA}` (and a moving `:main` if desired)
- Use `docker/build-push-action@v6` with `cache-from`/`cache-to: type=gha`
- For Harbor private: swap login to Harbor robot creds (out-of-scope for this skill — refer to ADR 0024 csgoplant pattern)

### A3. Stop and surface user action

Before any commits, present:

> The app-side files are ready in `<repo>`. Please:
> 1. Commit and push these files (you own this repo's history).
> 2. Watch the workflow at `https://github.com/<owner>/<repo>/actions` succeed.
> 3. **Flip the GHCR package public**: `https://github.com/<owner>/<repo>/pkgs/container/<repo>/settings` → Danger Zone → Change visibility → Public. (Required for in-cluster anonymous pulls; org packages default to private.)
> 4. Tell me when those three are done.

Wait for confirmation before continuing.

### A4. Verify the image is publicly pullable

```sh
TOKEN=$(curl -s "https://ghcr.io/token?service=ghcr.io&scope=repository:<owner>/<repo>:pull" | jq -r .token)
curl -sI -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json" \
  -o /dev/null -w 'manifest=%{http_code}\n' \
  "https://ghcr.io/v2/<owner>/<repo>/manifests/main-<sha>"
```

Expect 200. If 401/403 → the package is still private, ask the operator to flip it.

For Harbor: `curl http://192.168.1.106/v2/<project>/<name>/tags/list` (cluster-internal — run in a debug pod or skip).

## Phase B — Anton-side scaffold

### B1. Determine the current GHCR tag to pin

The anton manifests need an initial image reference. Use the latest tag from the registry:

```sh
crane ls "ghcr.io/<owner>/<repo>" 2>/dev/null | grep -E '^main-[a-f0-9]+$' | sort | tail -1
# or fetch via /v2/.../tags/list and pick the last main-* tag
```

Note the result as `INITIAL_TAG` (e.g. `main-123bfe5`).

### B2. Generate anton manifests

Layout under `kubernetes/apps/<ns>/<app>/`:

```
<app>/
├── ks.yaml                      Flux Kustomization (postBuild substitution from cluster-secrets)
└── app/
    ├── kustomization.yaml       Lists resources + the images: setter block with $imagepolicy marker
    ├── deployment.yaml          Plain Deployment, image: <registry>/<owner>/<repo>:<INITIAL_TAG>
    ├── service.yaml             ClusterIP on port 80 → containerPort
    ├── httproute.yaml           (only if gateway chosen) parentRef to envoy-internal/external
    ├── dnsendpoint.yaml         (only if envoy-external on a non-primary domain) CNAMEs to external.<domain>
    ├── imagerepository.yaml     image.toolkit.fluxcd.io/v1beta2 — interval 5m
    ├── imagepolicy.yaml         image.toolkit.fluxcd.io/v1beta2 — filterTags + alphabetical asc
    └── imageupdateautomation.yaml  image.toolkit.fluxcd.io/v1beta2 (NOT v1beta1 — see plan 0012)
```

Reference all of these at `/Users/wcygan/Development/anton/kubernetes/apps/default/homepage/` — copy and adapt.

Critical details (each one is a recorded pitfall from plan 0012):

- **`apiVersion: image.toolkit.fluxcd.io/v1beta2`** for all three image CRs. NOT `v1beta1` — the CRD only serves `v1` and `v1beta2`.
- **`# {"$imagepolicy": "<ns>:<app>:tag"}`** marker on the `kustomization.yaml`'s `images:` field. Namespace prefix matches where the ImagePolicy lives, which is the same namespace as the app (because `targetNamespace` overrides `metadata.namespace: flux-system`).
- **Service port 80 → containerPort matches Dockerfile's `EXPOSE`** (8080 for nginx-unprivileged, 3000 for typical Node, etc.). Read the Dockerfile to confirm.
- **HTTPRoute backendRef port = Service port (80)**, NOT the container port.
- **`SECRET_DOMAIN_*` placeholders only** in HTTPRoute hostnames and DNSEndpoint targets. Look up the right index per the operator's domain memory.

### B3. Wire into the parent kustomization

Edit `kubernetes/apps/<ns>/kustomization.yaml`:

```yaml
resources:
  - ./namespace.yaml
  - ./<existing>/ks.yaml
  - ./<app>/ks.yaml      # ← add this line
```

If the namespace doesn't exist in `kubernetes/apps/`, scaffold it first (delegate to `add-flux-app`).

### B4. Validate before commit

```sh
kubectl kustomize kubernetes/apps/<ns>/<app>/app 2>&1 | head -100
```

Expect all resources to render cleanly. If errors, fix and re-validate.

### B5. Stop and surface the diff

Show the operator the full set of new/modified files. List acceptance gates that need their explicit "go":

- Cross-repo writes for image-automation? (None — we use the cluster's existing flux-system deploy key.)
- `envoy-external` chosen? (If yes, confirm ADR 0023 approval was given.)

Ask: "Commit + push? (yes/no)"

### B6. Commit and push

If yes, stage the specific files (no `git add -A`):

```sh
git add kubernetes/apps/<ns>/kustomization.yaml \
        kubernetes/apps/<ns>/<app>/...

git commit -m "$(cat <<EOF
feat(<app>): adopt image-automation per ADR 0024

- Scaffold default/<app> (Deployment + Service + HTTPRoute + DNSEndpoint)
- Wire ImageRepository + ImagePolicy + ImageUpdateAutomation against
  <registry>/<owner>/<repo> with main-<sha> tag policy
- Initial image: <INITIAL_TAG>
EOF
)"
```

`git push origin main` — explicitly authorized only by the user, never amend.

## Phase C — Watch the first reconcile

### C1. Force the chain

The webhook will fire on push, but force to skip any latency:

```sh
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization <app> -n <ns>
```

### C2. Watch resources appear

```sh
# Should go from NotFound → Ready
flux get kustomization <app> -n <ns> --watch
# Once Ready, the workload exists:
kubectl get deploy,pod,svc,httproute,dnsendpoint -n <ns> -l app.kubernetes.io/name=<app>
flux get image repository,policy,update -n <ns>
```

### C3. Watch rollout

```sh
kubectl rollout status deployment/<app> -n <ns> --timeout=3m
```

### C4. Verify HTTP 200 (if HTTPRoute scaffolded)

Same `--resolve`-based curl as redeploy mode (see [redeploy](redeploy.md) Step 4). Use 1.1.1.1 to bypass local DNS cache.

### C5. Report

```
✅ <app> onboarded and serving
   anton commit:   <sha>
   manifests:      kubernetes/apps/<ns>/<app>/  (N files)
   first image:    <registry>/<owner>/<repo>:<INITIAL_TAG>
   pod:            <pod-name> Running
   url:            https://<host>/  →  200
   total elapsed:  <N>s  (commit → 200)
   next step:      push a code change to <repo>; loop will redeploy autonomically
                   verify with /deploy-owned-app <app>
```

## Stop conditions specific to onboard mode

In addition to the redeploy-mode failures (see [troubleshoot](troubleshoot.md)):

- **App repo missing required pieces** → ask the operator to add them; do not invent business logic.
- **GHCR pull returns 401 after the user said "flipped public"** → one more click is needed; surface the exact path.
- **`envoy-external` approval not given** → fall back to `envoy-internal` or "no ingress yet" rather than committing without approval.
- **Operator declines the commit** → stop cleanly; the manifests are in working tree; they can review/edit and commit themselves later.
- **`SECRET_DOMAIN_*` placeholder unknown for the requested domain** → ask the operator; never commit literal domains.
