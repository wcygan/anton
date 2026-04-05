# Common Workflows

Step-by-step recipes for the most frequent changes. All of these assume the repo conventions in `kubernetes-patterns.md` and `talos-patterns.md`.

## Add a new Flux app

1. Pick a namespace under `kubernetes/apps/<namespace>/`. Create it first if needed (see next section).
2. `mkdir kubernetes/apps/<namespace>/<app>/app`
3. Create `kubernetes/apps/<namespace>/<app>/ks.yaml` — copy from `kubernetes/apps/default/echo/ks.yaml`, update `metadata.name`, `spec.path`, and `spec.targetNamespace`.
4. Create `kubernetes/apps/<namespace>/<app>/app/kustomization.yaml` listing the resources you'll add.
5. Create the chart source:
   - OCI chart: `app/ocirepository.yaml` (preferred)
   - Classic Helm repo: `app/helmrepository.yaml`
6. Create `app/helmrelease.yaml` with `chartRef` (OCI) or `chart.spec.sourceRef` (HelmRepository) pointing at step 5. Inline `values:`.
7. If secrets are needed, add `app/secret.sops.yaml` (SOPS) or `app/externalsecret.yaml` (ESO). See `kubernetes-patterns.md` §5.
8. If the app is exposed, add HTTPRoute — inline in HelmRelease values if the chart supports it, otherwise `app/httproute.yaml`. For a secondary-domain app, also add `app/dnsendpoint.yaml` and ensure gateway certificates cover that domain.
9. Register the app: edit `kubernetes/apps/<namespace>/kustomization.yaml` and add `./<app>/ks.yaml` to the resources list. **This is required** — there is no auto-discovery.
10. `task configure` — validates schemas, renders templates, encrypts any `*.sops.*` files.
11. `git add -A && git commit && git push`
12. `task reconcile` or wait for Flux's poll interval.

Verify: `flux get ks -A | rg <app>`, `flux get hr -A | rg <app>`.

## Add a new namespace

1. `mkdir kubernetes/apps/<namespace>`
2. Create `namespace.yaml`:
   ```yaml
   apiVersion: v1
   kind: Namespace
   metadata:
     name: <namespace>
     annotations:
       kustomize.toolkit.fluxcd.io/prune: disabled
   ```
3. Create `kubernetes/apps/<namespace>/kustomization.yaml`:
   ```yaml
   apiVersion: kustomize.config.k8s.io/v1beta1
   kind: Kustomization
   resources:
     - ./namespace.yaml
     # - ./<app>/ks.yaml   (add apps here as you create them)
   components:
     - ../../components/sops
   ```
4. The namespace is picked up automatically by `kubernetes/flux/cluster/ks.yaml` which watches `./kubernetes/apps`.

## Expose a service

Two options, pick based on the chart:

**Option A — in HelmRelease values (if chart supports `route:` schema, e.g. bjw-s `app-template`):**
```yaml
values:
  route:
    app:
      hostnames: ["my-app.${SECRET_DOMAIN}"]
      parentRefs:
        - name: envoy-external        # public via Cloudflare tunnel
          namespace: network
          sectionName: https
      rules:
        - backendRefs: [{identifier: app, port: 80}]
```

**Option B — standalone `app/httproute.yaml`** (always works):
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
spec:
  hostnames: ["my-app.${SECRET_DOMAIN}"]
  parentRefs:
    - name: envoy-external            # or envoy-internal
      namespace: network
      sectionName: https
  rules:
    - backendRefs: [{name: my-app, port: 80}]
      matches: [{path: {type: PathPrefix, value: /}}]
```
Then add `- ./httproute.yaml` to `app/kustomization.yaml`.

Gateway choice:
- `envoy-external` — publicly reachable via Cloudflare tunnel
- `envoy-internal` — home network only (via k8s-gateway DNS)

For a secondary-domain host (`${SECRET_DOMAIN_TWO}`), you **also** need `app/dnsendpoint.yaml` (see `kubernetes-patterns.md` §6).

## Manage secrets

**SOPS route** (infrastructure secret that rarely rotates):
1. Create `app/secret.sops.yaml` in plain text with `data`/`stringData`.
2. `task configure` — encrypts in place.
3. Verify: `sops filestatus app/secret.sops.yaml` → encrypted.
4. Add `- ./secret.sops.yaml` to `app/kustomization.yaml`.

**ExternalSecret route** (preferred for new apps, pulls from 1Password):
1. Add the item to the `anton` 1Password vault.
2. Create `app/externalsecret.yaml` referencing `clusterSecretStoreRef: onepassword-connect` and `remoteRef.key: "item-name/field-name"`.
3. Add `- ./externalsecret.yaml` to `app/kustomization.yaml`.
4. No encryption step needed — nothing sensitive is in git.

Global vars (domain, etc.) belong in `kubernetes/components/sops/cluster-secrets.sops.yaml` — edit via `sops`, commit, run `task configure`.

## Add a node

1. Plan: get the node's hostname, IP, MAC, install disk serial, and a schematic ID from factory.talos.dev with the extensions you need.
2. Edit `nodes.yaml`: append a new entry under `nodes:` matching the existing schema.
3. `task configure` — validates `nodes.yaml` (CUE schema), re-renders `talos/talconfig.yaml`.
4. `task talos:generate-config` — produces machine config in `talos/clusterconfig/kubernetes-<hostname>.yaml`.
5. Boot the node off a Talos maintenance image (same version as `talenv.yaml`).
6. `task talos:apply-node IP=<new-node-ip> MODE=auto` — applies over insecure API, node reboots into configured state.
7. Verify: `talosctl -n <new-node-ip> health`, `kubectl get nodes`.
8. Commit: `nodes.yaml` and the updated `talos/talconfig.yaml`.

For a per-node patch, create `talos/patches/<hostname>/<patch>.yaml` — the template picks it up via `talos_patches('<hostname>')`.

## Upgrade a node (Talos OS)

1. Bump `talosVersion` in `talos/talenv.yaml`.
2. `task configure` — re-renders talconfig with the new version.
3. `task talos:upgrade-node IP=<node-ip>` — rolling upgrade, one node at a time.
4. Wait for node to come back: `talosctl -n <ip> version`, `kubectl get nodes`.
5. Repeat for each node.
6. Commit the `talenv.yaml` bump after all nodes are upgraded.

## Upgrade Kubernetes version

1. Bump `kubernetesVersion` in `talos/talenv.yaml`.
2. `task configure`.
3. `task talos:upgrade-k8s` — talhelper does the rolling upgrade (control planes first, then workers).
4. Verify: `kubectl get nodes -o wide`, `flux check`.
5. Commit.

## Edit an existing machine config patch

1. Edit `talos/patches/<scope>/<file>.yaml`.
2. `task talos:generate-config` — re-renders per-node configs.
3. Inspect the diff in `talos/clusterconfig/kubernetes-<hostname>.yaml` (gitignored, so `git diff` won't show anything — use your editor).
4. `task talos:apply-node IP=<ip> MODE=auto` for each affected node. Use `MODE=no-reboot` first to confirm Talos considers the change non-destructive; some kernel/disk changes force a reboot.

## Force a Flux sync

```
task reconcile
```

Or target a specific Kustomization:
```
flux reconcile kustomization <name> -n <ns> --with-source
```

## Pre-commit checklist

- [ ] `task configure` ran without errors
- [ ] No plaintext secrets: `find . -name '*.sops.*' -exec sops filestatus {} \;` all show encrypted
- [ ] No real tailnet name in any file (`<tailnet-name>.ts.net` placeholder only)
- [ ] Manifests validate: `deno task validate` (or whatever the `validate-changes` skill runs)
- [ ] Namespace kustomization lists the new app
- [ ] `ks.yaml` has `postBuild.substituteFrom` if the app uses `${VAR}`
