---
name: anton-cluster-health
description: Kubernetes-layer health triage for Anton. Starts above the Talos OS layer and walks CNI/DNS → Flux → platform components (cert-manager, ESO, envoy-gateway, cloudflared) → apps. Use when asking "is the cluster ok", "anything broken", "is Flux healthy", "platform components healthy", "ESO stuck", "gateway not serving", "cloudflared tunnel disconnected", "cert not issued". For node, disk, etcd, or network issues, hand off to talos-inspect first.
allowed-tools: Read, Bash
---

# Anton cluster health

Read-only ordered triage for the **Kubernetes layer and above**. Never mutates cluster state — no restarts, no force reconciles, no applies. If the triage surfaces a fix, hand off to the matching task skill (`debug-flux-reconciliation`, `upgrade-talos-or-k8s`, etc.).

## Scope — what this skill owns

| Layer | Owner | Notes |
|---|---|---|
| 1. Hardware, OS, disks, network | **`talos-inspect`** | Always start there if any sign the problem is below Flux |
| 2. Control plane, etcd quorum | **`talos-inspect`** | Talos manages these as static pods |
| 3. CNI & cluster DNS | **this skill** | [layer-3-cni-dns](references/layer-3-cni-dns.md) |
| 4. Flux (controllers, sources, root ks) | **this skill** | [layer-4-flux](references/layer-4-flux.md) |
| 5. Platform components | **this skill** | [layer-5-platform](references/layer-5-platform.md) |
| 6. App-layer summary | **this skill** | [layer-6-apps](references/layer-6-apps.md) |

**Stop at the first red layer and drill in.** Anything above a broken layer is noise.

## Gate — rule out the OS layer first

Before running anything in this skill, ask: *have nodes been flapping, did a node just reboot, is anyone reporting unreachability?* If yes, run `talos-inspect` first. Do not try to diagnose Flux when the real problem is a bonded interface down on `k8s-2`.

## Green-path one-liner

If you have 10 seconds and want a single pulse:

```sh
flux get ks -A --status-selector ready=false && \
flux get hr -A --status-selector ready=false
```

Two empty results means Flux believes everything is ok. **Necessary but not sufficient** — the [silent killers](references/silent-killers.md) do not show up in that output. Check those next.

## Full triage flow (layer 3 → 6)

### Layer 3 — CNI & DNS

Cilium agent must be Ready on every node; CoreDNS needs at least one Ready pod. A DNS failure masquerades as almost any app problem.

```sh
kubectl -n kube-system get ds cilium
kubectl -n kube-system get deploy coredns
kubectl -n kube-system get pods -l k8s-app=kube-dns
```

Details, DNS smoke test, common failures → [layer-3-cni-dns](references/layer-3-cni-dns.md).

### Layer 4 — Flux

Controllers themselves, then root `flux-system` Kustomization, then sources.

```sh
flux check
flux -n flux-system get ks flux-system
flux get sources all -A
```

**SOPS decryption errors** surface as Kustomization `ready=False` with a `decryption error` message — see [silent killers](references/silent-killers.md). Full flow → [layer-4-flux](references/layer-4-flux.md).

### Layer 5 — Platform (silent-killer territory)

cert-manager, External-Secrets + `ClusterSecretStore onepassword-connect`, envoy-gateway + Gateway `Programmed` condition, cloudflared tunnel, k8s-gateway.

```sh
kubectl get clustersecretstore onepassword-connect -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
kubectl get gateway -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,PROGRAMMED:.status.conditions[?(@.type=="Programmed")].status'
```

Details per component → [layer-5-platform](references/layer-5-platform.md).

### Layer 6 — Apps (only meaningful if 3-5 are green)

```sh
flux get ks -A --status-selector ready=false
flux get hr -A --status-selector ready=false
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -20
```

Count failures; do not deep-dive here. Hand off individual failures to `debug-flux-reconciliation` or direct log reading. Details → [layer-6-apps](references/layer-6-apps.md).

## Silent killers — the four that don't show up as "unhealthy"

These all pass `flux get ks/hr -A` but still break things. Always check explicitly. Full probes with copy-paste commands → [silent-killers](references/silent-killers.md).

1. **SOPS decryption error** — a Kustomization is `ready=False` with a `decryption error`; usually means `.sops.yaml` + age key mismatch after a rotation
2. **ClusterSecretStore `NotReady`** — ESO can't talk to 1Password, every `ExternalSecret` is frozen silently
3. **Gateway `Programmed=False`** — envoy-gateway Accepted the Gateway but failed to program it, HTTPRoutes attach but no traffic flows
4. **Cloudflared tunnel disconnected** — tunnel pod is Running but not registered; you just fixed a QUIC→HTTP/2 regression in commit `42822fc3`, watch for this class again

## What this skill does NOT do

- Does not mutate: no restarts, no `flux reconcile`, no `kubectl delete`, no `talosctl apply`
- Does not cover storage — Rook-Ceph was removed in commit `889a9662`, the cluster has no stateful storage layer right now
- Does not cover node/OS/etcd/disk/network — that's `talos-inspect`
- Does not deep-dive individual failing apps — hand off to `debug-flux-reconciliation`
- Does not report capacity or metric trends — only liveness/readiness

## Remote access

Every `kubectl`/`flux` command assumes the kubeconfig generated by `task bootstrap` or `task talos:generate-config`. For off-LAN access specifics → [anton-remote-access](../anton-remote-access/SKILL.md).
