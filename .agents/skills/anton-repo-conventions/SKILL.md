---
name: anton-repo-conventions
description: Reference for Anton Flux and manifest conventions. Use when Codex writes or reviews Kubernetes manifests, adds a Flux app, chooses OCIRepository versus HelmRepository versus GitRepository, decides between ExternalSecret and SOPS, or checks the 3-file app pattern.
---

# Anton Repo Conventions

Goal: Apply Anton's Flux conventions while editing manifests under `kubernetes/apps/`.

Success means:
- App manifests follow the 3-file pattern.
- CRD consumers and providers satisfy ADR 0027 dependency readiness.
- Helm sources use the best supported Flux source type.
- Secrets use External Secrets Operator or SOPS according to the audience and bootstrap timing.
- Changes match a nearby sibling before introducing a new shape.

Stop when: the manifest shape is explained by this skill, a referenced rule, or a documented exception.

## Workflow

1. Read `kubernetes/apps/AGENTS.md`.
2. Read the nearest sibling app in the same namespace.
3. Load only the reference needed for the decision:
   - `references/three-file-pattern.md` for `ks.yaml`, app directories, and namespace wiring.
   - `references/helmrelease-sources.md` for OCI, HelmRepository, and GitRepository source choices.
   - `references/secrets.md` for SOPS versus ExternalSecret.
4. Apply the convention with the smallest manifest change.
5. Run `python3 scripts/validate-flux-contract.py`, then validate YAML and
   secret handling before summarizing.

## Core Rules

Use this app layout unless a namespace-level `AGENTS.md` gives a narrower pattern:

```text
kubernetes/apps/<namespace>/
  namespace.yaml
  kustomization.yaml
  <app>/
    ks.yaml
    app/
      kustomization.yaml
      helmrelease.yaml + one chart source
        | raw manifests, components, patches, or generators
```

Use `postBuild.substituteFrom` with `cluster-secrets` when a manifest references cluster substitution variables.

Prefer ExternalSecret for application secrets. Use SOPS for bootstrap and infrastructure secrets that must exist before ESO.

Prefer OCIRepository for Helm charts when upstream publishes OCI. Use HelmRepository when upstream only ships an HTTP Helm repo. Use GitRepository for charts stored in Git. For raw mode, list manifests, components, patches, or generators directly in `app/kustomization.yaml`; do not add an artificial HelmRelease.

Before finishing `ks.yaml`, inspect the app's authored kinds. ADR 0027 requires
CRD consumers to depend on their platform Kustomization and providers to signal
readiness. The executable mapping lives in
`scripts/lib/flux_application_contract.py`; use the validator instead of
copying that mapping into this skill.

## Validation

Run the narrow check that matches the edited files:

```sh
python3 scripts/validate-flux-contract.py
yq . kubernetes/apps/<namespace>/<app>/ks.yaml
yq . kubernetes/apps/<namespace>/<app>/app/kustomization.yaml
find . -name '*.sops.*' -not -name '.sops.yaml' -not -path './.private/*' -exec sops filestatus {} \;
```
