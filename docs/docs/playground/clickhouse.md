---
sidebar_position: 6
sidebar_label: Clickhouse (Analytics)
---

# Clickhouse

[ClickHouse](https://clickhouse.com/) is a high-performance open-source columnar OLAP database built for real-time analytics.

## Kubernetes Deployment

I use [Altinity ClickHouse Operator](https://github.com/Altinity/clickhouse-operator) on Kubernetes:

> The Altinity Kubernetes Operator for ClickHouse creates, configures and manages ClickHouse clusters running on Kubernetes.
> 
> - Creates ClickHouse clusters defined as custom resources
> - Customized storage provisioning (VolumeClaim templates)
> - Customized pod templates
> - ClickHouse cluster scaling including automatic schema propagation
> - Exporting ClickHouse metrics to Prometheus

Docs: https://github.com/Altinity/clickhouse-operator/blob/master/docs/operator_installation_details.md