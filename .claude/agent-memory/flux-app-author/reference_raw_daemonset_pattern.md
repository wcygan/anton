---
name: Raw-resource Flux app with per-node DaemonSet config via ConfigMap
description: Pattern for Flux apps that are a bare DaemonSet + ConfigMap + SA, with per-node config keyed by NODE_NAME, and no Helm/OCI/Git chart source
type: reference
---

Exemplar: `kubernetes/apps/network/storage-vxlan/` (Phase 4c of plan 0004, 2026-04-19).

When the app is a DaemonSet that needs per-node configuration (e.g. different VTEP / overlay IPs per node) but should still run one image with one Pod spec, the anton pattern is:

1. Standard `ks.yaml` — identical shape to sibling chart-based apps: `interval: 1h`, `path: ./kubernetes/apps/<ns>/<app>/app`, `postBuild.substituteFrom: cluster-secrets`, `sourceRef: flux-system`, `wait: false`. No difference in the Flux Kustomization just because there's no chart.
2. `app/kustomization.yaml` — plain `kustomize.config.k8s.io/v1beta1` listing the raw resources in alphabetical order (`./configmap.yaml`, `./daemonset.yaml`, `./serviceaccount.yaml`). No GitRepository / HelmRepository / OCIRepository. No `flux-kustomization.yaml` needed — unlike `multus/` and `whereabouts/`, there is no external source to track.
3. `app/configmap.yaml` — one key per node (`k8s-1.env`, `k8s-2.env`, ...), each an env-file. Mount as projected volume at `/etc/vxlan-nodemap/`; container sources `/etc/vxlan-nodemap/${NODE_NAME}.env` where `NODE_NAME` comes from the downward API (`fieldRef: spec.nodeName`).
4. `app/daemonset.yaml` — the DS itself. Script shape that works well inside `command: [/bin/bash, -c] / args: [|-block]`:
   - `set -euo pipefail`
   - Guard that the nodemap file exists (`[[ -r $f ]] || { echo FATAL; exit 1; }`) — Longhorn-quality error messaging matters when a new node is added and the ConfigMap wasn't updated.
   - `source` the env file, then `: ${VAR:?}` assert each required var is set.
   - Use `ip link show X || ip link add X ...` + `ip addr replace` + `bridge fdb replace/append` for idempotency on pod restart.
   - `exec sleep infinity` at the end so the pod stays Ready (do NOT leave a restart-loop probe friendly).

Security: `capabilities.add: [NET_ADMIN] drop: [ALL]`, `privileged: false`, `runAsNonRoot: false` (needs root for `ip link`), `allowPrivilegeEscalation: true`. No hostPath. `hostNetwork: true`, `hostPID: false`, `dnsPolicy: ClusterFirstWithHostNet`.

Scheduling on an all-control-plane cluster: add the control-plane toleration explicitly — without it, a DS reports `0/N` and silently fails to roll out.
```
tolerations:
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule
```

Image pinning: keep a `# renovate: datasource=docker depName=<image>` comment above the `image:` line so Renovate can track the tag. `nicolaka/netshoot:v0.13` is the latest stable at time of writing and is already implicitly used elsewhere via probe pods.

No RBAC needed when the DS only touches the host netns (`ip`, `bridge`), never the K8s API — omit Role / RoleBinding / ClusterRole. The SA exists purely for identity/audit clarity.

Namespace kustomization registration is the single easy-to-miss step (apps are not auto-discovered): add `- ./<app>/ks.yaml` alphabetically to `kubernetes/apps/<ns>/kustomization.yaml`.

Hook warning quirk: `check_3_file_pattern.py` fires after every Write, so mid-sequence (after `ks.yaml` but before `app/kustomization.yaml`) it flags the app as incomplete. This is the same transient-state false positive noted in `reference_external_gitrepo_patches_pattern.md`. Ignore it as long as the final directory lists all resources.
