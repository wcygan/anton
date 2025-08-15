# Loki + Alloy Troubleshooting Guide

## Overview

This guide provides systematic troubleshooting approaches for common issues in the Loki + Alloy logging stack deployment.

## Quick Diagnostic Commands

### Health Check Commands

```bash
# Overall cluster status
kubectl get pods -n monitoring -l 'app.kubernetes.io/name in (loki,alloy)' -o wide

# Check HelmRelease status
kubectl get hr -n monitoring loki alloy

# Check recent events
kubectl get events -n monitoring --sort-by=.lastTimestamp | tail -20

# Check resource usage
kubectl top pods -n monitoring -l 'app.kubernetes.io/name in (loki,alloy)'
```

### Log Analysis Commands

```bash
# Check Loki logs for errors
kubectl logs -n monitoring loki-0 -c loki | grep -E "(error|Error|ERROR|fail|Fail|FAIL)" | tail -20

# Check Alloy logs for collection issues
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy | grep -E "(error|Error|ERROR)" | tail -20

# Check gateway logs
kubectl logs -n monitoring -l app.kubernetes.io/name=loki,app.kubernetes.io/component=gateway | tail -20
```

## Common Issues and Solutions

### 1. Loki Pod Constantly Restarting

**Symptoms:**
- Loki pod shows high restart count
- Logs not being ingested
- Gateway returning 502/503 errors

**Diagnostic Steps:**

```bash
# Check pod status and restart reason
kubectl describe pod -n monitoring loki-0

# Check current logs
kubectl logs -n monitoring loki-0 -c loki --tail=100

# Check previous logs if pod restarted
kubectl logs -n monitoring loki-0 -c loki --previous --tail=100

# Check resource limits
kubectl describe pod -n monitoring loki-0 | grep -A 10 "Limits\|Requests"
```

**Common Causes and Solutions:**

#### A. Memory Limit Exceeded (OOMKilled)

```bash
# Check if pod was OOMKilled
kubectl describe pod -n monitoring loki-0 | grep -i oom

# Solution: Increase memory limits
kubectl patch helmrelease loki -n monitoring --type='merge' -p='{"spec":{"values":{"loki":{"resources":{"limits":{"memory":"4Gi"},"requests":{"memory":"2Gi"}}}}}}'
```

#### B. S3 Backend Connection Issues

```bash
# Test S3 connectivity from Loki namespace
kubectl run -it --rm s3-debug --namespace=monitoring \
  --image=amazon/aws-cli:latest --restart=Never -- \
  s3 ls --endpoint-url=http://rook-ceph-rgw-storage.storage.svc.cluster.local

# Check S3 credentials
kubectl get secret -n monitoring loki-s3-credentials -o yaml

# Check Ceph RGW status
kubectl get pods -n storage -l app=rook-ceph-rgw
```

**Solution for S3 Issues:**
```bash
# Recreate S3 credentials if needed
kubectl delete secret -n monitoring loki-s3-credentials
flux reconcile helmrelease loki -n monitoring

# Check ObjectStore health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
```

#### C. Configuration Errors

```bash
# Validate Loki configuration
kubectl logs -n monitoring loki-0 -c loki | grep -i "config\|invalid\|parse"

# Check for syntax errors in HelmRelease
kubectl get helmrelease loki -n monitoring -o yaml | yq '.spec.values'
```

### 2. No Logs Appearing in Grafana

**Symptoms:**
- Grafana shows "No data" for LogQL queries
- Loki appears healthy but no data visible
- Alloy pods running but not collecting logs

**Diagnostic Steps:**

```bash
# Test Loki API directly
kubectl port-forward -n monitoring svc/loki-gateway 3100:80 &
curl -s "http://localhost:3100/loki/api/v1/labels" | jq
curl -s "http://localhost:3100/loki/api/v1/query?query={namespace=\"monitoring\"}" | jq
pkill -f "kubectl port-forward.*loki"

# Check Alloy configuration
kubectl get configmap -n monitoring alloy -o yaml

# Test log ingestion with a test pod
kubectl run test-logger --image=busybox --restart=Never -- \
  sh -c 'while true; do echo "Test log from pod at $(date)"; sleep 5; done'
```

**Common Causes and Solutions:**

#### A. Alloy Configuration Issues

```bash
# Check Alloy discovery configuration
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy | grep -E "(discovery|kubernetes_pods)"

# Common fix: Restart Alloy DaemonSet
kubectl rollout restart daemonset/alloy -n monitoring

# Check Alloy is finding pods
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy | grep -E "(targets|discovered)"
```

#### B. Label or Filter Misconfigurations

```bash
# Check if logs are being filtered out
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy | grep -E "(drop|filter|exclude)"

# Temporarily disable filtering to test
kubectl patch helmrelease alloy -n monitoring --type='merge' -p='{"spec":{"values":{"alloy":{"config":{"clients":[{"url":"http://loki-gateway.monitoring.svc.cluster.local/loki/api/v1/push"}]}}}}}'
```

#### C. Grafana Data Source Configuration

```bash
# Port forward to Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &

# Check data source configuration at:
# http://localhost:3000/datasources
# Should point to: http://loki-gateway.monitoring.svc.cluster.local
```

### 3. High Query Latency or Timeouts

**Symptoms:**
- Grafana queries take >30 seconds
- Frequent query timeouts
- High CPU usage on Loki pods

**Diagnostic Steps:**

```bash
# Check query performance metrics
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
# Query: histogram_quantile(0.95, rate(loki_request_duration_seconds_bucket[5m]))

# Check for resource saturation
kubectl top pod -n monitoring loki-0

# Check for large time range queries
kubectl logs -n monitoring loki-0 -c loki | grep -E "query.*range.*"
```

**Solutions:**

#### A. Resource Scaling

```bash
# Increase Loki resources
kubectl patch helmrelease loki -n monitoring --type='merge' -p='{"spec":{"values":{"loki":{"resources":{"requests":{"cpu":"2","memory":"4Gi"},"limits":{"cpu":"4","memory":"8Gi"}}}}}}'

# Scale gateway replicas
kubectl patch helmrelease loki -n monitoring --type='merge' -p='{"spec":{"values":{"gateway":{"replicas":2}}}}'
```

#### B. Query Optimization

```bash
# Enable query caching in Loki
kubectl patch helmrelease loki -n monitoring --type='merge' -p='{"spec":{"values":{"loki":{"config":{"query_range":{"cache_results":true,"parallelise_shardable_queries":true}}}}}}'
```

### 4. Storage-Related Issues

**Symptoms:**
- "Failed to store chunks" errors
- S3 access denied errors
- Disk space warnings

**Diagnostic Steps:**

```bash
# Check Ceph cluster health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Check S3 bucket accessibility
kubectl -n storage exec deploy/rook-ceph-tools -- \
  radosgw-admin bucket stats --bucket=loki-chunks

# Check ObjectBucketClaim status
kubectl get obc -n monitoring loki-bucket -o yaml
```

**Solutions:**

#### A. Ceph Storage Issues

```bash
# Check OSD status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd status

# Check placement groups
kubectl -n storage exec deploy/rook-ceph-tools -- ceph pg stat

# If Ceph is degraded, wait for recovery or check Ceph documentation
```

#### B. S3 Credentials or Permissions

```bash
# Recreate S3 credentials
kubectl delete secret -n monitoring loki-s3-credentials

# Force reconciliation to recreate
flux reconcile kustomization monitoring -n flux-system

# Test S3 access manually
kubectl run -it --rm s3-test --namespace=monitoring \
  --image=minio/mc:latest --restart=Never -- \
  mc alias set ceph http://rook-ceph-rgw-storage.storage.svc.cluster.local \
  $(kubectl get secret loki-s3-credentials -n monitoring -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d) \
  $(kubectl get secret loki-s3-credentials -n monitoring -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d)
```

### 5. Alloy Collection Issues

**Symptoms:**
- Some pods' logs not appearing
- Alloy pods showing errors
- Partial log collection

**Diagnostic Steps:**

```bash
# Check Alloy DaemonSet status
kubectl get daemonset alloy -n monitoring

# Check if Alloy is running on all nodes
kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy -o wide

# Check Alloy configuration
kubectl describe configmap alloy -n monitoring
```

**Solutions:**

#### A. DaemonSet Not Scheduled on All Nodes

```bash
# Check node taints and tolerations
kubectl describe nodes | grep -E "(Taints:|Name:)"

# Update Alloy tolerations if needed
kubectl patch helmrelease alloy -n monitoring --type='merge' -p='{"spec":{"values":{"alloy":{"tolerations":[{"operator":"Exists"}]}}}}'
```

#### B. Permission Issues

```bash
# Check ServiceAccount permissions
kubectl auth can-i get pods --as=system:serviceaccount:monitoring:alloy -n monitoring

# Verify RBAC configuration
kubectl get clusterrole alloy -o yaml
kubectl get clusterrolebinding alloy -o yaml
```

### 6. Network Connectivity Issues

**Symptoms:**
- Connection refused errors
- DNS resolution failures
- Service discovery problems

**Diagnostic Steps:**

```bash
# Test internal DNS resolution
kubectl run -it --rm dns-test --image=busybox --restart=Never -- \
  nslookup loki-gateway.monitoring.svc.cluster.local

# Test service connectivity
kubectl run -it --rm network-test --image=nicolaka/netshoot --restart=Never -- \
  curl -I http://loki-gateway.monitoring.svc.cluster.local

# Check service endpoints
kubectl get endpoints -n monitoring loki-gateway
```

**Solutions:**

#### A. Service Configuration

```bash
# Check service configuration
kubectl get svc -n monitoring loki-gateway -o yaml

# Verify pods are selected by service
kubectl get pods -n monitoring -l app.kubernetes.io/name=loki,app.kubernetes.io/component=gateway --show-labels
```

#### B. Network Policy Issues

```bash
# Check for network policies blocking traffic
kubectl get networkpolicy -A

# Temporarily disable network policies for testing
kubectl delete networkpolicy -n monitoring --all
```

## Emergency Recovery Procedures

### Complete Stack Restart

```bash
# 1. Scale down to zero
kubectl scale statefulset loki --replicas=0 -n monitoring
kubectl scale daemonset alloy --replicas=0 -n monitoring

# 2. Wait for pods to terminate
kubectl wait --for=delete pod -l app.kubernetes.io/name=loki -n monitoring --timeout=300s

# 3. Scale back up
kubectl scale statefulset loki --replicas=1 -n monitoring
kubectl scale daemonset alloy --replicas=3 -n monitoring
```

### Configuration Reset

```bash
# 1. Suspend HelmReleases
flux suspend helmrelease loki -n monitoring
flux suspend helmrelease alloy -n monitoring

# 2. Reset to known good configuration
git checkout HEAD~1 -- kubernetes/apps/monitoring/loki/
git checkout HEAD~1 -- kubernetes/apps/monitoring/alloy/

# 3. Commit and resume
git commit -m "revert: reset logging stack to known good state"
git push
flux resume helmrelease loki -n monitoring
flux resume helmrelease alloy -n monitoring
```

### Data Recovery

```bash
# If S3 data is intact but Loki needs rebuild
kubectl delete pvc -n monitoring storage-loki-0

# Force recreation
kubectl delete pod -n monitoring loki-0

# Wait for Loki to rebuild index from S3
kubectl logs -n monitoring loki-0 -c loki -f
```

## Performance Monitoring

### Key Metrics to Watch

```bash
# Query latency
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
# Query: histogram_quantile(0.95, rate(loki_request_duration_seconds_bucket[5m]))

# Ingestion rate
# Query: rate(loki_ingester_streams_created_total[5m])

# Error rate
# Query: rate(loki_request_total{status_code!~"2.."}[5m])

# Resource usage
kubectl top pods -n monitoring -l app.kubernetes.io/name=loki
```

### Alerting Thresholds

Set up alerts for:
- Query latency P95 > 5 seconds
- Error rate > 5%
- No logs ingested for > 10 minutes
- Loki pod restart frequency > 1/hour

## Getting Help

### Gathering Debug Information

```bash
# Create debug bundle
mkdir loki-debug-$(date +%Y%m%d-%H%M)
cd loki-debug-$(date +%Y%m%d-%H%M)

# Collect pod status
kubectl get pods -n monitoring -o yaml > pods.yaml

# Collect logs
kubectl logs -n monitoring loki-0 > loki.log
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy > alloy.log

# Collect configurations
kubectl get helmrelease loki alloy -n monitoring -o yaml > helmreleases.yaml
kubectl get configmap -n monitoring -o yaml > configmaps.yaml

# Collect events
kubectl get events -n monitoring --sort-by=.lastTimestamp > events.log

# Test connectivity
kubectl run -it --rm debug --image=nicolaka/netshoot --restart=Never -- \
  curl -v http://loki-gateway.monitoring.svc.cluster.local/ready > connectivity.log 2>&1
```

### Useful Documentation Links

- [Loki Configuration Reference](https://grafana.com/docs/loki/latest/configuration/)
- [Alloy Configuration Blocks](https://grafana.com/docs/alloy/latest/reference/components/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/logql/)
- [Ceph Troubleshooting](https://docs.ceph.com/en/latest/rados/troubleshooting/)

---

**Important Notes:**
- Always check recent git commits for configuration changes
- Monitor resource usage when making changes
- Test changes in development namespace first when possible
- Keep debug logs for pattern analysis

**Last Updated**: 2025-06-15  
**Version**: 1.0