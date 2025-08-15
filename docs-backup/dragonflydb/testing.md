# DragonflyDB Testing Guide

This guide documents how to deploy, configure, and test DragonflyDB instances in
your Kubernetes cluster.

## Overview

This testing framework demonstrates:

- Deploying Dragonfly cache instances using the operator
- Configuring storage with snapshots
- Testing Redis-compatible operations
- Monitoring performance and resource usage
- Validating cluster functionality

## Prerequisites

Before testing, ensure:

1. **DragonflyDB Operator** is installed and running (see `operator-install.md`)
2. **Storage Class** is available (`local-path` for persistent snapshots)
3. **Flux** is operational for GitOps deployment

**Current Status:**

- DragonflyDB Version: v1.28.1 (note: v1.30.3 is available)
- Test Instance: `test-cache` in `database` namespace
- Storage: 1Gi persistent storage via local-path StorageClass

## Test Instance Configuration

### Current Test Setup

The cluster includes a pre-configured test instance at
`kubernetes/apps/database/test-cache/`:

**Instance Specification** (`dragonfly.yaml`):

```yaml
apiVersion: dragonflydb.io/v1alpha1
kind: Dragonfly
metadata:
  name: test-cache
  namespace: database
spec:
  replicas: 1 # Single instance for testing

  # Resource limits for testing environment
  resources:
    requests:
      cpu: "100m"
      memory: "256Mi"
    limits:
      cpu: "500m"
      memory: "512Mi"

  # Persistent storage for snapshots
  snapshot:
    persistentVolumeClaimSpec:
      accessModes:
        - ReadWriteOnce
      resources:
        requests:
          storage: "1Gi"
      storageClassName: "local-path"

  # Testing environment variables
  env:
    - name: DRAGONFLY_MEMORY_STATS
      value: "true"
```

### Flux Integration

**Deployment Configuration** (`ks.yaml`):

- **Dependency**: Waits for `dragonfly-operator` to be ready
- **Interval**: 30m (standard for applications)
- **Health Check**: Monitors the `Dragonfly` CRD status
- **Timeout**: 10m (allows time for cache provisioning)

## Testing Procedures

### 1. Deploy Test Instance

The test instance is automatically deployed via Flux:

```bash
# Force reconciliation if needed
flux reconcile kustomization cluster-apps -n flux-system --with-source

# Check deployment status
flux get kustomization test-cache -n flux-system
flux describe kustomization test-cache -n flux-system
```

### 2. Verify Instance Health

```bash
# Check Dragonfly custom resource
kubectl get dragonfly test-cache -n database
kubectl describe dragonfly test-cache -n database

# Check pods created by operator
kubectl get pods -n database -l app=test-cache

# Check services
kubectl get services -n database -l app=test-cache

# Check persistent volume claims
kubectl get pvc -n database | grep test-cache
```

### 3. Connect to Dragonfly Instance

Get connection information:

```bash
# Get service details
kubectl get svc -n database -l app=test-cache

# Port forward for local testing
kubectl port-forward -n database svc/test-cache 6379:6379
```

### 4. Redis Compatibility Testing

Use Redis CLI or any Redis-compatible client:

```bash
# Install redis-cli (if not available)
# On macOS: brew install redis
# On Ubuntu: sudo apt-get install redis-tools

# Connect via port-forward (run in separate terminal)
kubectl port-forward -n database svc/test-cache 6379:6379

# In another terminal, connect with redis-cli
redis-cli -h localhost -p 6379

# Basic operations (run these in the redis-cli prompt)
SET test-key "Hello DragonflyDB"
GET test-key
KEYS *
INFO memory
INFO server
PING
```

**Alternative: Direct Pod Access**

```bash
# Execute Redis commands directly in the pod (useful for automation)
# Note: Use shell quoting for values with spaces
kubectl exec -n database pod/test-cache-0 -- sh -c 'redis-cli ping'
kubectl exec -n database pod/test-cache-0 -- sh -c 'redis-cli set test-key "Hello DragonflyDB"'
kubectl exec -n database pod/test-cache-0 -- sh -c 'redis-cli get test-key'
kubectl exec -n database pod/test-cache-0 -- sh -c 'redis-cli keys "*"'

# Interactive mode for more complex operations
kubectl exec -n database -it pod/test-cache-0 -- redis-cli
```

### 5. Performance Testing

#### Memory Usage Test

```bash
# First ensure port-forward is running:
# kubectl port-forward -n database svc/test-cache 6379:6379

# Set multiple keys to test memory usage
redis-cli -h localhost -p 6379 --eval - <<EOF
for i=1,1000 do
    redis.call('SET', 'key:' .. i, 'value:' .. i)
end
return 'OK'
EOF

# Check memory statistics
redis-cli -h localhost -p 6379 INFO memory
```

#### Throughput Test

```bash
# First ensure port-forward is running:
# kubectl port-forward -n database svc/test-cache 6379:6379

# Basic benchmark (requires redis-cli tools)
redis-benchmark -h localhost -p 6379 -t set,get -n 10000 -c 10

# Custom throughput test
redis-cli -h localhost -p 6379 --latency -i 1
```

### 6. Persistence Testing

Test snapshot functionality:

```bash
# Add test data
redis-cli -h localhost -p 6379 SET persistent-key "test-data"
redis-cli -h localhost -p 6379 BGSAVE

# Check snapshot files in PVC
kubectl exec -n database -it statefulset/test-cache -- ls -la /dragonfly/snapshots/

# Restart pod and verify data persistence
kubectl delete pod -n database -l app=test-cache
# Wait for pod to restart
kubectl wait --for=condition=ready pod -n database -l app=test-cache --timeout=60s

# Verify data is still there
redis-cli -h localhost -p 6379 GET persistent-key
```

## Test Scenarios

### Scenario 1: Basic Cache Operations

```bash
# First ensure port-forward is running:
# kubectl port-forward -n database svc/test-cache 6379:6379

# Test case: Basic key-value operations
redis-cli -h localhost -p 6379 <<EOF
SET user:1001 '{"name":"John","age":30}'
GET user:1001
HSET user:1002 name "Jane" age 25
HGETALL user:1002
EXPIRE user:1001 300
TTL user:1001
DEL user:1002
EOF
```

### Scenario 2: List and Set Operations

```bash
# Ensure port-forward is running in another terminal
# Test case: Complex data structures
redis-cli -h localhost -p 6379 <<EOF
LPUSH mylist "item1" "item2" "item3"
LRANGE mylist 0 -1
SADD myset "member1" "member2" "member3"
SMEMBERS myset
ZADD myzset 1 "first" 2 "second" 3 "third"
ZRANGE myzset 0 -1 WITHSCORES
EOF
```

### Scenario 3: Concurrent Access

```bash
# First ensure port-forward is running:
# kubectl port-forward -n database svc/test-cache 6379:6379

# Test case: Multiple clients
# Terminal 1:
redis-cli -h localhost -p 6379 MONITOR

# Terminal 2:
for i in {1..100}; do
  redis-cli -h localhost -p 6379 SET "concurrent:$i" "value:$i"
done

# Terminal 3:
for i in {1..100}; do
  redis-cli -h localhost -p 6379 GET "concurrent:$i"
done
```

## Monitoring and Observability

### Resource Monitoring

```bash
# Check pod resource usage
kubectl top pod -n database -l app=test-cache

# Check memory statistics via Dragonfly
redis-cli -h localhost -p 6379 INFO memory | grep used_memory

# Check CPU usage
kubectl exec -n database statefulset/test-cache -- ps aux
```

### Log Analysis

```bash
# View Dragonfly logs
kubectl logs -n database -l app=test-cache -f

# Check for errors or warnings
kubectl logs -n database -l app=test-cache | grep -E "(ERROR|WARN|error|warning)"

# Operator logs for troubleshooting
kubectl logs -n database deployment/dragonfly-operator -f
```

### Health Checks

```bash
# Check Dragonfly CRD status
kubectl get dragonfly test-cache -n database -o yaml | grep -A 10 status

# Check readiness probes
kubectl describe pod -n database -l app=test-cache | grep -A 5 "Readiness"

# Check service endpoints
kubectl get endpoints -n database -l app=test-cache
```

## Troubleshooting Test Issues

### Common Problems

1. **Pod Stuck in Pending**:
   ```bash
   kubectl describe pod -n database -l app=test-cache
   # Check for resource constraints or storage issues
   ```

2. **Connection Refused**:
   ```bash
   kubectl port-forward -n database svc/test-cache 6379:6379
   # Verify service and pod are running
   ```

3. **Data Not Persisting**:
   ```bash
   kubectl get pvc -n database -l app.kubernetes.io/instance=test-cache
   kubectl describe pvc -n database
   # Check storage class and volume mounting
   ```

4. **CRD Validation Errors**:
   ```bash
   kubectl describe dragonfly test-cache -n database
   # Check for schema validation issues in events
   ```

### Debug Commands

```bash
# Comprehensive debug information
kubectl get all -n database -l app=test-cache
kubectl describe dragonfly test-cache -n database
kubectl logs -n database deployment/dragonfly-operator --tail=50
kubectl get events -n database --sort-by=.metadata.creationTimestamp
```

## Production Readiness Testing

### Scale Testing

Create additional instances for scale testing:

```yaml
# Additional test instance
apiVersion: dragonflydb.io/v1alpha1
kind: Dragonfly
metadata:
  name: test-cache-scaled
  namespace: database
spec:
  replicas: 3 # Multi-replica setup
  resources:
    requests:
      cpu: "200m"
      memory: "512Mi"
    limits:
      cpu: "1000m"
      memory: "1Gi"
```

### Load Testing

```bash
# First ensure port-forward is running:
# kubectl port-forward -n database svc/test-cache 6379:6379

# Extended load test
redis-benchmark -h localhost -p 6379 \
  -t set,get,incr,lpush,rpush,lpop,rpop,sadd,hset,spop,lrange,mset \
  -n 100000 \
  -c 50 \
  --csv
```

### Backup and Recovery Testing

```bash
# Test snapshot creation
redis-cli -h localhost -p 6379 BGSAVE

# Verify snapshot files
kubectl exec -n database statefulset/test-cache -- ls -la /dragonfly/snapshots/

# Test recovery by deleting and recreating instance
kubectl delete dragonfly test-cache -n database
# Wait and recreate
kubectl apply -f kubernetes/apps/database/test-cache/app/dragonfly.yaml
```

## Cleanup

Remove test instances when done:

```bash
# Remove via Flux (recommended)
git rm kubernetes/apps/database/test-cache/
git commit -m "Remove DragonflyDB test instance"
git push

# Or direct deletion (not recommended for GitOps)
kubectl delete dragonfly test-cache -n database
```

## Next Steps

After successful testing:

1. **Production Deployment**: Scale up resources and replicas
2. **Monitoring Integration**: Add Prometheus metrics collection
3. **Backup Strategy**: Implement automated snapshot scheduling
4. **High Availability**: Configure multi-replica deployments
5. **Security**: Add authentication and network policies

## References

- [DragonflyDB Documentation](https://www.dragonflydb.io/docs)
- [Redis Commands Reference](https://redis.io/commands)
- [Kubernetes Testing Patterns](https://kubernetes.io/docs/concepts/cluster-administration/manage-deployment/#testing)
- [Redis Benchmarking](https://redis.io/docs/management/optimization/benchmarks/)
