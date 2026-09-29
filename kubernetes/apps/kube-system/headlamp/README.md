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

## Network isolation

`app/networkpolicy.yaml` isolates Headlamp ingress. It allows TCP to the named
`http` container port only from the Tailscale-managed proxy for the
`kube-system/headlamp` Ingress in the `tailscale` namespace. It selects both
Headlamp chart labels, so other `kube-system` workloads are unaffected.
The chart's Service port 80 forwards to container port 4466.

The proxy namespace, managed label, parent name, parent namespace, and resource
type must all match. This excludes ordinary Cloudflare and Envoy pods, other
Tailscale proxies, and similarly labelled pods in other namespaces. Kubernetes
NetworkPolicies are additive: any additional policy selecting Headlamp must
preserve this restriction. Node-origin traffic and privileged network paths
are outside this policy's ordinary pod-traffic boundary.

The policy does not replace token login. Broad edge egress restrictions remain
separate work because cloudflared's upstream connectivity and Envoy's backend
and control-plane connections must be preserved.

## Verification

Local structural checks:

```sh
yq . kubernetes/apps/kube-system/headlamp/ks.yaml \
  kubernetes/apps/kube-system/headlamp/app/kustomization.yaml \
  kubernetes/apps/kube-system/headlamp/app/helmrepository.yaml \
  kubernetes/apps/kube-system/headlamp/app/helmrelease.yaml \
  kubernetes/apps/kube-system/headlamp/app/ingress.yaml \
  kubernetes/apps/kube-system/headlamp/app/networkpolicy.yaml \
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

Before deployment, check that rendered and applied Headlamp pods have both
selector labels and the `http` port, and that the proxy pod has the policy's
four Tailscale labels in namespace `tailscale`. The labels and port were
verified with read-only live metadata on 2026-09-29 and chart 0.45.0 rendering.

After the change is deployed, retain the Flux revision, applied policy, and
Headlamp readiness. With explicit approval for live traffic testing (or in an
isolated test cluster), verify Tailscale access and token login still work,
while direct connections from cloudflared and external Envoy to the Headlamp
Service are blocked. Unauthenticated application requests must not return
cluster data. Local manifest checks alone do not prove Cilium enforcement.

If legitimate Tailscale access fails, revert the policy and its Kustomize entry
through Git, then confirm Flux prunes it. Do not widen the allow rule to the
whole `tailscale` or `network` namespace as a diagnostic shortcut.
