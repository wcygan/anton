---
name: External GitRepository + inner Flux Kustomization with patches
description: How to install an upstream manifest (no Helm chart) from a third-party GitHub repo via Flux, using spec.patches for namespace moves and image pins
type: reference
---

When an upstream project ships a plain YAML manifest (no usable Helm chart) and you want to pin a version + relocate namespaces, the anton pattern is:

1. `ks.yaml` — standard outer Flux Kustomization under `kubernetes/apps/<ns>/<app>/`, `path: ./kubernetes/apps/<ns>/<app>/app`, sourceRef to `flux-system/flux-system`.
2. `app/kustomization.yaml` — plain kustomize listing `./gitrepository.yaml` and `./flux-kustomization.yaml`.
3. `app/gitrepository.yaml` — `source.toolkit.fluxcd.io/v1 GitRepository` pointing at the external repo with `ref.tag`, an `ignore:` block pinning to only the manifest(s) you need, and a `# renovate: datasource=github-releases depName=<owner>/<repo>` comment above the tag.
4. `app/flux-kustomization.yaml` — inner `kustomize.toolkit.fluxcd.io/v1 Kustomization` (NOT plain kustomize — plain kustomize cannot consume a Flux GitRepository source). `path:` is the subdirectory inside the upstream repo; use `spec.patches` (6902-style JSON patch ops) for namespace moves, image pins, and RoleBinding subject fixups.

Key gotchas:
- Plain kustomize `kustomization.yaml` has no way to reference a Flux `GitRepository` — you must use an inner Flux `Kustomization` with `sourceRef.kind: GitRepository`.
- Renovate needs two annotations if you both pin a git tag AND pin an image tag inside a patch: one `# renovate: datasource=github-releases` on the `tag:`, one `# renovate: datasource=docker` on the image `value:`.
- The first Write of the `app/` directory trips the `check_3_file_pattern.py` hook mid-sequence (after ks.yaml, before app/kustomization.yaml). Write order is fine — the hook runs after each file; ignore the transient error if you can see the final directory is complete.
- First of its kind in anton (2026-04-19): previously all `GitRepository` resources pointed at `flux-system` self. Exemplar: `kubernetes/apps/network/multus/`.

When NOT to use this pattern: if the upstream publishes a Helm chart (OCI or classic), use `HelmRelease` + `OCIRepository`/`HelmRepository` per the standard 3-file pattern.
