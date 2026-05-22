# kubernetes/apps/

Goal: Maintain Flux-managed applications using Anton's 3-file pattern.

Success means:
- Each app has a namespace entry, a Flux `ks.yaml`, and an `app/kustomization.yaml`.
- `ks.yaml` points at `./kubernetes/apps/<namespace>/<app>/app` and uses `postBuild.substituteFrom` with `cluster-secrets` when substitutions are needed.
- Helm apps use `helmrelease.yaml` plus `ocirepository.yaml` when upstream publishes OCI charts, or `helmrepository.yaml` when OCI is unavailable.
- Raw upstream manifests use an explicit `GitRepository` or vendored raw file pattern that matches existing siblings.

Stop when: the app shape matches an existing sibling, validation passes, and live reconciliation is left to Flux or explicit operator action.

## Read Order

For an unfamiliar app, read:

1. `<namespace>/<app>/ks.yaml`
2. `<namespace>/<app>/app/kustomization.yaml`
3. `<namespace>/<app>/app/helmrelease.yaml` or raw manifests
4. The namespace-specific `AGENTS.md` when present

Use `kubernetes/apps/kube-system/reloader/` as the simple Helm exemplar. Use existing apps in the same namespace before inventing a new shape.

## Secret Policy

Use External Secrets Operator for new application secrets. It reads from the 1Password vault `anton` through the `onepassword-connect` `ClusterSecretStore`.

Use SOPS for bootstrap or infrastructure secrets that must exist before ESO is ready. Verify every `*.sops.*` file with `sops filestatus <file>` before commit.

## Exposure Policy

Attach HTTPRoutes to `envoy-internal` for LAN/internal access and `envoy-external` only for Cloudflare-fronted public access. Secondary domains require a `DNSEndpoint`; HTTPRoute annotations alone are insufficient.

## Validation

Prefer local structural checks before cluster actions:

```sh
find . -name '*.sops.*' -not -name '.sops.yaml' -not -path './.private/*' -exec sops filestatus {} \;
yq . kubernetes/apps/<namespace>/<app>/ks.yaml
flux get ks -A
flux get hr -A
```
