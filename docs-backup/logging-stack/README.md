# Loki + Alloy Logging Stack Documentation

## Overview

This documentation provides comprehensive guidance for deploying and operating a centralized logging solution using Grafana Loki and Alloy (formerly Grafana Agent) in the Kubernetes homelab environment.

## MCP Server Usage for Development

When working with the logging stack, leverage MCP servers for accurate, documentation-based implementation:

### Fetching Official Documentation
```bash
# Get Loki documentation
/mcp context7:resolve-library-id loki
/mcp context7:get-library-docs /grafana/loki "simple scalable mode" 5000

# Get Alloy documentation
/mcp context7:resolve-library-id alloy
/mcp context7:get-library-docs /grafana/alloy "kubernetes logs" 5000

# Get S3 configuration examples
/mcp context7:get-library-docs /grafana/loki "s3 storage configuration" 3000
```

### Complex Decision Making
```bash
# Analyze deployment mode selection
/mcp sequential-thinking:sequential_thinking "Given a 3-node cluster with 100GB daily log volume, compare Loki deployment modes (monolithic vs simple scalable vs microservices) considering performance, operational complexity, and resource usage"

# Design retention strategy
/mcp sequential-thinking:sequential_thinking "Design a log retention policy for Airflow logs (high value, 100GB/day) vs system logs (low value, 10GB/day) optimizing for cost and compliance"
```

### Real-time Cluster Inspection
```bash
# Check current storage status before deployment
/mcp kubernetes:kubectl_get "cephobjectstore" "storage" "storage"
/mcp kubernetes:kubectl_get "pods" "storage" "-l app=rook-ceph-rgw"

# Monitor deployment progress
/mcp kubernetes:kubectl_get "helmrelease" "monitoring" "-l app.kubernetes.io/name=loki"
/mcp kubernetes:kubectl_logs "monitoring" "loki-read-0" "--tail=50"
```

## Current Status

**Status**: PENDING - CLEAN SLATE IMPLEMENTATION  
**Last Updated**: January 2025  
**Version**: 2.0
**Deployment Approach**: S3-First with Loki + Alloy (Production)

### Key Highlights
- **Trigger Met**: All deployment conditions satisfied (100Gi Airflow logs)
- **Architecture**: Simple Scalable mode selected for production readiness
- **Storage**: S3-First approach - Ceph S3 must be enabled before deployment
- **Log Agent**: Alloy (modern Grafana agent) instead of deprecated Promtail
- **Clean Slate**: Previous quickstart deployment removed for proper implementation

## Documentation Structure

### Bootstrap Guides
1. **[00-s3-prerequisites.md](bootstrap/00-s3-prerequisites.md)** - S3 setup guide (MUST complete first)
2. **[00-readiness.md](bootstrap/00-readiness.md)** - Infrastructure validation and requirements
3. **[01-planning.md](bootstrap/01-planning.md)** - Architecture design and deployment strategy
4. **[02-implementation-guide.md](bootstrap/02-implementation-guide.md)** - Step-by-step deployment instructions
5. **[03-goals.json](bootstrap/03-goals.json)** - Structured objectives and success metrics

### Setup Guides
- **[airflow-vector-sidecar.md](setup/airflow-vector-sidecar.md)** - Vector sidecar pattern for ephemeral pods

### Operations Guides (To Be Created)
- `operations/daily-health-check.md` - Daily operational tasks
- `operations/troubleshooting.md` - Common issues and solutions
- `operations/logql-queries.md` - Useful query patterns
- `operations/retention-management.md` - Storage and retention policies
- `operations/performance-tuning.md` - Optimization guidelines

### Example Configurations (To Be Created)
- `examples/namespace-filtering.yaml` - Filter logs by namespace
- `examples/json-parsing.yaml` - Parse structured JSON logs
- `examples/airflow-config.yaml` - Airflow-specific configuration
- `examples/alerting-rules.yaml` - Log-based alerting

## Quick Links

### For Immediate Action
- **Quick Deploy**: Start with [04-quickstart.md](bootstrap/04-quickstart.md) for fastest deployment
- **Full Deploy**: Follow [02-implementation-guide.md](bootstrap/02-implementation-guide.md) for production setup
- **Check Status**: Review [03-goals.json](bootstrap/03-goals.json) for current progress

### Key Decisions Made
- **Mode**: Simple Scalable (not Monolithic) for future growth
- **Agent**: Alloy (not Promtail) as Promtail enters EOL
- **Storage**: Ceph S3 (not filesystem) for production reliability
- **Deployment**: Phased rollout starting with test namespaces

## Problem Statement

### Current Pain Points
1. **Airflow Logs**: Using expensive 100Gi PVC for local file storage
2. **No Correlation**: Cannot search logs across services
3. **Limited Visibility**: Each app manages its own logs
4. **Debugging Difficulty**: No centralized search capability

### Solution Benefits
1. **Centralized Access**: All logs in one place via Grafana
2. **Cost Efficiency**: 10:1 compression ratio vs block storage
3. **Powerful Queries**: LogQL for complex log analysis
4. **Long Retention**: 30+ days of searchable logs
5. **Correlation**: Link logs with metrics and traces

## Architecture Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Pod Logs  │────▶│    Alloy    │────▶│    Loki     │
└─────────────┘     └─────────────┘     └─────────────┘
                          │                      │
                          ▼                      ▼
                    ┌─────────────┐       ┌─────────────┐
                    │  Prometheus │       │  Ceph S3    │
                    └─────────────┘       └─────────────┘
                                                 │
                                                 ▼
                                          ┌─────────────┐
                                          │   Grafana   │
                                          └─────────────┘
```

## Deployment Checklist

### Prerequisites
- [x] Kubernetes 1.24+ (Talos Linux)
- [x] **Ceph cluster with S3 gateway enabled and operational** (see [S3 Prerequisites Guide](bootstrap/00-s3-prerequisites.md))
- [x] Grafana via kube-prometheus-stack
- [x] External Secrets Operator
- [x] Resource capacity (15.5Gi RAM needed)

### Implementation Steps

#### Step 0: S3 Prerequisites (Required for Production)
- [ ] Enable Ceph ObjectStore (rename `ks.yaml.disabled` to `ks.yaml`)
- [ ] Verify S3 gateway is operational
- [ ] Validate S3 connectivity and create test bucket
- [ ] Configure S3 credentials in External Secrets

#### Production Deployment (S3-First Approach)
- [ ] Add Grafana Helm repository
- [ ] Deploy Loki (Simple Scalable mode with S3 backend)
- [ ] Deploy Alloy (DaemonSet)
- [ ] Configure Grafana data source
- [ ] Import dashboards
- [ ] Test log ingestion
- [ ] Migrate Airflow logs
- [ ] Implement retention policies
- [ ] Document operations

**Note**: For immediate testing without S3, see [Quick Start Guide](bootstrap/04-quickstart.md) - not suitable for production

## Resource Requirements

### Minimum (Monolithic Mode)
- **Loki**: 1 replica, 1 CPU, 2Gi RAM, 50Gi storage
- **Alloy**: DaemonSet, 0.5 CPU, 512Mi RAM per node
- **Total**: ~2.5 CPU, 3.5Gi RAM

### Recommended (Simple Scalable)
- **Loki Write**: 3 replicas, 3 CPU, 6Gi RAM
- **Loki Read**: 3 replicas, 3 CPU, 6Gi RAM  
- **Loki Backend**: 1 replica, 0.5 CPU, 1Gi RAM
- **Gateway**: 2 replicas, 1 CPU, 1Gi RAM
- **Alloy**: 3 nodes, 1.5 CPU, 1.5Gi RAM
- **Total**: 9 CPU, 15.5Gi RAM

## Common Operations

### View Logs in Grafana
1. Navigate to Explore
2. Select "Loki" data source
3. Use LogQL queries:
   ```logql
   {namespace="airflow"}
   {pod=~"airflow-.*"} |~ "ERROR"
   {container="scheduler"} | json | level="error"
   ```

### Check System Health
```bash
# Loki status
kubectl get pods -n monitoring -l app.kubernetes.io/name=loki

# Alloy status  
kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy

# Ingestion rate
curl -s http://loki.monitoring:3100/metrics | grep loki_distributor_bytes_received_total
```

### Troubleshooting
```bash
# No logs appearing
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy

# Loki errors
kubectl logs -n monitoring -l app.kubernetes.io/name=loki

# Force restart
kubectl rollout restart deployment/loki-read -n monitoring
```

## Migration Timeline

### Week 1: Deployment
- Days 1-2: Infrastructure setup
- Days 3-4: Loki and Alloy deployment
- Days 5-7: Testing and validation

### Week 2: Migration
- Days 8-10: Parallel running with Airflow
- Days 11-12: Dashboard creation
- Days 13-14: Team training

### Week 3: Optimization
- Days 15-17: Performance tuning
- Days 18-19: Retention policy implementation
- Days 20-21: Documentation completion

### Week 4: Handoff
- Full cutover from PVC logging
- Decommission 100Gi Airflow PVC
- Operational handoff

## Support and References

### Internal Documentation
- [Why Loki + Alloy](why-loki-alloy.md) - Problem statement and solution benefits
- [Setup Guide](setup/how-to-add-loki-alloy.md) - Detailed deployment instructions
- [Recovery Plan](recovery-plan.md) - Disaster recovery procedures
- Airflow Examples: [examples/airflow-logql-queries.md](examples/airflow-logql-queries.md)
- PLAN.md: Phase 4 includes Loki deployment

### External Resources
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Alloy Documentation](https://grafana.com/docs/alloy/latest/)
- [LogQL Guide](https://grafana.com/docs/loki/latest/logql/)
- [Helm Chart Docs](https://grafana.com/docs/loki/latest/setup/install/helm/)

### Community
- [Grafana Community Forums](https://community.grafana.com/c/grafana-loki/)
- [Loki Slack Channel](https://slack.grafana.com/)
- [GitHub Issues](https://github.com/grafana/loki/issues)

## Contributing

To update this documentation:
1. Follow the existing structure
2. Update version and date in metadata
3. Test all commands before documenting
4. Include troubleshooting for known issues
5. Keep examples practical and tested

---

**Documentation Version**: 1.0  
**Maintainer**: Homelab Team  
**Next Review**: After deployment completion