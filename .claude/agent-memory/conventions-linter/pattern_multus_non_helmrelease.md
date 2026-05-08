---
name: Multus + Whereabouts use GitRepository + spec.patches (not HelmRelease)
description: Apps deployed via GitRepository + Flux Kustomization spec.patches do not use the OCI/HelmRepository pattern; 3-file lint hook accepts this deviation
type: feedback
---

**Rule:** The 3-file pattern allows `<app>/ks.yaml` to reference a `GitRepository` instead of an `OCIRepository`/`HelmRepository`. Multus and Whereabouts use this because the upstream charts are inadequate for thick-mode CNI, so the deployments are pulled via GitRepository and modified via spec.patches.

**Why:** Thick-mode Multus and Whereabouts require custom DaemonSet patches that upstream Helm charts do not expose as values (or have no usable chart for thick mode at all). Pulling raw YAML and patching is more maintainable than forking or trying to force upstream chart shapes. This is a load-bearing pattern in anton (ADR 0017 / plan 0004).

**How to apply:** When linting a GitRepository-based app:
- Do NOT expect `helmrelease.yaml` or `ocirepository.yaml` / `helmrepository.yaml`
- DO expect the app's `ks.yaml` to reference a `GitRepository` (listed in `kustomization.yaml` under `resources` or `gitRepository` block)
- DO expect `app/flux-kustomization.yaml` as the Flux Kustomization that patches upstream YAML
- DO verify `postBuild.substituteFrom` is present if any `${VAR}` appear in the patches
