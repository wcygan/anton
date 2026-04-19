---
name: whereabouts upstream YAML quirks
description: Layout traps when installing k8snetworkplumbingwg/whereabouts via external-GitRepository-with-patches; extra CRDs in doc/crds and a floating :latest image
type: reference
---

When consuming `k8snetworkplumbingwg/whereabouts` (tested at v0.9.3) via the external GitRepository + inner Flux Kustomization pattern, `doc/crds/` is NOT just the three files the README install snippet implies — it also ships `node-slice-controller.yaml` and `whereabouts.cni.cncf.io_nodeslicepools.yaml`, which are only needed if you enable the optional node-slice controller. Pointing `path: ./doc/crds` at the whole directory will pull all five.

Mitigation: restrict the GitRepository via `ignore:` so the artifact only contains the three files you actually want:

```yaml
ignore: |
  /*
  !/doc/crds/daemonset-install.yaml
  !/doc/crds/whereabouts.cni.cncf.io_ippools.yaml
  !/doc/crds/whereabouts.cni.cncf.io_overlappingrangeipreservations.yaml
```

Second quirk: `daemonset-install.yaml` pins `image: ghcr.io/k8snetworkplumbingwg/whereabouts:latest` — floating tag. Unlike Multus which already hardcodes a release tag in its daemonset YAML, whereabouts requires a `spec.patches` image replace to pin the image. Use two Renovate annotations: one on the GitRepository `tag:` (`datasource=github-releases depName=k8snetworkplumbingwg/whereabouts`) and one on the image `value:` (`datasource=docker depName=ghcr.io/k8snetworkplumbingwg/whereabouts`).

Resource names to target with patches (v0.9.3):
- ServiceAccount `whereabouts` (namespace → network)
- ConfigMap `whereabouts-config` (namespace → network, used by DaemonSet for cron schedule)
- DaemonSet `whereabouts` (namespace → network, image pin)
- ClusterRoleBinding `whereabouts` (subjects[0].namespace → network)
- ClusterRole `whereabouts-cni` (cluster-scoped, no patch needed)
- CRDs `ippools.whereabouts.cni.cncf.io`, `overlappingrangeipreservations.whereabouts.cni.cncf.io` (cluster-scoped, no patch needed)

Exemplar: `kubernetes/apps/network/whereabouts/` (added 2026-04-19, plan 0004 Phase 4a).
