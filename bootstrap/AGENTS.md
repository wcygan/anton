# bootstrap/

Goal: Maintain the one-time Helmfile bootstrap layer that hands a fresh Talos cluster to Flux.

Success means:
- Bootstrap contains only the components required before Flux can reconcile the repo.
- Bootstrap values continue to read from the matching HelmReleases under `kubernetes/apps/`.
- Fresh-cluster startup order remains explicit and minimal.

Stop when: the bootstrap path still installs CNI, DNS, cert-manager, Flux operator, and Flux instance in dependency order.

## Contents

- `helmfile.d/00-crds.yaml`: pre-installs CRDs needed by early charts.
- `helmfile.d/01-apps.yaml`: installs cilium, coredns, spegel, cert-manager, flux-operator, and flux-instance.
- `helmfile.d/templates/values.yaml.gotmpl`: reads `.spec.values` from committed HelmReleases.
- `sops-age.sops.yaml`: loads the age key into `flux-system` for first sync.

## Usage

Use `scripts/bootstrap-apps.sh` through `task bootstrap:apps`. Edit `bootstrap/` only when a component blocks cluster startup. Put normal platform components, monitoring, gateways, and apps under `kubernetes/apps/`.

## Validation

```sh
yq . bootstrap/helmfile.d/00-crds.yaml
yq . bootstrap/helmfile.d/01-apps.yaml
sops filestatus bootstrap/sops-age.sops.yaml
```
