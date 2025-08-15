# Loki + Alloy Operations Runbook

## Overview

This runbook provides operational procedures for the Loki + Alloy centralized logging stack deployed in the homelab. The stack consists of:

- **Loki**: Log aggregation and storage (SingleBinary mode with S3 backend)
- **Alloy**: Log collection agent (DaemonSet on all nodes)
- **Gateway**: Load balancer for Loki (NGINX)
- **Storage**: Ceph S3 ObjectStore for log data
- **Monitoring**: Grafana integration with dashboards and alerts

## Daily Operations

### Health Checks

```bash
# Check all logging components
kubectl get pods -n monitoring -l 'app.kubernetes.io/name in (loki,alloy)'

# Expected output:
# alloy-xxxxx    2/2 Running (3 pods across nodes)
# loki-0         2/2 Running (1 pod)
# loki-gateway-* 1/1 Running (1 pod)
# loki-canary-*  1/1 Running (3 pods)
```

### Log Ingestion Status

```bash
# Check Alloy is collecting logs
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy --tail=50 | grep -E "(sent|error)"

# Check Loki ingestion rate
kubectl port-forward -n monitoring svc/loki-gateway 3100:80 &
curl -s http://localhost:3100/metrics | grep loki_ingester_streams_created_total
pkill -f "kubectl port-forward.*loki"
```

### Storage Usage

```bash
# Check S3 bucket usage via Ceph
kubectl -n storage exec deploy/rook-ceph-tools -- \
  radosgw-admin bucket stats --bucket=loki-chunks

# Check ObjectBucketClaim status
kubectl get obc -n monitoring loki-bucket -o yaml
```

## Weekly Operations

### Log Retention Review

```bash
# Check current retention policy (7 days default)
kubectl get secret -n monitoring loki-s3-credentials -o yaml

# Review log volume trends
kubectl port-forward -n monitoring svc/loki-gateway 3100:80 &
curl -s "http://localhost:3100/loki/api/v1/query_range?query={namespace!=\"\"}&start=$(date -d '7 days ago' -u +%s)000000000&end=$(date -u +%s)000000000&step=3600" | jq '.data.result | length'
pkill -f "kubectl port-forward.*loki"
```

### Performance Monitoring

```bash
# Check query performance metrics
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
# Navigate to: http://localhost:9090/graph
# Query: histogram_quantile(0.95, rate(loki_request_duration_seconds_bucket[5m]))
pkill -f "kubectl port-forward.*prometheus"

# Check Loki resource usage
kubectl top pod -n monitoring -l app.kubernetes.io/name=loki
```

## Emergency Procedures

### Loki Pod Restart Loop

**Symptoms**: Loki pod constantly restarting, logs not being ingested

```bash
# Check pod status and events
kubectl describe pod -n monitoring loki-0

# Check logs for errors
kubectl logs -n monitoring loki-0 -c loki --previous

# Common fixes:
# 1. S3 connectivity issues
kubectl -n storage exec deploy/rook-ceph-tools -- \
  s3cmd ls s3://loki-chunks --host=rook-ceph-rgw-storage.storage.svc.cluster.local:80

# 2. Resource constraints
kubectl patch helmrelease loki -n monitoring --type='merge' -p='{"spec":{"values":{"loki":{"resources":{"requests":{"memory":"2Gi"},"limits":{"memory":"4Gi"}}}}}}'

# 3. Force recreation
kubectl delete pod -n monitoring loki-0
```

### Alloy Collection Failure

**Symptoms**: No new logs appearing in Grafana

```bash
# Check Alloy pod status on all nodes
kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy -o wide

# Check Alloy configuration
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy | grep -E "(error|failed)"

# Restart Alloy DaemonSet
kubectl rollout restart daemonset/alloy -n monitoring
```

### S3 Storage Issues

**Symptoms**: Loki failing to write chunks, storage errors in logs

```bash
# Check Ceph cluster health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Check RGW service
kubectl get svc -n storage rook-ceph-rgw-storage

# Test S3 connectivity from monitoring namespace
kubectl run -it --rm s3-test --namespace=monitoring \
  --image=amazon/aws-cli:latest --restart=Never -- \
  s3 ls --endpoint-url=http://rook-ceph-rgw-storage.storage.svc.cluster.local
```

### Complete Log Ingestion Failure

**Symptoms**: No logs visible in Grafana for extended period

```bash
# 1. Check Loki API health
kubectl port-forward -n monitoring svc/loki-gateway 3100:80 &
curl -s http://localhost:3100/ready
curl -s http://localhost:3100/metrics | head -20
pkill -f "kubectl port-forward.*loki"

# 2. Check Grafana data source
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &
# Navigate to: http://localhost:3000/datasources
# Test Loki data source connectivity
pkill -f "kubectl port-forward.*grafana"

# 3. Force reconciliation
flux reconcile helmrelease loki -n monitoring
flux reconcile helmrelease alloy -n monitoring
```

## Backup and Recovery

### Backup Procedures

```bash
# 1. Export HelmRelease configurations
kubectl get helmrelease loki -n monitoring -o yaml > loki-backup.yaml
kubectl get helmrelease alloy -n monitoring -o yaml > alloy-backup.yaml

# 2. Export secrets
kubectl get secret loki-s3-credentials -n monitoring -o yaml > loki-secrets-backup.yaml

# 3. Document S3 bucket contents
kubectl -n storage exec deploy/rook-ceph-tools -- \
  radosgw-admin bucket list --bucket=loki-chunks > loki-chunks-inventory.txt
```

### Recovery Procedures

```bash
# 1. Recreate from backup
kubectl apply -f loki-backup.yaml
kubectl apply -f alloy-backup.yaml
kubectl apply -f loki-secrets-backup.yaml

# 2. Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=loki -n monitoring --timeout=300s

# 3. Validate functionality
./scripts/logging-functional-test.ts
```

## Performance Tuning

### Scaling Guidelines

**When to Scale Up:**
- Query latency consistently >2s
- CPU usage >80% on Loki pods
- Memory usage >90% on Loki pods
- Log ingestion backlog growing

**Scaling Commands:**
```bash
# Increase Loki resources
kubectl patch helmrelease loki -n monitoring --type='merge' -p='{"spec":{"values":{"loki":{"resources":{"requests":{"cpu":"2","memory":"4Gi"},"limits":{"cpu":"4","memory":"8Gi"}}}}}}'

# Scale gateway replicas
kubectl patch helmrelease loki -n monitoring --type='merge' -p='{"spec":{"values":{"gateway":{"replicas":3}}}}'
```

### Query Optimization

**Common Slow Queries to Avoid:**
- Large time ranges without filters: `{namespace=""} |~ "error"`
- Regex without anchoring: `{namespace="app"} |~ ".*error.*"`
- No log level filtering: `{namespace="app"}`

**Optimized Query Patterns:**
- Use label filters: `{namespace="app",pod=~"frontend.*"} |= "error"`
- Limit time ranges: Last 1h instead of 24h
- Use structured logging: `{namespace="app"} | json | level="error"`

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Loki Ingestion Rate**: `rate(loki_ingester_streams_created_total[5m])`
2. **Query Latency**: `histogram_quantile(0.95, rate(loki_request_duration_seconds_bucket[5m]))`
3. **Error Rate**: `rate(loki_request_total{status_code!~"2.."}[5m])`
4. **Storage Usage**: Monitor S3 bucket size and growth rate

### Alert Thresholds

- **Critical**: No logs ingested for >10 minutes
- **Warning**: Query latency P95 >2 seconds
- **Warning**: Error rate >5%
- **Info**: Storage usage growth >10GB/day

## Configuration Management

### Update Procedures

```bash
# 1. Make changes to HelmRelease values
vi kubernetes/apps/monitoring/loki/app/helmrelease.yaml

# 2. Commit changes
git add -A && git commit -m "feat(logging): update Loki configuration"

# 3. Push and reconcile
git push && flux reconcile helmrelease loki -n monitoring

# 4. Monitor deployment
kubectl rollout status statefulset/loki -n monitoring
```

### Rollback Procedures

```bash
# 1. Check Helm history
helm history loki -n monitoring

# 2. Rollback to previous version
helm rollback loki -n monitoring

# 3. Or use Flux
flux suspend helmrelease loki -n monitoring
# Revert git changes
flux resume helmrelease loki -n monitoring
```

## Capacity Planning

### Current Resource Usage

```bash
# Check current allocation
kubectl describe pod loki-0 -n monitoring | grep -A 10 "Requests\|Limits"

# Check actual usage
kubectl top pod loki-0 -n monitoring
```

### Growth Projections

- **Current**: ~25GB logs/week (based on test workloads)
- **Projected**: 100GB/week at full application deployment
- **Storage**: S3 with compression (10:1 ratio expected)
- **Retention**: 7 days default (configurable per namespace)

## Contact Information

- **On-call**: Check cluster monitoring dashboards first
- **Escalation**: Review troubleshooting guide
- **Documentation**: `docs/logging-stack/`
- **Configuration**: `kubernetes/apps/monitoring/loki/` and `kubernetes/apps/monitoring/alloy/`

---

**Last Updated**: 2025-06-15  
**Version**: 1.0  
**Next Review**: Weekly during initial 30-day period