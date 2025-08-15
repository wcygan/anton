# Why Loki and Alloy?

## Problem Statement

I want to view the logs of my Airflow pods, but I can't currently do that because:
- Airflow logs are stored on persistent volumes (PVCs)
- Log volumes are growing rapidly (100Gi+ usage)
- No centralized log aggregation or search capability
- Debugging requires manual pod access

## Solution: Loki + Alloy

Loki and Alloy provide a modern, production-grade logging solution:

### Loki
- **Purpose**: Horizontally scalable, multi-tenant log aggregation system
- **Design**: Cost-effective storage using object storage (S3/Ceph)
- **Integration**: Native Grafana integration for visualization
- **Source**: https://github.com/grafana/loki

### Alloy
- **Purpose**: Modern replacement for Promtail as the log collection agent
- **Design**: Unified telemetry collector with flow-based configuration
- **Benefits**: More flexible and powerful than Promtail
- **Source**: https://github.com/grafana/alloy

## Benefits

1. **Centralized Logging**: All pod logs accessible from a single interface
2. **Cost Efficiency**: S3 storage is cheaper than PVC storage
3. **Scalability**: Loki scales horizontally for high log volumes
4. **Search Performance**: Fast log queries with LogQL
5. **Integration**: Works seamlessly with existing Grafana dashboards
6. **Modern Architecture**: Alloy is the future-forward choice for log collection