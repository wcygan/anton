---
name: anton-cluster-health
description: Kubernetes-layer health triage for Anton. Use when Codex checks whether the cluster is OK, Flux is healthy, platform controllers are ready, CNI or DNS is failing, cert-manager or ESO is stuck, gateways are broken, cloudflared is disconnected, or apps are unhealthy.
---

# Anton Cluster Health

Goal: Triage Anton from Kubernetes upward and stop at the first failing layer.

Success means:
- Node/Talos symptoms route to `talos-inspect` first.
- CNI/DNS, Flux, platform, and app checks run in order.
- The output is a ranked punch list with command evidence and safe next steps.

Stop when: the first red layer is explained or every layer is green enough for the user's question.

## Layer Order

1. Talos and nodes: use `talos-inspect` for node, disk, etcd, or network symptoms.
2. CNI and DNS: read `references/layer-3-cni-dns.md`.
3. Flux: read `references/layer-4-flux.md`.
4. Platform: read `references/layer-5-platform.md`.
5. Apps: read `references/layer-6-apps.md`.
6. Silent killers: read `references/silent-killers.md` when symptoms look clean but behavior is wrong.

## Read-Only Checks

```sh
kubectl get nodes -o wide
kubectl get pods -A
flux get sources git -A
flux get ks -A
flux get hr -A
kubectl -n cert-manager get pods
kubectl -n external-secrets get pods
kubectl -n network get pods,httproute,gateway
```

## Output Shape

Return:

- Overall status: green, yellow, red, or blocked.
- First failing layer.
- Evidence: commands and key lines.
- Next action: matching skill, file, or operator-approved command.

Keep the triage read-only. Hand off fixes to the relevant manifest, Flux, Talos, or credential workflow.
