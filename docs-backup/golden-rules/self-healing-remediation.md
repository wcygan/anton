# Self-Healing & Remediation Golden Rules

## The Golden Rule

**Never set infinite retries without circuit breakers.** Infinite retries without backoff or circuit breaking can overwhelm systems, create cascading failures, and prevent actual recovery. Failed systems need time to heal.

## Critical Rules

### 1. Always Configure Proper Health Checks Before Remediation

**WRONG:**
```yaml
# No health checks but aggressive remediation
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
spec:
  install:
    remediation:
      retries: -1  # Infinite retries!
  # No health checks defined
```

**RIGHT:**
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
spec:
  install:
    remediation:
      retries: 3
  test:
    enable: true  # Run Helm tests
  values:
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 5
      failureThreshold: 3
```

**Why:** Without health checks, remediation keeps restarting broken services without knowing if they're actually fixed.

### 2. Never Use Zero Backoff for Retries

**WRONG:**
```yaml
# Hammering the system with instant retries
spec:
  retryPolicy:
    retries: 10
    backoff:
      duration: 0s  # No backoff!
```

**RIGHT:**
```yaml
# Exponential backoff gives system time to recover
spec:
  retryPolicy:
    retries: 5
    backoff:
      duration: 10s
      factor: 2
      maxDuration: 5m
    # Results in: 10s, 20s, 40s, 80s, 160s
```

**Why:** Systems need time to recover. Instant retries can worsen the problem and prevent self-healing.

### 3. Always Set Resource Limits for Self-Healing Controllers

**WRONG:**
```yaml
# Flux controller with no limits
apiVersion: apps/v1
kind: Deployment
metadata:
  name: helm-controller
spec:
  template:
    spec:
      containers:
      - name: manager
        # No resource limits!
```

**RIGHT:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: helm-controller
spec:
  template:
    spec:
      containers:
      - name: manager
        resources:
          limits:
            memory: 1Gi
          requests:
            cpu: 100m
            memory: 128Mi
```

**Why:** During remediation storms, controllers can consume excessive resources and destabilize the cluster.

### 4. Never Ignore Remediation Exhaustion

**WRONG:**
```yaml
# No alerting on remediation failures
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
spec:
  install:
    remediation:
      retries: 3
  # No notification of exhaustion
```

**RIGHT:**
```yaml
# Alert on remediation exhaustion
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
spec:
  groups:
  - name: flux-remediation
    rules:
    - alert: RemediationExhausted
      expr: |
        gotk_reconcile_condition{type="Ready",status="False",kind="HelmRelease"}
        and
        gotk_remedile_info{retries="0"}
      for: 10m
      annotations:
        summary: "HelmRelease {{ $labels.name }} exhausted retries"
        runbook_url: "https://wiki/runbooks/flux-remediation"
```

**Why:** Silent failures mean problems go unnoticed until users complain.

### 5. Always Implement Progressive Remediation

**WRONG:**
```yaml
# Same aggressive remediation for all failures
kind: HelmRelease
spec:
  upgrade:
    remediation:
      remediateLastFailure: true  # Might rollback valid upgrades!
      retries: 10
```

**RIGHT:**
```yaml
# Progressive remediation strategy
kind: HelmRelease
spec:
  upgrade:
    remediation:
      remediateLastFailure: false  # Don't auto-rollback
      retries: 3
      strategy: rollback  # Only on specific failures
  
  # Combine with progressive delivery
  postRenderers:
  - kustomize:
      patchesStrategicMerge:
      - kind: Deployment
        metadata:
          name: app
        spec:
          strategy:
            type: RollingUpdate
            rollingUpdate:
              maxSurge: 1
              maxUnavailable: 0  # Zero-downtime
```

**Why:** Not all failures should trigger the same response. Progressive remediation prevents overreaction.

## Self-Healing Patterns

### Application-Level Self-Healing

```yaml
# Implement circuit breakers
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  circuit_breaker.yaml: |
    circuitBreaker:
      errorThresholdPercentage: 50
      requestVolumeThreshold: 20
      sleepWindowInMilliseconds: 60000
      timeout: 5000
    
    retry:
      maxAttempts: 3
      backoffMultiplier: 2
      initialInterval: 1000
      maxInterval: 30000
```

### Pod-Level Self-Healing

```yaml
# Comprehensive probe configuration
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: app
        # Startup probe for slow-starting apps
        startupProbe:
          httpGet:
            path: /health/startup
            port: 8080
          failureThreshold: 30
          periodSeconds: 10
        
        # Liveness for deadlock detection
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 0
          periodSeconds: 10
          timeoutSeconds: 1
          successThreshold: 1
          failureThreshold: 3
        
        # Readiness for traffic management
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 0
          periodSeconds: 5
          timeoutSeconds: 1
          successThreshold: 1
          failureThreshold: 3
        
        # Graceful shutdown
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
```

### Service Mesh Self-Healing

```yaml
# Istio retry and circuit breaking
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: app-vs
spec:
  http:
  - retries:
      attempts: 3
      perTryTimeout: 30s
      retryOn: 5xx,reset,connect-failure,refused-stream
      retryRemoteLocalities: true
    timeout: 90s
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: app-dr
spec:
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        http1MaxPendingRequests: 50
        http2MaxRequests: 100
    outlierDetection:
      consecutiveErrors: 5
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
      minHealthPercent: 30
      splitExternalLocalOriginErrors: true
```

### Operator-Level Self-Healing

```yaml
# Custom operator with self-healing logic
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-operator
spec:
  template:
    spec:
      containers:
      - name: operator
        env:
        - name: RECONCILE_PERIOD
          value: "1m"
        - name: ERROR_THRESHOLD
          value: "3"
        - name: BACKOFF_LIMIT
          value: "5"
        - name: BACKOFF_DURATION
          value: "30s"
        - name: HEALTH_CHECK_INTERVAL
          value: "30s"
```

## Remediation Strategies

### Flux Remediation Configuration

```yaml
# Graduated remediation strategy
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: critical-app
spec:
  interval: 5m
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
      strategy: rollback
  rollback:
    timeout: 10m
    cleanupOnFail: true
  test:
    enable: true
    timeout: 5m
  # Force remediation check
  suspend: false
```

### Progressive Delivery with Flagger

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: app
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: app
  progressDeadlineSeconds: 600
  service:
    port: 80
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    # Automatic rollback on metrics
    metrics:
    - name: request-success-rate
      thresholdRange:
        min: 99
      interval: 1m
    - name: request-duration
      thresholdRange:
        max: 500
      interval: 1m
    # Automated rollback
    webhooks:
    - name: rollback-on-failure
      type: rollback
      url: http://flagger-loadtester.test/
```

## Monitoring Remediation

### Key Metrics to Track

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard
data:
  remediation-dashboard.json: |
    {
      "panels": [
        {
          "title": "Remediation Rate",
          "targets": [{
            "expr": "rate(gotk_remediation_total[5m])"
          }]
        },
        {
          "title": "Failed Remediations",
          "targets": [{
            "expr": "gotk_remediation_failed_total"
          }]
        },
        {
          "title": "Circuit Breaker Status",
          "targets": [{
            "expr": "circuit_breaker_open"
          }]
        }
      ]
    }
```

## Recovery Procedures

### Remediation Storm Recovery

```bash
# 1. Suspend problematic resources
flux suspend hr --all -n problematic-namespace

# 2. Check controller resources
kubectl top pods -n flux-system

# 3. Increase controller resources if needed
kubectl patch deployment -n flux-system helm-controller \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"manager","resources":{"limits":{"memory":"2Gi"}}}]}}}}'

# 4. Resume one by one
for hr in $(kubectl get hr -n problematic-namespace -o name); do
  kubectl patch $hr -n problematic-namespace -p '{"spec":{"suspend":false}}'
  sleep 30  # Give time between resumptions
done
```

### Circuit Breaker Reset

```bash
# Manual circuit breaker reset
kubectl exec -n app deployment/app -- curl -X POST localhost:8080/admin/circuit-breaker/reset

# Or via service mesh
kubectl exec -n istio-system deployment/istio-pilot -- \
  pilot-discovery request GET /clusters | grep outlier
```

## Pre-Operation Checklist

- [ ] Health checks configured and tested
- [ ] Retry policies have exponential backoff
- [ ] Resource limits set on controllers
- [ ] Monitoring alerts configured
- [ ] Circuit breakers configured where appropriate
- [ ] Remediation strategy documented
- [ ] Rollback procedures tested
- [ ] Notification channels configured

## Incidents

### 2024-05-15: Remediation Storm Crashed Cluster
- **What happened:** Infinite retries on failing deployments
- **Impact:** Controllers OOM, cluster API unresponsive
- **Root cause:** No retry limits or resource constraints
- **Lesson:** Always limit retries and controller resources

### 2024-07-20: Silent Failures for 3 Days
- **What happened:** Apps failing but no alerts
- **Impact:** Users reported issues before ops knew
- **Root cause:** Remediation exhausted but no alerts
- **Lesson:** Alert on remediation exhaustion

### 2024-09-10: Rollback Loop
- **What happened:** Upgrade → Fail → Rollback → Upgrade loop
- **Impact:** 6 hours of instability
- **Root cause:** Auto-rollback with bad health checks
- **Lesson:** Fix root cause, don't just rollback