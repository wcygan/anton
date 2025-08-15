# Load Testing Guide for Anton Cluster

This guide provides comprehensive load testing strategies for validating your Kubernetes cluster's production readiness.

## 🎯 Testing Objectives

**Performance Validation:**
- Network/Ingress throughput and latency
- Storage I/O performance and reliability
- Resource scaling and limits enforcement
- Control plane stability under load

**Resilience Testing:**
- Pod failure recovery
- Resource pressure handling
- Storage persistence across failures
- API server stress tolerance

## 🛠️ Available Test Suites

### 1. Comprehensive Load Test
**Command:** `deno task load-test`

Tests all major cluster components simultaneously:
- **Network/Ingress:** HTTP load with concurrent connections
- **Storage:** Sequential and random I/O benchmarks using FIO
- **Resource Scaling:** HPA behavior under CPU/memory pressure
- **Monitoring:** Log volume generation and metrics collection
- **Control Plane:** Rapid API operations stress test
- **GitOps:** Concurrent Flux reconciliation

**Configuration:**
```bash
# Default: 5 min duration, 50 concurrent workers
deno task load-test

# Custom configuration
deno task load-test --duration=600 --concurrency=100 --namespace=custom-test
```

### 2. Realistic Workload Test  
**Command:** `deno task load-test:realistic`

Simulates production application patterns:
- **Web Frontend:** 3 replicas, moderate CPU/memory
- **API Backend:** 2 replicas, higher resource requirements
- **Database:** 1 replica with persistent storage
- **Batch Processor:** CPU-intensive workload
- **Log Aggregator:** High I/O log processing

**Resource Footprint:**
- Total CPU Requests: ~2.0 cores
- Total Memory Requests: ~4.5GB  
- Storage: 10GB persistent volumes

### 3. Chaos Resilience Test
**Command:** `deno task load-test:chaos`

Chaos engineering tests for cluster resilience:
- **Pod Failure Recovery:** Kill pods, verify auto-recovery
- **Resource Pressure:** Create memory pressure, test scheduling
- **Storage Resilience:** Verify data persistence across failures
- **Control Plane Stress:** API server performance under load

## 📊 Test Results & Metrics

### Success Criteria

**Comprehensive Load Test:**
- ✅ Network RPS > 1000 with <50ms latency
- ✅ Storage sequential read/write > 100MB/s
- ✅ HPA successfully scales under load
- ✅ Monitoring system handles high log volume
- ✅ API server >95% success rate under stress

**Realistic Workload:**
- ✅ All workloads deploy successfully
- ✅ Resource requests honored (no evictions)
- ✅ Traffic simulation completes without errors
- ✅ Node utilization remains under 80%

**Chaos Resilience:**
- ✅ Pod failures automatically recover
- ✅ New pods schedule during resource pressure
- ✅ Storage data persists across pod restarts
- ✅ API server maintains >90% availability under stress

### Performance Benchmarks

**Expected Performance (Anton Cluster):**
```
Network Throughput:    1500+ RPS
Storage Sequential:    150MB/s read, 120MB/s write  
Storage Random:        8000+ IOPS
Resource Scaling:      <2 min HPA response
Control Plane:         >95% API success rate
Monitoring:            <2GB Prometheus memory under load
```

## 🔧 Pre-Test Checklist

1. **Cluster Health:** Ensure all nodes and core services are healthy
2. **Resource Availability:** Verify sufficient CPU/memory for test workloads
3. **Storage:** Confirm Ceph cluster is healthy with available capacity
4. **Monitoring:** Ensure Prometheus/Grafana are functioning
5. **Backup:** Consider cluster state backup before destructive tests

## 📋 Running Load Tests

### Quick Start
```bash
# Health check first
./scripts/k8s-health-check.ts --json

# Run comprehensive test suite  
deno task load-test

# Check results and cluster impact
kubectl top nodes
./scripts/k8s-health-check.ts --json
```

### Production Validation Sequence
```bash
# 1. Realistic workload simulation
deno task load-test:realistic

# 2. Full load test
deno task load-test --duration=600 --concurrency=75

# 3. Resilience validation
deno task load-test:chaos

# 4. Final health check
./scripts/k8s-health-check.ts --json
```

### Monitoring During Tests

**Watch cluster resources:**
```bash
# Node utilization
watch kubectl top nodes

# Pod resource usage
watch kubectl top pods -A

# Check for evictions or failures
kubectl get events -A --sort-by=.lastTimestamp | tail -20
```

**Monitor specific metrics:**
- Prometheus memory usage
- Loki ingestion rate
- Ceph cluster health
- Network latency

## ⚠️ Safety Considerations

1. **Test Environment:** Run on non-production clusters when possible
2. **Resource Limits:** Tests respect configured resource limits
3. **Cleanup:** All tests clean up their resources automatically
4. **Monitoring:** Watch cluster health during tests
5. **Abort Procedure:** Tests can be stopped with Ctrl+C

## 🐛 Troubleshooting

### Common Issues

**Test Namespace Stuck:**
```bash
kubectl get namespace load-test -o yaml | grep finalizers
kubectl patch namespace load-test -p '{"metadata":{"finalizers":null}}' --type=merge
```

**Storage Tests Fail:**
```bash
# Check Ceph health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Verify storage class
kubectl get storageclass ceph-block
```

**Network Tests Timeout:**
```bash
# Check ingress controller
kubectl get pods -n network -l app.kubernetes.io/name=ingress-nginx

# Verify service connectivity
kubectl get endpoints -A
```

### Performance Debugging

**Poor Network Performance:**
- Check Cilium CNI health
- Verify ingress controller resources
- Monitor network policies

**Storage Bottlenecks:**
- Review Ceph OSD performance
- Check node disk utilization
- Verify PVC mount points

**Resource Constraints:**
- Review node available resources
- Check for resource quota limits
- Monitor scheduler decisions

## 📈 Production Readiness Assessment

### Grade A (Production Ready)
- All tests pass with >95% success rates
- Performance meets or exceeds benchmarks
- No resource exhaustion during tests
- Rapid recovery from simulated failures

### Grade B (Ready with Monitoring)
- Tests pass with >90% success rates
- Minor performance degradation under load
- Occasional resource pressure but no failures
- Good recovery times from failures

### Grade C (Needs Improvement)
- Tests pass with >80% success rates
- Significant performance impact under load
- Resource constraints causing scheduling issues
- Slow recovery from failures

### Grade F (Not Production Ready)
- Test failures or <80% success rates
- Severe performance degradation
- Resource exhaustion causing cascading failures
- Poor or no recovery from failures

## 🔄 Continuous Load Testing

### Automated Testing Schedule
```bash
# Weekly comprehensive test
0 2 * * 1 /usr/bin/deno task load-test --duration=300

# Daily realistic workload
0 3 * * * /usr/bin/deno task load-test:realistic  

# Monthly chaos engineering
0 4 1 * * /usr/bin/deno task load-test:chaos
```

### CI/CD Integration
- Run realistic workload tests before major deployments
- Include load testing in cluster upgrade procedures
- Monitor performance trends over time
- Alert on significant performance regressions

## 🎯 Next Steps

1. **Baseline Establishment:** Run tests on healthy cluster to establish performance baseline
2. **Regular Testing:** Schedule automated load tests
3. **Performance Tuning:** Use results to optimize resource allocation
4. **Capacity Planning:** Plan scaling based on load test results
5. **Disaster Recovery:** Validate backup/restore procedures under load