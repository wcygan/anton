---
name: add-flux-app
description: Scaffold a new Helm or raw Kustomize Flux app for Anton. Use to add an app, add a chart, add a raw manifest app, create a namespace, or create an ExternalSecret. Stops after repository validation and an explicit Git/rollout handoff.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Add a Flux app

Task skill that scaffolds the 3-file Flux pattern for a new application in `kubernetes/apps/<namespace>/<app>/`. For the WHY behind every field — the 3-file pattern, postBuild substitution, OCI vs Helm vs Git sources, the SOPS vs ExternalSecret decision — read the `anton-repo-conventions` skill first; this skill assumes you already know it.

## What this skill produces

Field reference for every file's shape: `anton-repo-conventions` skill.

| File | Path |
| --- | --- |
| Flux Kustomization (Tier 1) | `kubernetes/apps/<ns>/<app>/ks.yaml` |
| Plain Kustomize (Tier 2) | `kubernetes/apps/<ns>/<app>/app/kustomization.yaml` |
| Helm resources (Tier 3, Helm mode) | `app/helmrelease.yaml` plus exactly one chart source |
| Raw resources (Tier 3, raw mode) | manifests, components, patches, or generators listed by `app/kustomization.yaml` |
| Optional Namespace + namespace kustomization | `kubernetes/apps/<ns>/namespace.yaml` |
| Optional ExternalSecret | `kubernetes/apps/<ns>/<app>/app/externalsecret.yaml` |

## Workflow A — add an app to an existing namespace

1. **Pick the namespace.** Confirm it already exists: `ls kubernetes/apps/<ns>/`. If not, jump to Workflow B.
2. **Choose Helm or raw mode.** Match the closest sibling. For Helm, verify the chart first with `mise exec -- helm search repo <repo>/<chart> --versions | head -5` or `mise exec -- crane ls ghcr.io/<org>/charts/<chart>`. For raw mode, identify the exact manifests, components, patches, or generators that `app/kustomization.yaml` will own.
3. **Create the app directory:** `mkdir -p kubernetes/apps/<ns>/<app>/app`
4. **Author the app shape directly.** Every app gets `ks.yaml` and `app/kustomization.yaml`. Helm mode adds `app/helmrelease.yaml` and exactly one chart source. Raw mode lists at least one manifest, component, patch, or generator and does not invent a HelmRelease. Use `anton-repo-conventions` for the field contract and copy the closest in-tree sibling.
5. **Register the app** in the namespace kustomization. Add one line:
   ```sh
   $EDITOR kubernetes/apps/<ns>/kustomization.yaml
   # add: - ./<app>/ks.yaml
   ```
   Apps are NOT auto-discovered. Skipping this means Flux silently never deploys the app.
6. **Validate dependency readiness:** run
   `python3 scripts/validate-flux-contract.py`. If the app authors a custom
   resource, add the ADR 0027 `dependsOn` edge reported by the validator; if it
   is a provider, add `wait: true`, `healthChecks`, or `healthCheckExprs`.
7. **If any `*.sops.*` files:** `mise exec -- sops -e -i <file>` to encrypt in place. Verify with `mise exec -- sops filestatus <file>` → `encrypted`.
8. **Stop after repository validation.** Report the validated diff and hand off commit, push, and Flux reconciliation as separate operator actions. Perform none of them unless the user explicitly authorizes that boundary.

## Workflow B — add an app in a new namespace

1. **Create the namespace dir:** `mkdir -p kubernetes/apps/<ns>`
2. **Author `kubernetes/apps/<ns>/namespace.yaml` directly.** The annotation `kustomize.toolkit.fluxcd.io/prune: disabled` is required — it stops Flux from deleting the namespace. Copy the shape from a neighbor namespace.
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

OCIRepository is the default. Two alternatives, only when the chart is not on OCI:

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
1. Hand off creation of the item in the `anton` 1Password vault unless that external mutation was explicitly authorized. Field names are case-sensitive.
2. Author `app/externalsecret.yaml` directly. Template shape and field-mapping rules: `anton-repo-conventions/references/secrets.md`. Copy from an in-tree ExternalSecret (e.g. `kubernetes/apps/network/cloudflare-tunnel/app/externalsecret.yaml`).
3. Add `- ./externalsecret.yaml` to the app's `kustomization.yaml`.
4. No encryption step. Verify after deploy:
   ```sh
   mise exec -- kubectl get externalsecret -n <ns> <name>
   mise exec -- kubectl get secret        -n <ns> <name>
   mise exec -- kubectl describe externalsecret -n <ns> <name> | grep -A5 Status:
   ```

**Path 2 — SOPS Secret (only for static infra credentials that must exist before ESO).**
1. Author `app/secret.sops.yaml` in plaintext with `data` or `stringData`.
2. Encrypt in place: `mise exec -- sops -e -i app/secret.sops.yaml`.
3. Verify: `SOPS_AGE_KEY_FILE=./age.key mise exec -- sops filestatus app/secret.sops.yaml` → `encrypted`.
4. Add `- ./secret.sops.yaml` to the app's `kustomization.yaml`.

Full templates and field-mapping rules: `anton-repo-conventions/references/secrets.md`.

## Variant — the app needs an HTTPRoute

That belongs to a different skill. Use `expose-service` for HTTPRoute, gateway choice, secondary-domain DNSEndpoint, and certificate sourcing.

## Pre-commit checklist

- [ ] `python3 scripts/validate-flux-contract.py` passes
- [ ] App is listed in `kubernetes/apps/<ns>/kustomization.yaml`
- [ ] `ks.yaml` has `postBuild.substituteFrom: [{name: cluster-secrets, kind: Secret}]` if the app uses any `${VAR}`
- [ ] Namespace kustomization includes `components: [../../components/sops]`
- [ ] Helm mode has exactly one chart source; raw mode lists at least one manifest, component, patch, or generator
- [ ] In Helm mode, `OCIRepository.metadata.name` matches `HelmRelease.spec.chartRef.name`
- [ ] All `*.sops.*` files show `encrypted`: `mise exec -- find . -name '*.sops.*' -exec sops filestatus {} \;`
- [ ] Commit, push, live Secret creation, and Flux reconciliation are named as unperformed operator handoffs unless separately authorized

## Related skills

- Pattern reference (the WHY for every field) → `anton-repo-conventions`
- Exposing the app on a gateway → `expose-service`
- App not deploying after commit → `debug-flux-reconciliation`
