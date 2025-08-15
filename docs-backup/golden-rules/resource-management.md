# Resource Management Golden Rules

## The Golden Rule

**Always set resource requests; never remove them to "fix" scheduling issues.** Without requests, Kubernetes cannot make intelligent scheduling decisions, leading to node overload and cascading failures.

## Critical Rules

### 1. Always Set Memory Limits, Never Set CPU Limits

**WRONG:**
```yaml
resources:
  limits:
    cpu: 500m      # This causes CPU throttling!
    memory: 512Mi
```

**RIGHT:**
```yaml
resources:
  requests:
    cpu: 100m      # Request what you need
    memory: 128Mi
  limits:
    memory: 512Mi  # Only limit memory to prevent OOM
    # No CPU limit - prevents throttling
```

**Why:** CPU limits cause throttling even when CPU is available. Memory limits prevent OOM kills.

### 2. Never Set Requests Higher Than Node Capacity

**WRONG:**
```yaml
resources:
  requests:
    memory: 32Gi  # On a node with 16Gi total!
```

**RIGHT:**
```bash
# First, check node capacity
kubectl describe nodes | grep -A5 "Allocated resources"

# Set requests leaving headroom
resources:
  requests:
    memory: 2Gi  # On a 16Gi node, leave room for system
```

**Why:** Pods will be stuck in Pending forever if requests exceed any node's capacity.

### 3. Always Use Resource Quotas for Shared Namespaces

**WRONG:**
```bash
# Creating a shared namespace without quotas
kubectl create namespace shared-dev
```

**RIGHT:**
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: shared-dev-quota
  namespace: shared-dev
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    persistentvolumeclaims: "10"
```

**Why:** Without quotas, one application can consume all cluster resources.

### 4. Never Ignore PodDisruptionBudgets for Critical Services

**WRONG:**
```yaml
# Deploying a critical service without PDB
apiVersion: apps/v1
kind: Deployment
metadata:
  name: critical-app
spec:
  replicas: 3
```

**RIGHT:**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: critical-app-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: critical-app
```

**Why:** Without PDB, cluster upgrades can take down all replicas simultaneously.

### 5. Always Set Topology Spread Constraints for HA

**WRONG:**
```yaml
# Multiple replicas that might all land on same node
spec:
  replicas: 3
```

**RIGHT:**
```yaml
spec:
  replicas: 3
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app: critical-app
```

**Why:** Without spread constraints, node failure can take down all replicas.

## Resource Sizing Guidelines

### Standard Application Tiers

**Minimal (Development)**
```yaml
resources:
  requests:
    cpu: 10m
    memory: 32Mi
  limits:
    memory: 128Mi
```

**Small (Light Services)**
```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    memory: 512Mi
```

**Medium (Standard Apps)**
```yaml
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    memory: 2Gi
```

**Large (Databases/Heavy Apps)**
```yaml
resources:
  requests:
    cpu: 1000m
    memory: 2Gi
  limits:
    memory: 8Gi
```

## Monitoring Resource Usage

### Check Actual Usage Before Setting
```bash
# Get actual usage for sizing
kubectl top pods -n namespace
kubectl top nodes

# Check historical usage in Grafana
# Dashboard: "Kubernetes / Compute Resources / Namespace (Pods)"
```

### Alert on Resource Pressure
```yaml
# PrometheusRule for resource alerts
- alert: PodMemoryUsageHigh
  expr: |
    container_memory_working_set_bytes{pod!=""}
    / container_spec_memory_limit_bytes{pod!=""}
    > 0.8
  for: 5m
```

## Recovery Procedures

### Node Memory Pressure
```bash
# Identify memory hogs
kubectl top pods -A --sort-by=memory

# Evict non-critical pods
kubectl drain node-name --ignore-daemonsets \
  --delete-emptydir-data --pod-selector='priority!=high'
```

### Scheduling Failures
```bash
# Check why pods aren't scheduling
kubectl describe pod stuck-pod

# Check node resources
kubectl describe nodes | grep -A10 "Allocated resources"

# Temporarily reduce requests if needed
kubectl edit deployment app-name
# Reduce requests, but SET A REMINDER TO FIX
```

## Pre-Operation Checklist

- [ ] Current resource usage analyzed with `kubectl top`
- [ ] Historical usage patterns reviewed in Grafana
- [ ] Node capacity verified
- [ ] Resource quotas checked for namespace
- [ ] PodDisruptionBudget configured for HA apps
- [ ] Topology spread constraints set for multi-replica
- [ ] Monitoring alerts configured

## Incidents

### 2024-10-30: OOM Killer Rampage
- **What happened:** Removed memory limits to "fix" scheduling
- **Impact:** Node ran out of memory, OOM killer killed critical pods
- **Root cause:** No memory limits meant unbounded growth
- **Lesson:** Always set memory limits

### 2024-12-05: CPU Throttling Crisis
- **What happened:** Set CPU limits on latency-sensitive app
- **Impact:** Response times 10x higher despite CPU available
- **Root cause:** CPU limits cause throttling
- **Lesson:** Never set CPU limits, only requests