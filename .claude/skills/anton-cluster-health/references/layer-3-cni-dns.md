# Layer 3 — CNI & cluster DNS

Cilium is the CNI; CoreDNS handles cluster DNS. If either is unhealthy, everything above it is noise.

## Cilium agent (DaemonSet on every node)

```sh
# DaemonSet desired == ready?
kubectl -n kube-system get ds cilium

# Per-node agent pods
kubectl -n kube-system get pods -l k8s-app=cilium -o wide

# If the cilium CLI is installed (mise/task dependency):
cilium status --wait=false
```

**Healthy looks like**: `DESIRED=3, CURRENT=3, READY=3, UP-TO-DATE=3, AVAILABLE=3` (assuming the current 3-node cluster).

**Common failures**:
- One pod stuck `ContainerCreating` → node just rebooted; check `talos-inspect` for the node's kernel/services
- Restart count climbing on one node → check that node's `dmesg` via talosctl; often correlates with kube-apiserver contact loss
- IPAM exhaustion — rare in homelab but manifests as new pods stuck `ContainerCreating` with `no IP available`. Run `cilium status --verbose` for the CIDR allocation

## Cilium operator

```sh
kubectl -n kube-system get deploy cilium-operator
```

One replica is enough for a homelab. If it's crash-looping, reconciliation of CiliumNode resources stalls — new nodes fail to join the mesh cleanly.

## CoreDNS

```sh
kubectl -n kube-system get deploy coredns
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=30
```

**Healthy looks like**: 2 replicas Ready, zero restarts in recent history, logs quiet except periodic reload messages.

## DNS smoke test

Fastest proof that cluster DNS actually works end-to-end:

```sh
kubectl run -n default dnscheck --rm -it --restart=Never \
  --image=busybox:1.36 -- nslookup kubernetes.default
```

Expected: an A record answer within 1-2 seconds. If it hangs or returns `SERVFAIL`:

1. CoreDNS pods Ready? (above)
2. Cilium agent Ready on the node where `dnscheck` landed?
3. The `kube-dns` Service has endpoints? `kubectl -n kube-system get ep kube-dns`
4. NetworkPolicy blocking? Unlikely but check `kubectl get netpol -A`

## Common failure modes

- **CoreDNS CrashLoop on startup** — usually a bad ConfigMap edit (check `kubectl -n kube-system get cm coredns -o yaml`); Flux manages this via `kube-system/coredns`, so a bad commit is the usual culprit
- **DNS works from some nodes but not others** — one Cilium agent is broken; narrow via `kubectl get pods -o wide` to identify the node, then hand off to `talos-inspect`
- **Pods can resolve external names but not `*.svc.cluster.local`** — CoreDNS is up but its upstream forwarder is hijacking everything. Check the Corefile for missing `kubernetes cluster.local` plugin
