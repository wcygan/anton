# Hosting Apps Outside Flux

How to deploy a workload directly into the anton cluster with `kubectl apply`, bypassing the GitOps repo, while still reusing the existing Cloudflare Tunnel, wildcard certificate, and `envoy-external` gateway. Useful for short-lived experiments, throwaway demos, or one-off services that don't justify a full Flux scaffold.

## When to use this pattern

| Use this pattern | Use Flux (the GitOps repo) |
|---|---|
| Throwaway prototype you'll delete in days | Anything you want to survive a cluster reset |
| Manual hands-on iteration loop (image-tag changes, debug builds) | Anything other people in the cluster need to rely on |
| You need a hostname *now* and the GitOps round-trip is too slow | Production-quality services with backups, monitoring, alerting |
| Demos that should disappear when the laptop closes | Anything you would be unhappy to lose |

If a "throwaway prototype" turns into something you're glad you have, promote it into Flux via the `add-flux-app` skill. The `HTTPRoute` and `Service` shapes carry over identically; only the `Deployment` graduates into a `HelmRelease` (or stays as raw manifests under `app/kustomization.yaml`).

## Why this works

Three load-bearing facts about the cluster make this pattern viable without touching a single line of `kubernetes/`:

1. **Wildcard tunnel ingress.** `cloudflare-tunnel`'s ConfigMap routes `*.<onboarded-domain>` to `envoy-external`. Any new subdomain of an already-onboarded domain is covered automatically.
2. **Wildcard TLS cert.** Each onboarded domain has a `*.<domain>` certificate attached to the `envoy-external` gateway listener. Every new subdomain inherits TLS for free.
3. **Cross-namespace gateway attach.** The `envoy-external` listener is configured with `allowedRoutes.namespaces.from: All`, so an `HTTPRoute` in any namespace — including a non-Flux-managed one — can attach to it.

The only thing the cluster *can't* do for you on the cheap path is publish DNS, because `external-dns` runs with `--gateway-name=envoy-external` (which forces it to inherit the gateway's annotation and ignore HTTPRoute-level annotations). For non-primary domains, you must include a `DNSEndpoint` resource — exactly the same gotcha as for any non-primary domain in the GitOps flow. See [adding a 2nd domain](./adding-a-2nd-domain.md) for the underlying explanation.

## Namespace strategy

Use a dedicated `scratch` (or `lab`, or whatever name resonates) namespace that **no Flux Kustomization owns**. Benefits:

- Zero pruning risk. Flux only prunes resources carrying its ownership labels (`kustomize.toolkit.fluxcd.io/*`); imperatively-applied resources don't have them. A namespace with no Flux Kustomization removes the question entirely.
- One-command teardown: `kubectl delete ns scratch` wipes every experiment in there.
- Defense-in-depth: annotating the namespace with `kustomize.toolkit.fluxcd.io/prune: disabled` ensures even a future Flux Kustomization pointed at this namespace cannot delete it.

**Avoid** putting these resources into Flux-managed namespaces (`default`, `network`, `observability`, `databases`, etc.). It works, because Flux still won't prune your unlabelled resources, but raises the chance of name collisions and confusing debug sessions later.

## Minimum manifest set

Five resources in one YAML file. Save outside the anton repo (e.g. `~/scratch/<app>.yaml`). Substitute the app name (`hello`), the public hostname (`hello.example.com`), and the container image as needed. The `external.example.com` target in the `DNSEndpoint` matches the existing tunnel-CNAME entry that `cloudflare-tunnel/app/dnsendpoint.yaml` already publishes for the onboarded domain.

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: scratch
  annotations:
    kustomize.toolkit.fluxcd.io/prune: disabled
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello
  namespace: scratch
  labels:
    scratch.app: hello
spec:
  replicas: 1
  selector:
    matchLabels:
      scratch.app: hello
  template:
    metadata:
      labels:
        scratch.app: hello
    spec:
      containers:
        - name: app
          image: ghcr.io/mendhak/http-https-echo:38
          env:
            - { name: HTTP_PORT, value: "80" }
          ports:
            - { containerPort: 80, name: http }
          resources:
            requests: { cpu: 10m, memory: 32Mi }
            limits: { memory: 128Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: hello
  namespace: scratch
  labels:
    scratch.app: hello
spec:
  selector:
    scratch.app: hello
  ports:
    - { name: http, port: 80, targetPort: http }
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: hello
  namespace: scratch
  labels:
    scratch.app: hello
spec:
  parentRefs:
    - name: envoy-external
      namespace: network
      sectionName: https
  hostnames:
    - hello.example.com
  rules:
    - backendRefs:
        - name: hello
          port: 80
---
apiVersion: externaldns.k8s.io/v1alpha1
kind: DNSEndpoint
metadata:
  name: hello
  namespace: scratch
  labels:
    scratch.app: hello
spec:
  endpoints:
    - dnsName: hello.example.com
      recordType: CNAME
      targets: ["external.example.com"]
```

A few details worth understanding:

- The `scratch.app: <name>` label on every resource lets you target a single app for teardown without disturbing siblings sharing the namespace.
- `parentRefs[].sectionName: https` attaches to the gateway's TLS listener (port 443), not the plain HTTP-redirect listener.
- `parentRefs[].namespace: network` is required — the gateway lives in the `network` namespace, the route in `scratch`.
- The `DNSEndpoint`'s `targets` field references a CNAME target that the cluster's tunnel `DNSEndpoint` resource has already published — that resolves the chain `<app>.<domain>` → `external.<domain>` → `<tunnel-uuid>.cfargotunnel.com`.

## Workflow

```sh
# deploy
kubectl apply -f ~/scratch/hello.yaml

# verify (DNS publishes within ~1 min after the DNSEndpoint lands)
kubectl get dnsendpoint -n scratch
kubectl get httproute -n scratch hello -o yaml | grep -A 5 status:
dig +short hello.example.com @1.1.1.1
curl -sI https://hello.example.com/

# iterate
kubectl set image -n scratch deploy/hello app=<new-image>
kubectl rollout status -n scratch deploy/hello

# tear down a single app
kubectl delete -n scratch all,httproute,dnsendpoint -l scratch.app=hello

# nuke everything in scratch
kubectl delete ns scratch
```

## What's bypassed vs reused

| Concern | Behavior |
|---|---|
| Flux ownership / pruning | Bypassed — the `scratch` namespace is invisible to Flux |
| Cluster-secrets `${VAR}` substitution | Bypassed — write literal hostnames directly |
| Tunnel ingress edits | Not needed — wildcard covers all subdomains of an onboarded domain |
| Wildcard cert | Reused — comes for free via the `envoy-external` listener |
| External-dns | Used — picks up the `DNSEndpoint` and publishes the CNAME |
| `envoy-external` gateway | Used — `HTTPRoute` attaches cross-namespace |
| Cloudflare tunnel | Used — `cloudflared` proxies the request the same way it does for Flux-managed apps |

The pattern reuses the heavy stable bits (gateway, cert, tunnel) and skips the parts that exist for safe collaboration (GitOps round-trip, postBuild substitution, code review). That's the right trade for one-off work.

## Things to know

- **Image stability.** No `imagePullPolicy: Always` is set, and the `:38` tag is immutable, so the pod will not pull a newer image on its own. That's intentional for stability between iterations. Force an update with `kubectl set image` or `kubectl rollout restart`.
- **Audit drift periodically.** Imperative resources are invisible to the repo, which means they're invisible to your future self. Once a quarter, run `kubectl get httproute -A` and `kubectl get dnsendpoint -A` and confirm everything in non-Flux namespaces (e.g. `scratch`, `lab`) is intentional.
- **Promotion path.** When something graduates from "experiment" to "real," scaffold it via `add-flux-app` (10-minute round-trip). The `HTTPRoute` shape carries over verbatim; only the `Deployment` moves into a `HelmRelease`.
- **Cleanup gotcha.** If you `kubectl delete ns scratch` while an `HTTPRoute` outside `scratch` references one of its Services (rare; only if you cross-pollinated namespaces deliberately), the route hangs in `Accepted=False` until you fix the dangling reference. Easy to spot via `kubectl describe httproute`.
- **No Prometheus scrape by default.** kube-prometheus-stack scrapes via `ServiceMonitor` / `PodMonitor` discovery in known namespaces; your scratch app won't show up in Grafana unless you add a `ServiceMonitor`. That's usually fine for experiments.
- **No backups, no replication, no DR.** A `scratch` Deployment is single-replica, no PVC by default, no Longhorn replication. If the workload writes state you care about, this is the wrong pattern — graduate to Flux first.

## When the wildcard isn't enough

If the experimental hostname needs a domain the cluster has *not* yet onboarded, you can't avoid a Flux change — onboarding a new domain edits `cluster-secrets`, `cloudflare-tunnel`, `envoy-gateway`, `cert-manager`, and `cloudflare-dns`, all of which are GitOps territory. Walk-through: [adding a 2nd domain](./adding-a-2nd-domain.md). After the domain is onboarded, this pattern works for any subdomain of it.

## Related notes

- [Adding a 2nd domain](./adding-a-2nd-domain.md) — full domain onboarding flow; prerequisite for new top-level zones
- [Exposing workloads through Tailscale](./exposing-workloads-through-tailscale.md) — alternative path for off-LAN HTTP UIs without going public
