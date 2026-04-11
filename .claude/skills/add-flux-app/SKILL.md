---
name: add-flux-app
description: Scaffold a new Flux app for Anton. Use to add an app, deploy app, new helm chart, new namespace, scaffold flux app, or create external secret. Generates ks.yaml with postBuild, HelmRelease, OCIRepository, and optional ExternalSecret.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Add a Flux app

Task skill that scaffolds the 3-file Flux pattern for a new application in `kubernetes/apps/<namespace>/<app>/`. For the WHY behind every field — the 3-file pattern, postBuild substitution, OCI vs Helm vs Git sources, the SOPS vs ExternalSecret decision — read the `anton-repo-conventions` skill first; this skill assumes you already know it.

## What this skill produces

| File | Path | From template |
| --- | --- | --- |
| Flux Kustomization (Tier 1) | `kubernetes/apps/<ns>/<app>/ks.yaml` | `templates/ks.yaml.template` |
| Plain Kustomize (Tier 2) | `kubernetes/apps/<ns>/<app>/app/kustomization.yaml` | `templates/kustomization.yaml.template` |
| HelmRelease (Tier 3) | `kubernetes/apps/<ns>/<app>/app/helmrelease.yaml` | `templates/helmrelease.yaml.template` |
| OCIRepository (chart source) | `kubernetes/apps/<ns>/<app>/app/ocirepository.yaml` | `templates/ocirepository.yaml.template` |
| Optional Namespace + namespace kustomization | `kubernetes/apps/<ns>/namespace.yaml` | `templates/namespace.yaml.template` |
| Optional ExternalSecret | `kubernetes/apps/<ns>/<app>/app/externalsecret.yaml` | `templates/externalsecret.yaml.template` |

## Workflow A — add an app to an existing namespace

1. **Pick the namespace.** Confirm it already exists: `ls kubernetes/apps/<ns>/`. If not, jump to Workflow B.
2. **Check the chart exists** before scaffolding: `helm search repo <repo>/<chart> --versions | head -5` for HelmRepository charts; for OCI, look at the registry directly (`crane ls ghcr.io/<org>/charts/<chart>` or just visit the URL).
3. **Create the app directory:** `mkdir -p kubernetes/apps/<ns>/<app>/app`
4. **Render the four core files** by reading `templates/{ks,kustomization,helmrelease,ocirepository}.yaml.template` and substituting:
   - `{{APP_NAME}}` → e.g. `my-app`
   - `{{NAMESPACE}}` → e.g. `monitoring`
   - `{{CHART_URL}}` → e.g. `oci://ghcr.io/example/charts/my-app`
   - `{{CHART_TAG}}` → pinned semver, e.g. `1.2.3`
5. **Register the app** in the namespace kustomization. Add one line:
   ```sh
   $EDITOR kubernetes/apps/<ns>/kustomization.yaml
   # add: - ./<app>/ks.yaml
   ```
   Apps are NOT auto-discovered. Skipping this means Flux silently never deploys the app.
6. **Validate and (if any `*.sops.*` files) encrypt:** `task configure`
7. **Commit and push.** Wait for Flux poll, or force with `task reconcile`.
8. **Verify:**
   ```sh
   flux get ks -A | rg <app>
   flux get hr -A | rg <app>
   ```

## Workflow B — add an app in a new namespace

1. **Create the namespace dir:** `mkdir -p kubernetes/apps/<ns>`
2. **Render `kubernetes/apps/<ns>/namespace.yaml`** from `templates/namespace.yaml.template`. The annotation `kustomize.toolkit.fluxcd.io/prune: disabled` must stay — it stops Flux from deleting the namespace.
3. **Create the namespace kustomization** at `kubernetes/apps/<ns>/kustomization.yaml`:
   ```yaml
   ---
   apiVersion: kustomize.config.k8s.io/v1beta1
   kind: Kustomization
   resources:
     - ./namespace.yaml
     # apps go here as you add them
   components:
     - ../../components/sops
   ```
   The `components: [../../components/sops]` line is mandatory — it injects `cluster-secrets` so `${VAR}` substitution works for every app in this namespace.
4. **Continue from step 2 of Workflow A** to add the first app.

## Variant — chart source other than OCIRepository

OCIRepository is the default and what `templates/ocirepository.yaml.template` produces. Two alternatives, only when the chart is not on OCI:

**HelmRepository (classic Helm repo).** Replace the OCIRepository file with a HelmRepository, and replace the HelmRelease's `chartRef:` block with `chart.spec.sourceRef`:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: {{APP_NAME}}
spec:
  interval: 15m
  url: https://example.helm.repo
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: {{APP_NAME}}
spec:
  interval: 1h
  chart:
    spec:
      chart: {{CHART_NAME}}
      version: {{CHART_VERSION}}
      sourceRef:
        kind: HelmRepository
        name: {{APP_NAME}}
  values: {}
```

**GitRepository (rare).** Use only when the chart lives in a git tree (a fork or unreleased chart). See `anton-repo-conventions/references/helmrelease-sources.md` for the exact shape.

## Variant — the app needs a secret

Pick one path; do not mix for the same secret.

**Path 1 — ExternalSecret (default for new apps, pulls from 1Password).**
1. Add the item to the `anton` 1Password vault. Field names are case-sensitive.
2. Render `templates/externalsecret.yaml.template`, substituting `{{SECRET_NAME}}`, `{{NAMESPACE}}`, `{{ONEPASSWORD_ITEM}}`, `{{ONEPASSWORD_FIELD}}`, `{{K8S_SECRET_KEY}}`.
3. Add `- ./externalsecret.yaml` to the app's `kustomization.yaml`.
4. No encryption step. Verify after deploy:
   ```sh
   kubectl get externalsecret -n <ns> <name>
   kubectl get secret        -n <ns> <name>
   kubectl describe externalsecret -n <ns> <name> | grep -A5 Status:
   ```

**Path 2 — SOPS Secret (only for static infra credentials that must exist before ESO).**
1. Author `app/secret.sops.yaml` in plaintext with `data` or `stringData`.
2. Run `task configure` — it encrypts in place via SOPS+Age.
3. Verify: `SOPS_AGE_KEY_FILE=./age.key sops filestatus app/secret.sops.yaml` → `encrypted`.
4. Add `- ./secret.sops.yaml` to the app's `kustomization.yaml`.

Full templates and field-mapping rules: `anton-repo-conventions/references/secrets.md`.

## Variant — the app needs an HTTPRoute

That belongs to a different skill. Use `expose-service` for HTTPRoute, gateway choice, secondary-domain DNSEndpoint, and certificate sourcing.

## Pre-commit checklist

- [ ] App is listed in `kubernetes/apps/<ns>/kustomization.yaml`
- [ ] `ks.yaml` has `postBuild.substituteFrom: [{name: cluster-secrets, kind: Secret}]` if the app uses any `${VAR}`
- [ ] Namespace kustomization includes `components: [../../components/sops]`
- [ ] `OCIRepository.metadata.name` matches `HelmRelease.spec.chartRef.name`
- [ ] `task configure` ran without errors (validates schemas + encrypts SOPS files)
- [ ] No plaintext secrets: `find . -name '*.sops.*' -exec sops filestatus {} \;` all `encrypted`
- [ ] `flux get ks -A | rg <app>` and `flux get hr -A | rg <app>` both show `Ready=True` after `task reconcile`

## Related skills

- Pattern reference (the WHY for every field) → `anton-repo-conventions`
- Exposing the app on a gateway → `expose-service`
- App not deploying after commit → `debug-flux-reconciliation`
