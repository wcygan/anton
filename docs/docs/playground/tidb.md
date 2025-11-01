---
sidebar_position: 2
sidebar_label: TiDB (Relational Database)
---

# TiDB

[TiDB](https://www.pingcap.com/en/products/tidb/) is an open-source distributed SQL database that remains MySQL compatible while scaling horizontally.

## Kubernetes Deployment

I use [TiDB Operator](https://github.com/pingcap/tidb-operator) on Kubernetes:

> TiDB Operator manages TiDB clusters on Kubernetes and automates tasks related to operating a TiDB cluster.
> 
> - Safely scaling the TiDB cluster
> - Rolling update of the TiDB cluster
> - Multi-tenant support
> - Automatic failover

Docs: https://docs.pingcap.com/tidb-in-kubernetes/stable/ + https://docs.pingcap.com/tidb-in-kubernetes/stable/deploy-tidb-operator/