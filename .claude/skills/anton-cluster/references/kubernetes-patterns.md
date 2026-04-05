# Kubernetes / Flux Patterns

Conventions for everything under `kubernetes/` in the Anton repo. Paired with `talos-patterns.md` for the OS layer.

## 1. Directory Layout

```
kubernetes/
├── apps/                               # Flux-managed applications, one dir per namespace
│   └── <namespace>/
│       ├── namespace.yaml              # Namespace object; annotated prune: disabled
│       ├── kustomization.yaml          # Lists apps + includes ../../components/sops
│       └── <app>/
│           ├── ks.yaml                 # Flux Kustomization CR (watches Git path)
│           └── app/
│               ├── kustomization.yaml  # Plain Kustomize; lists resources in this dir
│               ├── helmrelease.yaml
│               ├── ocirepository.yaml  # OR helmrepository.yaml
│               ├── secret.sops.yaml    # Optional
│               ├── httproute.yaml      # Optional
│               ├── certificate.yaml    # Optional
│               ├── dnsendpoint.yaml    # Optional (needed for secondary domains)
│               └── externalsecret.yaml # Optional (ESO)
├── components/
│   └── sops/                           # Kustomize Component, pulled in by every namespace
│       ├── kustomization.yaml          # kind: Component
│       └── cluster-secrets.sops.yaml   # Encrypted Secret cluster-secrets
└── flux/
    └── cluster/
        └── ks.yaml                     # Top-level Kustomization; root entry point
```

Rules:
- Apps are **not** auto-discovered. Namespace kustomization must list `./app-name/ks.yaml` explicitly.
- Namespaces carry `kustomize.toolkit.fluxcd.io/prune: disabled` annotation so Flux never deletes them.
- Every namespace kustomization includes `../../components/sops` to get `cluster-secrets`.

## 2. The 3-File Flux App Pattern

Every app has **exactly three tiers**:

**Tier 1 — `<ns>/<app>/ks.yaml`**: Flux `Kustomization` CR. Tells Flux to reconcile a Git path.
**Tier 2 — `<ns>/<app>/app/kustomization.yaml`**: Plain Kustomize list of resources in the `app/` dir.
**Tier 3 — `<ns>/<app>/app/{helmrelease,ocirepository,…}.yaml`**: The actual resources.

Clean exemplar: `kubernetes/apps/default/echo/`.

```yaml
# ks.yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: echo
spec:
  interval: 1h
  path: ./kubernetes/apps/default/echo/app   # Always .../app, never .../echo
  postBuild:
    substituteFrom:
      - name: cluster-secrets
        kind: Secret
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: default
  wait: false
```

```yaml
# app/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./ocirepository.yaml
```

## 3. Flux Kustomization Conventions

| Field | Convention | Notes |
|---|---|---|
| `metadata.name` | matches app directory | |
| `spec.interval` | `1h` | |
| `spec.path` | `./kubernetes/apps/<ns>/<app>/app` | Must end in `/app` |
| `spec.prune` | `true` | Always |
| `spec.wait` | `false` | `true` only for critical services |
| `spec.targetNamespace` | matches namespace dir | |
| `spec.sourceRef` | `GitRepository flux-system/flux-system` | Always |
| `spec.postBuild.substituteFrom` | `cluster-secrets` Secret | Required for `${VAR}` |
| `spec.dependsOn` | `[{name: other-app}]` | For ordering |

`decryption.provider: sops` and HelmRelease defaults (`install.crds: CreateReplace`, retry policies, `cleanupOnFail`) are **inherited** from patches in `kubernetes/flux/cluster/ks.yaml` — do not repeat them per app.

## 4. HelmRelease Conventions

**Pattern A — OCIRepository (preferred for modern charts):**

```yaml
# ocirepository.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: echo
spec:
  interval: 15m
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 4.4.0
  url: oci://ghcr.io/bjw-s-labs/helm/app-template
---
# helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: echo
spec:
  chartRef:
    kind: OCIRepository
    name: echo             # MUST match ocirepository.metadata.name
  interval: 1h
  values:
    # ...
```

**Pattern B — HelmRepository (traditional Helm repos, e.g. harbor, cloudnative-pg):**

```yaml
spec:
  chart:
    spec:
      chart: <chart-name>
      version: X.Y.Z
      sourceRef:
        kind: HelmRepository
        name: <repo-name>
```

**Values loading** — inline `values:` for most config, `valuesFrom:` for values sourced from Secrets/ConfigMaps:

```yaml
spec:
  values: { ... }
  valuesFrom:
    - kind: Secret
      name: my-secret
      valuesKey: password
      targetPath: auth.password
```

## 5. Secrets Patterns

Two systems coexist. Choose based on source and lifecycle.

### SOPS-encrypted Secret (static, small, infrastructure)

File: `kubernetes/apps/<ns>/<app>/app/secret.sops.yaml`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-secret
stringData:
  token: "sensitive-value"
# After edit: sops --encrypt --in-place secret.sops.yaml
# Or run: task configure
```

Use when: API tokens, bootstrap credentials, values that rarely change. SOPS rules live in `.sops.yaml`; only `data`/`stringData` fields are encrypted for `bootstrap/` and `kubernetes/` paths.

### ExternalSecret (ESO → 1Password, preferred for new apps)

`ClusterSecretStore` `onepassword-connect` authenticates via a service-account token and pulls from the `anton` 1Password vault. See exemplar `kubernetes/apps/external-secrets/onepassword-store/`.

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: my-secret
  namespace: default
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: my-secret
    creationPolicy: Owner
  data:
    - secretKey: password
      remoteRef:
        key: "item-name/field-name"   # SDK provider combined-key syntax
```

Use when: rotating credentials, shared secrets, large secret payloads.

### Global cluster variables

`kubernetes/components/sops/cluster-secrets.sops.yaml` holds a Secret named `cluster-secrets` with keys like `SECRET_DOMAIN`, `SECRET_DOMAIN_TWO`. Every `ks.yaml` references it via `postBuild.substituteFrom`, so `${SECRET_DOMAIN}` is interpolated at Flux apply time.

## 6. Gateway API & DNS

Two gateways, two traffic paths, split-horizon DNS.

| Gateway | Purpose | Traffic source |
|---|---|---|
| `envoy-external` | Public via Cloudflare tunnel | Internet → Tunnel → Gateway |
| `envoy-internal` | Home network | LAN → k8s-gateway DNS → Gateway |

Both live in namespace `network`. Gateway IPs are pinned via Cilium LBIPAM annotations (`lbipam.cilium.io/ips`). Certificates are issued by cert-manager (`letsencrypt-production` ClusterIssuer) and stored as Secrets named like `${SECRET_DOMAIN/./-}-production-tls`.

### HTTPRoute pattern

Either inside the HelmRelease values (when the chart supports it, e.g. `app-template`):

```yaml
values:
  route:
    app:
      hostnames: ["{{ .Release.Name }}.${SECRET_DOMAIN}"]
      parentRefs:
        - name: envoy-external
          namespace: network
          sectionName: https
      rules:
        - backendRefs:
            - identifier: app
              port: 80
```

Or as a standalone file `app/httproute.yaml`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
spec:
  hostnames: ["my-app.${SECRET_DOMAIN}"]
  parentRefs:
    - name: envoy-external
      namespace: network
      sectionName: https
  rules:
    - backendRefs:
        - name: my-app
          port: 80
      matches:
        - path:
            type: PathPrefix
            value: /
```

### Secondary domain apps (CRITICAL)

For apps on `${SECRET_DOMAIN_TWO}`, **explicit `DNSEndpoint` is required** — external-dns's `--gateway-name` filter does not pick up HTTPRoute annotations for the second domain. Also add a gateway certificate for the second domain. See `docs/docs/notes/adding-a-2nd-domain.md` and exemplar `kubernetes/apps/default/echo-two/app/dnsendpoint.yaml`:

```yaml
apiVersion: externaldns.k8s.io/v1alpha1
kind: DNSEndpoint
metadata:
  name: echo-two
spec:
  endpoints:
    - dnsName: "echo-two.${SECRET_DOMAIN_TWO}"
      recordType: CNAME
      targets: ["external.${SECRET_DOMAIN_TWO}"]
```

## 7. Components

Currently only `kubernetes/components/sops/`, a Kustomize `Component` that supplies the `cluster-secrets` Secret to any namespace that includes it. Pattern leaves room to add more components (e.g. shared RBAC, storage defaults) — include via `components: [../../components/<name>]` in the namespace kustomization.

## 8. Flux Root Wiring

`kubernetes/flux/cluster/ks.yaml` is the top-level Kustomization:

- `path: ./kubernetes/apps` — watches every namespace subdirectory
- `decryption.provider: sops` — enables SOPS for all child Kustomizations via patches
- Nested `patches:` inject HelmRelease defaults (`install.crds: CreateReplace`, `upgrade.cleanupOnFail: true`, retry/remediation policies) into every HelmRelease cluster-wide, so app authors don't repeat them

`GitRepository flux-system/flux-system` is the single source reference everything uses.

## 9. Variable Substitution Pipeline

Three stages, in order:

1. **Makejinja** (local, at `task configure` time) — renders `{{ var }}` from `cluster.yaml`/`nodes.yaml` into `${VAR}` Flux placeholders. Output is committed to git.
2. **Flux `postBuild.substituteFrom`** (at reconciliation) — replaces `${VAR}` with values from the `cluster-secrets` Secret, provided by the `sops` component.
3. **Helm templating** (during HelmRelease install) — resolves `{{ .Values.* }}`, `{{ .Release.Name }}`, etc.

Common failure: `${VAR}` appearing literal in a deployed resource → forgot `postBuild.substituteFrom` in `ks.yaml`, or the namespace kustomization doesn't include `../../components/sops`.

## 10. Consistency Notes

Patterns are strictly followed across all namespaces. Observed intentional variations (not drift):

- OCIRepository is preferred; HelmRepository is still used for charts not published to OCI (harbor, cloudnative-pg).
- Routes sometimes live in `helmrelease.yaml` values, sometimes in `app/httproute.yaml` — depends on whether the chart exposes a route schema.
- `wait: false` is the norm; no app currently uses `wait: true`.
