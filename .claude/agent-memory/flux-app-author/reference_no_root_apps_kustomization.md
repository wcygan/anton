---
name: No root kubernetes/apps/kustomization.yaml — namespaces discovered by Flux recursion
description: Do not create or update a root kustomization.yaml when adding a new namespace; each namespace has its own kustomization.yaml and Flux finds them by recursive discovery
type: reference
---

anton does **not** have a `kubernetes/apps/kustomization.yaml`. The top-level Flux `Kustomization` at `kubernetes/flux/cluster/ks.yaml` sets `path: ./kubernetes/apps` and Flux's kustomize-controller recurses — each `kubernetes/apps/<ns>/kustomization.yaml` is picked up automatically.

Confirmed 2026-04-16: `find kubernetes/apps -maxdepth 2 -name kustomization.yaml` shows one file per namespace (`cert-manager`, `external-secrets`, `flux-system`, `kube-system`, `network`, `storage`, `default`, `playground`), zero at the root.

When adding a new namespace:
1. Create `kubernetes/apps/<ns>/namespace.yaml` (with `kustomize.toolkit.fluxcd.io/prune: disabled`).
2. Create `kubernetes/apps/<ns>/kustomization.yaml` listing `./namespace.yaml` and each `./<app>/ks.yaml`, plus `components: [../../components/sops]`.
3. **Do not** touch any root-level apps registration — there isn't one.

Briefs that ask you to "update the root apps kustomization.yaml" for a new namespace are describing a different homelab layout; in anton that file does not exist and should not be created.
