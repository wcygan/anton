# Authoring the HTTPRoute

Two workflows. Default to A.

## Workflow A — standalone HTTPRoute file (default, always works)

Use this unless the chart explicitly documents a `route:` schema. It works with every chart, keeps routing decoupled from chart values, and matches what most apps in this repo already do.

1. Create `kubernetes/apps/<ns>/<app>/app/httproute.yaml`:

   ```yaml
   ---
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata:
     name: <app>
   spec:
     hostnames: ["<app>.${SECRET_DOMAIN}"]
     parentRefs:
       - name: envoy-internal          # default; use envoy-external only when public is approved
         namespace: network
         sectionName: https
     rules:
       - backendRefs:
           - name: <service-name>      # a Service in the same namespace as the HTTPRoute
             port: 80
         matches:
           - path:
               type: PathPrefix
               value: /
   ```

2. Add to `kubernetes/apps/<ns>/<app>/app/kustomization.yaml`:

   ```yaml
   resources:
     - ./helmrelease.yaml
     - ./ocirepository.yaml
     - ./httproute.yaml
   ```

3. `task configure` to validate and encrypt, then commit + push, then `task reconcile` (or wait for the Flux interval).

## Workflow B — HTTPRoute inside HelmRelease values

Use this **only** when the chart explicitly supports a `route:` schema. In this repo that currently means bjw-s `app-template`. Saves a file at the cost of coupling routing to the chart; not worth it for one-off charts.

```yaml
spec:
  values:
    route:
      app:
        hostnames: ["{{ .Release.Name }}.${SECRET_DOMAIN}"]
        parentRefs:
          - name: envoy-internal        # default
            namespace: network
            sectionName: https
        rules:
          - backendRefs: [{identifier: app, port: 80}]
```

## Conventions that apply to both workflows

- `parentRefs[0].name` is a Gateway name, never a Service name.
- `parentRefs[0].namespace: network` is mandatory (both gateways live there).
- `parentRefs[0].sectionName: https` attaches to the TLS listener; omitting it silently lands on port 80 and nothing works in a browser.
- Hostname uses `${SECRET_DOMAIN}` substitution — the `postBuild.substituteFrom: cluster-secrets` in the app's `ks.yaml` resolves it at reconcile time.
- Prefer one HTTPRoute per hostname. If an app needs both LAN and public endpoints, ship two HTTPRoutes with different subdomains.
