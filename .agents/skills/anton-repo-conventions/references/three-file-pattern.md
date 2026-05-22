# The 3-file Flux app pattern (full example)

## Contents
- Tier 1 — ks.yaml
- Tier 2 — app/kustomization.yaml
- Tier 3 — app/helmrelease.yaml + app/ocirepository.yaml
- Namespace registration

Canonical exemplar in the repo: `kubernetes/apps/kube-system/reloader/`. Read it before authoring a new app.

## Tier 1 — ks.yaml

Path: `kubernetes/apps/<ns>/<app>/ks.yaml`. Tells Flux to reconcile a Git path as a Kustomization.

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: reloader
  namespace: flux-system
spec:
  interval: 1h
  path: ./kubernetes/apps/kube-system/reloader/app   # Always .../app, never .../<app-name>
  postBuild:
    substituteFrom:
      - name: cluster-secrets
        kind: Secret
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: kube-system
  wait: false
```

Notes:
- `metadata.namespace: flux-system` is required — Flux Kustomizations always live in `flux-system`.
- `spec.path` MUST end in `/app`. The directory layout is enforced by every existing app.
- `postBuild.substituteFrom` is the ONLY way `${VAR}` references in your manifests get resolved. Omit it and `${SECRET_DOMAIN}` will land literally in the cluster.
- Do NOT add `decryption.provider: sops`, retry policies, or HelmRelease defaults — they are inherited from `kubernetes/flux/cluster/ks.yaml` patches.
- Use `dependsOn: [{name: other-app}]` to order against another Flux Kustomization.

## Tier 2 — app/kustomization.yaml

Path: `kubernetes/apps/<ns>/<app>/app/kustomization.yaml`. Plain Kustomize file listing the resources Flux should apply.

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./ocirepository.yaml
  # - ./secret.sops.yaml
  # - ./externalsecret.yaml
  # - ./httproute.yaml
  # - ./certificate.yaml
  # - ./dnsendpoint.yaml
```

Just a list. Add new files here as you add them to the directory.

## Tier 3 — app/helmrelease.yaml + app/ocirepository.yaml

The actual resources. The most common shape is one HelmRelease + one OCIRepository:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: reloader
spec:
  interval: 15m
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 2.2.3
  url: oci://ghcr.io/stakater/charts/reloader
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: reloader
spec:
  chartRef:
    kind: OCIRepository
    name: reloader            # MUST match the OCIRepository.metadata.name above
  interval: 1h
  values:
    # ...
```

For the HelmRepository and GitRepository variants, see `helmrelease-sources.md`.

## Namespace registration

Every app must be listed in its namespace `kustomization.yaml`. Apps are NOT auto-discovered from the directory tree.

Path: `kubernetes/apps/<ns>/kustomization.yaml`

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./namespace.yaml
  - ./reloader/ks.yaml          # ← add this line for each new app
components:
  - ../../components/sops       # provides cluster-secrets to every app in this namespace
```

If you skip the `components: [../../components/sops]` line, `postBuild.substituteFrom` will fail to find `cluster-secrets` and every `${VAR}` will land literally.
