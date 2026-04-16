---
name: longhorn-data-locality
description: When to override Longhorn data locality per-volume in anton.
---

# Data locality tuning

Canonical: https://longhorn.io/docs/1.11.1/best-practices/#setting-up-default-parameters

Anton default: `best-effort`. Workloads get a local replica when scheduling permits, but anti-affinity is preserved.

## When to keep `best-effort` (default)

- Stateful workloads that tolerate occasional cross-node reads (most of them).
- Anything that benefits from resilience over peak read latency.

## When to consider `strict-local`

Almost never on anton. It ties volume availability to a single node and breaks the anti-affinity that keeps replicas on different nodes. If you find yourself reaching for it, first ask whether the workload should instead use a local hostPath.

## When to consider `disabled`

Workloads where the attaching pod migrates frequently and local-replica rebuild churn costs more than the latency savings.

## Override per-volume

Author a **custom StorageClass** with `parameters.dataLocality: <value>`. Don't edit the `longhorn` SC in place — it is managed by the HelmRelease and changes will be reverted on the next reconcile.

## `numberOfReplicas` pairing

If you change `dataLocality`, think about replica count too. `strict-local` + 1 replica is a hostPath with extra steps. `strict-local` + 3 replicas on anton forces replicas onto all three nodes, which only works while k8s-2 has headroom.
