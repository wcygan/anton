# Headlamp

Headlamp is the Tailscale-only Kubernetes web UI for Anton. It is deployed by
Flux from this directory into `kube-system`.

## Access

Use the Tailscale hostname:

```sh
https://headlamp.<tailnet-name>.ts.net
```

The committed Ingress uses `ingressClassName: tailscale` and the short TLS host
`headlamp`. Do not add Cloudflare, public DNS, or `envoy-external` exposure for
this app.

## Authentication

Headlamp is configured for in-cluster mode and token login. Generate a
short-lived token for the read-only Headlamp service account:

```sh
kubectl -n kube-system create token headlamp --duration=8h
```

Paste the output into the `ID token` field in Headlamp. Do not commit, paste into
chat, or store the token.

Long-term interactive access should use OIDC before granting write permissions
or long-lived credentials.

## Permissions

`app/rbac.yaml` binds the `kube-system/headlamp` service account to the built-in
`view` role plus a small cluster-scoped read role for dashboard inventory such as
nodes, namespaces, storage classes, CRDs, and API services.

The Headlamp RBAC intentionally omits:

- secrets
- mutating verbs
- cluster-admin access

## Verification

Local structural checks:

```sh
yq . kubernetes/apps/kube-system/headlamp/ks.yaml \
  kubernetes/apps/kube-system/headlamp/app/kustomization.yaml \
  kubernetes/apps/kube-system/headlamp/app/helmrepository.yaml \
  kubernetes/apps/kube-system/headlamp/app/helmrelease.yaml \
  kubernetes/apps/kube-system/headlamp/app/ingress.yaml \
  kubernetes/apps/kube-system/headlamp/app/rbac.yaml

kubectl kustomize kubernetes/apps/kube-system/headlamp/app \
  | kubectl apply --dry-run=client -f -
```

Live read-only checks:

```sh
flux get ks -n kube-system headlamp
flux get hr -n kube-system headlamp
kubectl -n kube-system get deploy,svc,ingress headlamp
kubectl -n kube-system rollout status deploy/headlamp --timeout=120s
curl -I https://headlamp.<tailnet-name>.ts.net
```

The Codex in-app browser is Electron-based. Headlamp treats Electron user agents
as the desktop app and may try to call `localhost:4466`; verify the deployed web
UI in a normal browser such as Chrome.
