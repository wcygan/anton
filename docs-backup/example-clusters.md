# Example Clusters

This document summarizes the shared structure and conventions used by the two
example Flux-managed Talos/Kubernetes clusters.

## Common Patterns

- **Per-app directories** under `kubernetes/apps/<namespace>/<app>/`, each
  containing:
  - A top-level `kustomization.yaml` defining a Flux `Kustomization` CR (with
    `prune: true`, `interval`, `sourceRef: flux-system`, `path`,
    `targetNamespace`).
  - An `app/helmrelease.yaml` defining the chart source and a nested
    `app/kustomization.yaml` that applies the `HelmRelease`.
- **Shared components** in `kubernetes/components/common`, imported by each app
  via `components:`.
- **Encrypted secrets** managed with SOPS (`*.sops.yaml`) next to each
  HelmRelease and/or Kustomize overlay.
- **ConfigMapGenerators** used to surface `valuesFrom` for HelmReleases via
  `configMapGenerator` blocks and `kustomizeconfig.yaml` nameReference patches.
- **Repository CRs** (`HelmRepository` or `OCIRepository`) declared alongside
  charts to fetch Helm charts from registries.
- **Flux source** always `GitRepository` named `flux-system` in the
  `flux-system` namespace.

## Referencing These Examples

You can refer to either of these full cluster examples in the `/examples`
folder:

- `examples/onedr0p-home-ops.md` &ndash; Onedr0p's cluster-template
  demonstration
- `examples/Tanguille-cluster.md` &ndash; Tanguille's full cluster configuration

Each file contains the complete directory layout and manifest definitions
following the above patterns.

## Additional Observations

### Joryirving Home Ops Example (`examples/joryirving-home-ops.md`)

- Monorepo with `kubernetes/apps/base` for shared common components and
  `kubernetes/apps/<cluster>` overlays for cluster-specific deployments.
- Uses a top-level `Taskfile.yaml` plus MiniJinja templating (`.minijinja.toml`,
  `.mise.toml`) to generate Talos and Kubernetes configs and orchestrate tasks.
- Bootstraps core infrastructure via `bootstrap/helmfile.yaml` and
  `bootstrap/resources.yaml.j2` rather than Flux alone.
- Secrets managed by SOPS (`.sops.yaml`) and Flux `ExternalSecret` CRs alongside
  `*.sops.yaml` files.
- Per-app directories under `kubernetes/apps/...` follow the same
  `kustomization.yaml` + `helmrelease.yaml` + nested Kustomization pattern
  described above.

### JJGadgets Biohazard Example (`examples/JJGadgets-Biohazard.md`)

- Splits the repo under `kube/` into `bootstrap/` (Flux install manifests),
  `clusters/` (cluster and Talos configs), and `deploy/apps/` (per-app
  deployments).
- Each app in `deploy/apps/<app>` contains `ns.yaml` (namespace), `ks.yaml`
  (Kustomization), `es.yaml` (ExternalSecret), `hr.yaml` (HelmRelease), optional
  `pvc.yaml` (PVC), and other resource fragments.
- Flux configuration CRs (`flux-repo.yaml`, `kustomization.yaml`) live under
  `kube/clusters/<cluster>/flux/`, and Talos machine configs under
  `kube/clusters/<cluster>/talos/`.
- Uses a `Taskfile.dist.yaml` for task definitions and standard SOPS and
  pre-commit configuration files for CI consistency.
