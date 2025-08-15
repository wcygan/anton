# High Availability Golden Rules

## The Golden Rule

**Never deploy critical services without redundancy.** A single replica is a single point of failure. Hardware fails, nodes crash, and maintenance happens - plan for it.

## Critical Rules

### 1. Always Use Pod Anti-Affinity for Critical Services

**WRONG:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: critical-service
spec:
  replicas: 3  # All might land on same node!
```

**RIGHT:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: critical-service
spec:
  replicas: 3
  template:
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: critical-service
            topologyKey: kubernetes.io/hostname
```

**Why:** Without anti-affinity, all pods could be scheduled on the same node. One node failure = total service outage.

### 2. Never Rely on Single Zone/Node for Stateful Data

**WRONG:**
```yaml
# Single replica StatefulSet
apiVersion: apps/v1
kind: StatefulSet
spec:
  replicas: 1  # Data lives on one node only
```

**RIGHT:**
```yaml
# Multi-replica with distributed storage
apiVersion: apps/v1
kind: StatefulSet
spec:
  replicas: 3
  podManagementPolicy: Parallel
  template:
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: database
            topologyKey: kubernetes.io/hostname
```

**Why:** Stateful data on a single node is lost if that node fails. Distribute across nodes with replication.

### 3. Always Define PodDisruptionBudgets for HA Services

**WRONG:**
```bash
# No PDB = all pods can be evicted simultaneously
kubectl drain node-1 --ignore-daemonsets
# Suddenly all replicas are terminating!
```

**RIGHT:**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: critical-service-pdb
spec:
  minAvailable: 2  # Or use maxUnavailable: 1
  selector:
    matchLabels:
      app: critical-service
  unhealthyPodEvictionPolicy: AlwaysAllow
```

**Why:** PDBs prevent cluster operations from taking down too many pods at once, maintaining service availability.

### 4. Never Use Deployment for Distributed Stateful Services

**WRONG:**
```yaml
# Using Deployment for distributed database
apiVersion: apps/v1
kind: Deployment
metadata:
  name: distributed-database
spec:
  replicas: 3
  # Pods have random names, no stable identity!
```

**RIGHT:**
```yaml
# Use StatefulSet for stable identity
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: distributed-database
spec:
  serviceName: database-headless
  replicas: 3
  # Pods get stable names: database-0, database-1, database-2
```

**Why:** Distributed systems need stable network identities and ordered deployment. StatefulSets provide both.

### 5. Always Implement Readiness Gates for Zero-Downtime Updates

**WRONG:**
```yaml
# No readiness probe
spec:
  containers:
  - name: app
    image: myapp:v2
    # Traffic sent immediately, even if app isn't ready!
```

**RIGHT:**
```yaml
spec:
  containers:
  - name: app
    image: myapp:v2
    readinessProbe:
      httpGet:
        path: /health/ready
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 5
      successThreshold: 1
      failureThreshold: 3
    # Optional: readiness gates for advanced checks
    readinessGates:
    - conditionType: "app.example.com/feature-flags-loaded"
```

**Why:** Without readiness probes, traffic is routed to pods before they're ready, causing errors during updates.

## HA Architecture Patterns

### Service Layer HA

```yaml
# Primary/Secondary pattern with automatic failover
---
apiVersion: v1
kind: Service
metadata:
  name: app-primary
spec:
  selector:
    app: myapp
    role: primary
  clusterIP: None  # Headless for direct pod access
---
apiVersion: v1
kind: Service
metadata:
  name: app-all
spec:
  selector:
    app: myapp  # All instances for read traffic
```

### Database HA Pattern

```yaml
# PostgreSQL HA with automated failover
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: postgres-ha
spec:
  instances: 3
  primaryUpdateStrategy: unsupervised
  
  postgresql:
    parameters:
      synchronous_commit: "on"
      min_wal_size: 1GB
      max_wal_size: 4GB
  
  bootstrap:
    initdb:
      database: app
      owner: app
  
  monitoring:
    enabled: true
```

### Cache HA Pattern

```yaml
# Redis Sentinel for automatic failover
apiVersion: databases.spotahome.com/v1
kind: RedisFailover
metadata:
  name: redis-ha
spec:
  sentinel:
    replicas: 3
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
        - topologyKey: kubernetes.io/hostname
  
  redis:
    replicas: 3
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
        - topologyKey: kubernetes.io/hostname
```

## Health Check Patterns

### Comprehensive Health Checks

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 3

startupProbe:  # For slow-starting apps
  httpGet:
    path: /health/startup
    port: 8080
  initialDelaySeconds: 0
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 30  # 5 minutes to start
```

### Circuit Breaker Pattern

```yaml
# Using Istio for circuit breaking
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: app-circuit-breaker
spec:
  host: app-service
  trafficPolicy:
    outlierDetection:
      consecutiveErrors: 5
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
      minHealthPercent: 50
```

## Recovery Procedures

### Service Degradation

```bash
# Detect unhealthy instances
kubectl get pods -l app=critical-service -o wide | grep -v Running

# Increase replicas temporarily
kubectl scale deployment critical-service --replicas=5

# Investigate failing pods
kubectl describe pod <failing-pod>
kubectl logs <failing-pod> --previous
```

### Split-Brain Recovery

```bash
# For stateful services with split-brain
# 1. Identify the true primary
kubectl exec -n db postgres-0 -- psql -c "SELECT pg_is_in_recovery();"

# 2. Fence the false primary
kubectl cordon <node-with-false-primary>

# 3. Force leader election
kubectl delete pod postgres-1 --force --grace-period=0

# 4. Verify single primary
kubectl exec -n db postgres-0 -- psql -c "SELECT * FROM pg_stat_replication;"
```

## Pre-Operation Checklist

- [ ] Anti-affinity rules configured for all critical services
- [ ] PodDisruptionBudgets defined with appropriate thresholds
- [ ] Health checks (liveness/readiness) tested and tuned
- [ ] Minimum 3 replicas for critical services
- [ ] Service mesh circuit breakers configured
- [ ] Backup pods/nodes available for failover
- [ ] Monitoring alerts for HA metrics
- [ ] Runbooks prepared for failure scenarios

## Incidents

### 2024-07-15: Full Service Outage During Upgrade
- **What happened:** Rolled out update to all 3 replicas simultaneously
- **Impact:** 15 minutes complete service outage
- **Root cause:** No PodDisruptionBudget defined
- **Lesson:** Always define PDBs for critical services

### 2024-09-23: Database Split-Brain
- **What happened:** Network partition caused two PostgreSQL primaries
- **Impact:** Data inconsistency requiring manual reconciliation
- **Root cause:** No proper fencing mechanism
- **Lesson:** Implement proper leader election and fencing

### 2024-11-01: Cascading Failure from Single Pod
- **What happened:** One sick pod caused entire service degradation
- **Impact:** 50% error rate for 2 hours
- **Root cause:** No circuit breaker, requests kept routing to sick pod
- **Lesson:** Implement circuit breakers and outlier detection