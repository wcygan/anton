---
sidebar_position: 3
sidebar_label: Dragonfly (Cache)
---

# Dragonfly

[Dragonfly](https://www.dragonflydb.io/) is a drop-in Redis alternative that delivers multi-threaded, in-memory caching for large-scale workloads.

## Kubernetes Deployment

I use [Dragonfly Operator](https://github.com/dragonflydb/dragonfly-operator) on Kubernetes:

> Dragonfly Operator is a Kubernetes operator used to deploy and manage Dragonfly instances inside your Kubernetes clusters. Main features include:
>
> - Automatic failover
> - Scaling horizontally and vertically with custom rollout strategy
> - Authentication and server TLS
> - Automatic snapshots to PVCs and S3
> - Monitoring with Prometheus and Grafana

Docs: https://www.dragonflydb.io/docs/managing-dragonfly/operator/installation