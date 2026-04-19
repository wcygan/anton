---
name: anton-repo-conventions
description: Reference for Anton's Flux conventions — the 3-file pattern, ks.yaml shape, HelmRelease sources (OCI/Helm/Git), postBuild substitution from cluster-secrets, and SOPS vs ExternalSecret decision. Use when writing manifests or picking a secret store.
allowed-tools: Read, Grep, Glob
---

# Anton repo conventions

Reference skill. Read `kubernetes/apps/kube-system/reloader/` first — it is the canonical exemplar for the 3-file pattern.

> **Post-tidy history note.** Older commits, ADRs, and plans reference `task configure` or `task template:*`. Those were archived on 2026-04-19 via `task template:tidy` (commit `50abae87`). `kubernetes/`, `talos/`, and `bootstrap/` are now hand-edited; `*.sops.*` files are round-tripped with `sops <file>` (transparent edit) or `sops -e -i <file>` (encrypt in place). No render step, no `task configure`.

## Directory layout

```
kubernetes/
├── apps/<namespace>/
│   ├── namespace.yaml              # Namespace, prune: disabled
│   ├── kustomization.yaml          # Lists ./<app>/ks.yaml + ../../components/sops
│   └── <app>/
│       ├── ks.yaml                 # Flux Kustomization (Tier 1)
│       └── app/
│           ├── kustomization.yaml  # Plain Kustomize (Tier 2)
│           ├── helmrelease.yaml    # Resources (Tier 3)
│           └── ocirepository.yaml  # OR helmrepository.yaml
├── components/sops/                # Kustomize Component → cluster-secrets
└── flux/cluster/ks.yaml            # Top-level Flux Kustomization
```

Apps are NOT auto-discovered. Every namespace `kustomization.yaml` must list `./<app>/ks.yaml` explicitly. Namespaces carry `kustomize.toolkit.fluxcd.io/prune: disabled` so Flux never deletes them.

## The 3-file pattern

Every app has exactly three tiers, named identically to the app:

| Tier | File | Kind |
| --- | --- | --- |
| 1 | `<ns>/<app>/ks.yaml` | `kustomize.toolkit.fluxcd.io/v1` Kustomization |
| 2 | `<ns>/<app>/app/kustomization.yaml` | `kustomize.config.k8s.io/v1beta1` Kustomization |
| 3 | `<ns>/<app>/app/{helmrelease,ocirepository,…}.yaml` | the actual resources |

Full annotated example: see `references/three-file-pattern.md`.

## ks.yaml required shape

| Field | Value |
| --- | --- |
| `metadata.name` | matches app directory |
| `spec.interval` | `1h` |
| `spec.path` | `./kubernetes/apps/<ns>/<app>/app` (must end in `/app`) |
| `spec.prune` | `true` |
| `spec.wait` | `false` (use `true` only for critical services) |
| `spec.targetNamespace` | matches namespace dir |
| `spec.sourceRef` | `GitRepository flux-system/flux-system` |
| `spec.postBuild.substituteFrom` | `[{name: cluster-secrets, kind: Secret}]` — required if the app uses any `${VAR}` |

Defaults inherited from `kubernetes/flux/cluster/ks.yaml` (do NOT repeat per app): `decryption.provider: sops`, HelmRelease `install.crds: CreateReplace`, retry/remediation policies, `cleanupOnFail`.

## HelmRelease chart sources

Three source kinds, prefer OCIRepository:

| Source | Use when | Example |
| --- | --- | --- |
| `OCIRepository` (preferred) | chart is published to an OCI registry (most modern charts) | `oci://ghcr.io/stakater/charts/reloader` |
| `HelmRepository` | classic Helm repo without OCI | harbor, cloudnative-pg |
| `GitRepository` | chart lives in a git tree (rare) | a fork, or a chart not yet released |

`OCIRepository.metadata.name` MUST match `HelmRelease.spec.chartRef.name`. Full templates plus the values vs valuesFrom rules: see `references/helmrelease-sources.md`.

## Cluster-secrets and postBuild substitution

`kubernetes/components/sops/cluster-secrets.sops.yaml` is a SOPS-encrypted Secret named `cluster-secrets` with keys like `SECRET_DOMAIN`, `SECRET_DOMAIN_TWO`, `CLUSTER_POD_CIDR`. Every namespace pulls it in via `components: [../../components/sops]`. Every `ks.yaml` references it via `postBuild.substituteFrom`, so `${SECRET_DOMAIN}` is interpolated at Flux apply time.

Pipeline order (post-tidy — no render step):

1. **Flux postBuild** resolves `${VAR}` at reconcile from `cluster-secrets` (the `${VAR}` is a hand-written literal in the manifest)
2. **Helm templating** resolves `{{ .Values.* }}` during install

Common failure: a literal `${SECRET_DOMAIN}` appearing in a deployed object → forgot `postBuild.substituteFrom` in `ks.yaml`, or the namespace kustomization is missing `../../components/sops`.

## SOPS vs ExternalSecret decision

| Choose | When | Where it lives |
| --- | --- | --- |
| **SOPS Secret** (`*.sops.yaml`) | static, infrastructure-only, rarely rotates, must be in git for bootstrap | `kubernetes/apps/<ns>/<app>/app/secret.sops.yaml`, encrypted in place via `sops -e -i <file>` |
| **ExternalSecret** (ESO → 1Password, preferred) | rotating credentials, app secrets, large payloads, anything sourced from 1Password | `kubernetes/apps/<ns>/<app>/app/externalsecret.yaml`, no encryption step |

Both share the same Age recipient (defined in `.sops.yaml`); ESO uses the `onepassword-connect` `ClusterSecretStore` against the `anton` 1Password vault. Full templates and field-mapping rules: see `references/secrets.md`.

`cluster-secrets.sops.yaml` itself stays SOPS — it must be in git so Flux can substitute from it before any app is up.

## Pre-commit checklist

- [ ] App is listed in `kubernetes/apps/<ns>/kustomization.yaml`
- [ ] `ks.yaml` has `postBuild.substituteFrom` if the app uses any `${VAR}`
- [ ] Namespace kustomization includes `components: [../../components/sops]`
- [ ] `OCIRepository.metadata.name` matches `HelmRelease.spec.chartRef.name`
- [ ] No plaintext secrets: `find . -name '*.sops.*' -not -path './.private/*' -exec sops filestatus {} \;` all report `encrypted`

## Related skills

- Scaffolding a new app from these conventions → `add-flux-app`
- Exposing a service through a gateway → `expose-service`
- Triaging a stuck Flux sync → `debug-flux-reconciliation`
- One-time cluster bootstrap → see `bootstrap/CLAUDE.md`
