# ClickStack experiment — retired

The ClickStack experiment is historical and is no longer under review. Its
managed source-of-truth manifests were removed when the cluster's durable
Kubernetes pod-log path moved to the OTel Collector DaemonSet and monolithic
Loki. The experiment evaluated ClickHouse, Keeper, MongoDB, HyperDX, and a
narrow homepage-only collector; it did not become the production log backend.

The successor architecture, retention contract, queries, rollout order, and
operator-only teardown procedure are maintained in the canonical
[Kubernetes logs: OTel Collector to Loki runbook](../runbooks/kubernetes-logs-loki.md)
and [ADR 0032](https://github.com/wcygan/anton/blob/main/context/adrs/0032-honor-loki-stream-retention-minimum.md).

The separate temporary Talos log sink remains in place. It is not the
Kubernetes pod-log backend and is intentionally not removed by this migration.
Live ClickStack teardown, including any namespace, PVC, or storage helper
cleanup, requires explicit operator approval; no live mutation was performed
as part of this source-of-truth change.
