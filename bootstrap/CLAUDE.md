# bootstrap/

Helmfile manifests applied once by `task bootstrap:apps` to take a fresh Talos cluster from "nodes Ready" to "Flux in charge." Only the minimum infrastructure Flux itself needs to run lives here.

## Contents

- `helmfile.d/00-crds.yaml` — extracts CRDs (external-dns, envoy-gateway, kube-prometheus-stack) before the charts that reference them are deployed
- `helmfile.d/01-apps.yaml` — six releases in strict `needs:` order: cilium → coredns → spegel → cert-manager → flux-operator → flux-instance
- `helmfile.d/templates/values.yaml.gotmpl` — one-line bridge that reads `.spec.values` directly from `kubernetes/apps/<ns>/<name>/app/helmrelease.yaml`, so bootstrap and Flux share a single source of values
- `sops-age.sops.yaml` — age key loaded into `flux-system` so Flux can decrypt on first sync

## Usage

Orchestrated by `scripts/bootstrap-apps.sh` in five phases: wait for nodes → create namespaces from `kubernetes/apps/*/` → apply SOPS secrets → apply CRDs → `helmfile sync`. After `flux-instance` is up, Flux reads `kubernetes/flux/cluster/ks.yaml` and runs everything from there — do not re-run bootstrap except during a full cluster rebuild (it is idempotent, but there is no reason to).

Only edit this directory if a component literally blocks cluster startup (CNI, DNS, cert-manager webhook, Flux itself). Everything else — monitoring, gateways, user apps — belongs under `kubernetes/apps/` and is Flux-managed. To change a bootstrap app's version or values, edit the corresponding HelmRelease under `kubernetes/apps/`; the `values.yaml.gotmpl` bridge picks it up on the next bootstrap run with no duplicate config.
