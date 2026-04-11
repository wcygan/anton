# kubernetes/apps/

Flux-managed application manifests, grouped one directory per target namespace. Every app under a namespace follows the 3-file Flux pattern so scaffolding, reconciliation, and pruning are deterministic.

## Contents

- `<namespace>/namespace.yaml` + `<namespace>/kustomization.yaml` — creates the namespace (prune disabled) and lists the namespace's apps plus shared components (e.g. `../../components/sops` for SOPS decryption)
- `<namespace>/<app>/ks.yaml` — Flux `Kustomization` pointing at `./kubernetes/apps/<namespace>/<app>/app` with `postBuild.substituteFrom: cluster-secrets`
- `<namespace>/<app>/app/` — `kustomization.yaml` listing the resources, usually `helmrelease.yaml` + `ocirepository.yaml`, plus optional `secret.sops.yaml`, `externalsecret.yaml`, `httproute.yaml`, etc.
- `network/CLAUDE.md` — deeper guidance on gateways, HTTPRoutes, and the secondary-domain DNSEndpoint requirement

## Usage

Use the skills the root CLAUDE.md points at rather than hand-crafting manifests: `add-flux-app` for new apps, namespaces, or ExternalSecrets; `expose-service` for HTTPRoutes and DNSEndpoints; `debug-flux-reconciliation` when a sync is stuck; `anton-repo-conventions` for the SOPS-vs-ESO decision and postBuild rules. The `flux-app-author` and `conventions-linter` subagents handle the write-and-verify loop without touching the cluster.

When reading an unfamiliar app, open its `ks.yaml` first (to see the Flux inputs and which secrets it substitutes), then `app/kustomization.yaml` (for the full resource list), then `app/helmrelease.yaml`. Prefer copying the shape of an existing sibling in the same namespace over generating from scratch — every namespace already has a representative example.
