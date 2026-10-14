---
sidebar_position: 6
---

# Observability Stack Installation Guide

> Historical installation example: this page uses the retired template pipeline
> and an Alloy/operator design. Anton's current Kubernetes log path uses an
> OTel Collector DaemonSet and Loki. Use the [Kubernetes logs runbook](../runbooks/kubernetes-logs-loki.md)
> for current operation and the [routine operations guide](../runbooks/routine-operations.md)
> for deployment; do not run this page's `task configure` examples.

Complete guide for deploying a production-grade observability stack (Prometheus, Loki, Alloy, Grafana) on Talos Kubernetes using GitOps.

## Overview

This guide installs a comprehensive observability stack providing metrics collection, log aggregation, and unified visualization through Kubernetes operators.

**Stack Components:**

| Component | Version | Purpose | Operator |
|-----------|---------|---------|----------|
| **Prometheus** | v0.86.1 | Metrics collection, storage, alerting | prometheus-operator/prometheus-operator |
| **Loki** | v3.4 | Log aggregation and storage | grafana/loki (operator) |
| **Alloy** | v3.0 | Telemetry collector (replaces Grafana Agent) | grafana/alloy-operator |
| **Grafana** | v5.20.0 | Unified visualization and dashboards | grafana/grafana-operator |

**Why This Stack:**
- **Unified observability**: Metrics (Prometheus) + Logs (Loki) in single pane (Grafana)
- **Kubernetes-native**: Declarative CRDs for all components
- **GitOps-ready**: Flux-managed HelmReleases for version control
- **Scalable**: Microservices mode for production workloads
- **Cost-effective**: Self-hosted alternative to cloud observability platforms

**Architecture:**

```mermaid
flowchart TD
    subgraph cluster[Kubernetes Cluster]
        subgraph collectors[Collectors]
            alloy[Alloy Agents<br/>DaemonSet]
        end

        subgraph backends[Storage Backends]
            prometheus[Prometheus<br/>Time-series DB]
            loki[Loki<br/>Log aggregation]
        end

        subgraph visualization[Visualization]
            grafana[Grafana<br/>Dashboards]
        end

        alloy -->|metrics| prometheus
        alloy -->|logs| loki
        prometheus --> grafana
        loki --> grafana
    end

    pods[Application Pods] -->|scrape| alloy
    nodes[Node Logs] -->|collect| alloy

    classDef collector fill:#4caf50,color:white
    classDef backend fill:#2196f3,color:white
    classDef viz fill:#ff9800,color:white

    class alloy collector
    class prometheus,loki backend
    class grafana viz
```

---

## Prerequisites

### Cluster Requirements

| Requirement | Value |
|------------|-------|
| Kubernetes | v1.29+ (Talos Linux) |
| Nodes | 3+ control plane nodes |
| Storage | Rook Ceph or equivalent (dynamic PVC provisioning) |
| CPU (total) | 4+ cores recommended |
| Memory (total) | 8Gi+ recommended |
| Flux CD | Installed and syncing |

### Resource Allocation Guidelines

| Component | CPU Request | Memory Request | Storage |
|-----------|-------------|----------------|---------|
| Prometheus | 500m | 2Gi | 50Gi (time-series data) |
| Loki | 500m | 1Gi | 50Gi (log data) |
| Alloy | 200m/node | 512Mi/node | Ephemeral |
| Grafana | 250m | 512Mi | 10Gi (dashboards/plugins) |

**Total estimated**: 2-3 cores, 8-10Gi memory, 110Gi storage

### Software Requirements

- ✓ Flux CD installed and syncing from Git
- ✓ SOPS configured for secret encryption
- ✓ Rook Ceph storage class configured (or equivalent)
- ✓ Talos cluster fully operational

---

## Deployment Plan

### Phase 1: Metrics Backend (Prometheus)

**Why first**: Foundation for cluster monitoring; other components depend on metrics.

**Steps:**
1. Deploy Prometheus Operator via HelmRelease
2. Create Prometheus CRD instance
3. Configure ServiceMonitor for auto-discovery
4. Verify metrics scraping

**Expected outcome**: Prometheus collecting metrics from kube-state-metrics, node-exporter, and API server.

### Phase 2: Log Backend (Loki)

**Why second**: Independent of Prometheus; provides log storage backend.

**Deployment mode**: Monolithic (simpler) or Microservices (production HA)

**Steps:**
1. Deploy Loki Operator
2. Create LokiStack CRD instance
3. Configure object storage backend (S3/Ceph)
4. Verify Loki readiness

**Expected outcome**: Loki ready to receive logs from Alloy.

### Phase 3: Telemetry Collector (Alloy)

**Why third**: Requires both Prometheus and Loki backends to send data to.

**Important**: Alloy replaces deprecated Grafana Agent (EOL Nov 1, 2025) and Promtail (deprecated in Loki 3.0).

**Steps:**
1. Deploy Alloy Operator
2. Deploy Alloy DaemonSet with configuration
3. Configure pipelines:
   - Kubernetes logs → Loki
   - Prometheus metrics → Prometheus
   - Pod logs → Loki
4. Verify data flow

**Expected outcome**: Logs flowing to Loki, metrics to Prometheus.

### Phase 4: Visualization (Grafana)

**Why last**: Consumes data from Prometheus and Loki.

**Steps:**
1. Deploy Grafana Operator v5
2. Create Grafana instance
3. Configure data sources:
   - Prometheus (metrics)
   - Loki (logs)
4. Import dashboards:
   - Kubernetes cluster overview
   - Node exporter metrics
   - Loki log explorer
5. Configure ingress/gateway for access

**Expected outcome**: Unified dashboards showing metrics + logs.

---

## Installation Steps

### Step 1: Prometheus Operator

**Documentation**: https://prometheus-operator.dev/

**Create namespace structure**:
```bash
mkdir -p kubernetes/apps/observability/prometheus-operator
cd kubernetes/apps/observability/prometheus-operator
```

**Standard 3-file pattern**:
```
prometheus-operator/
 app/
    helmrelease.yaml       # Prometheus Operator v0.86.1
    kustomization.yaml
 ks.yaml                    # Kustomization for Flux
```

**Key configuration**:
```yaml
# helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: prometheus-operator
spec:
  chart:
    spec:
      chart: kube-prometheus-stack
      version: 67.4.0  # Includes Prometheus Operator v0.86.1
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  values:
    prometheus:
      prometheusSpec:
        retention: 30d
        storageClassName: ceph-block
        storageSpec:
          volumeClaimTemplate:
            spec:
              resources:
                requests:
                  storage: 50Gi
```

**Deploy**:
```bash
task configure
git add kubernetes/apps/observability/prometheus-operator
git commit -m "feat: add prometheus-operator v0.86.1"
git push
task reconcile
```

**Verify**:
```bash
# Watch deployment
watch kubectl get pods -n observability

# Expected pods:
# - prometheus-operator-kube-prometheus-operator-*
# - prometheus-prometheus-operator-kube-prometheus-prometheus-0
# - alertmanager-prometheus-operator-kube-prometheus-alertmanager-0
# - prometheus-operator-kube-state-metrics-*
# - prometheus-operator-prometheus-node-exporter-* (DaemonSet)

# Check Prometheus targets
kubectl port-forward -n observability svc/prometheus-operator-kube-prometheus-prometheus 9090:9090
# Open: http://localhost:9090/targets
```

### Step 2: Loki Operator

**Documentation**: https://loki-operator.dev/

**Create namespace structure**:
```bash
mkdir -p kubernetes/apps/observability/loki-operator
cd kubernetes/apps/observability/loki-operator
```

**Deployment considerations**:

| Mode | Use Case | Complexity | HA | Storage |
|------|----------|------------|----|---------|
| Monolithic | Small clusters, dev | Low | No | Single instance |
| Microservices | Production, scale | High | Yes | Distributed |

**Recommended**: Start with monolithic, migrate to microservices if needed.

**Key configuration**:
```yaml
# helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: loki
spec:
  chart:
    spec:
      chart: loki
      version: 6.26.0  # Loki v3.4
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: flux-system
  values:
    deploymentMode: SingleBinary  # Monolithic mode
    loki:
      commonConfig:
        replication_factor: 1
      storage:
        type: filesystem
      schemaConfig:
        configs:
          - from: 2024-04-01
            store: tsdb
            object_store: filesystem
            schema: v13
    singleBinary:
      replicas: 1
      persistence:
        enabled: true
        storageClass: ceph-block
        size: 50Gi
```

**For production (microservices mode)**:
```yaml
deploymentMode: Distributed
write:
  replicas: 3
  persistence:
    storageClass: ceph-block
    size: 50Gi
read:
  replicas: 3
```

**Deploy and verify**:
```bash
task configure
git add kubernetes/apps/observability/loki-operator
git commit -m "feat: add loki v3.4 (monolithic mode)"
git push
task reconcile

# Verify
kubectl get pods -n observability -l app.kubernetes.io/name=loki
kubectl logs -n observability -l app.kubernetes.io/name=loki --tail=50
```

### Step 3: Alloy Operator

**Documentation**: https://grafana.com/docs/alloy/latest/

**Important migration notes**:
- Alloy replaces **Grafana Agent** (EOL Nov 1, 2025)
- Alloy replaces **Promtail** (deprecated in Loki 3.0)
- Use Alloy for all new deployments

**Create namespace structure**:
```bash
mkdir -p kubernetes/apps/observability/alloy-operator
cd kubernetes/apps/observability/alloy-operator
```

**Key configuration**:
```yaml
# helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: alloy-operator
spec:
  chart:
    spec:
      chart: alloy-operator
      version: 0.13.0
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: flux-system
---
# alloy-instance.yaml
apiVersion: monitoring.grafana.com/v1alpha1
kind: Alloy
metadata:
  name: alloy-metrics-logs
  namespace: observability
spec:
  config: |
    // Scrape Kubernetes pod metrics
    prometheus.scrape "pods" {
      targets = discovery.kubernetes.pods.targets
      forward_to = [prometheus.remote_write.prometheus.receiver]
    }

    // Collect Kubernetes pod logs
    loki.source.kubernetes "pods" {
      targets = discovery.kubernetes.pods.targets
      forward_to = [loki.write.loki.receiver]
    }

    // Send metrics to Prometheus
    prometheus.remote_write "prometheus" {
      endpoint {
        url = "http://prometheus-operator-kube-prometheus-prometheus.observability.svc:9090/api/v1/write"
      }
    }

    // Send logs to Loki
    loki.write "loki" {
      endpoint {
        url = "http://loki-gateway.observability.svc:80/loki/api/v1/push"
      }
    }

  clustering:
    enabled: true
```

**Deploy and verify**:
```bash
task configure
git add kubernetes/apps/observability/alloy-operator
git commit -m "feat: add alloy-operator v3.0 for telemetry collection"
git push
task reconcile

# Verify collectors
kubectl get pods -n observability -l app.kubernetes.io/name=alloy
kubectl logs -n observability -l app.kubernetes.io/name=alloy --tail=50
```

### Step 4: Grafana Operator

**Documentation**: https://grafana.com/docs/grafana-cloud/developer-resources/infrastructure-as-code/grafana-operator/

**Create namespace structure**:
```bash
mkdir -p kubernetes/apps/observability/grafana-operator
cd kubernetes/apps/observability/grafana-operator
```

**Key configuration**:
```yaml
# helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: grafana-operator
spec:
  chart:
    spec:
      chart: grafana-operator
      version: v5.20.0
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: flux-system
---
# grafana-instance.yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: Grafana
metadata:
  name: grafana
  namespace: observability
spec:
  config:
    server:
      root_url: "https://grafana.${CLOUDFLARE_DOMAIN}"
    security:
      admin_user: admin
      admin_password: ${GRAFANA_ADMIN_PASSWORD}  # From SOPS secret
  deployment:
    spec:
      replicas: 1
  persistentVolumeClaim:
    spec:
      storageClassName: ceph-block
      resources:
        requests:
          storage: 10Gi
---
# datasource-prometheus.yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDatasource
metadata:
  name: prometheus
  namespace: observability
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana
  datasource:
    name: Prometheus
    type: prometheus
    url: http://prometheus-operator-kube-prometheus-prometheus.observability.svc:9090
    isDefault: true
    access: proxy
---
# datasource-loki.yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDatasource
metadata:
  name: loki
  namespace: observability
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana
  datasource:
    name: Loki
    type: loki
    url: http://loki-gateway.observability.svc:80
    access: proxy
```

**Deploy and verify**:
```bash
task configure
git add kubernetes/apps/observability/grafana-operator
git commit -m "feat: add grafana-operator v5.20.0 with datasources"
git push
task reconcile

# Verify
kubectl get pods -n observability -l app=grafana
kubectl get grafanadatasources -n observability

# Access Grafana
kubectl port-forward -n observability svc/grafana-service 3000:3000
# Open: http://localhost:3000
```

---

## Post-Deployment Validation

### Health Checks

**Prometheus**:
```bash
# Check targets
kubectl port-forward -n observability svc/prometheus-operator-kube-prometheus-prometheus 9090:9090
# Visit: http://localhost:9090/targets (all should be "UP")

# Query metrics
curl -s http://localhost:9090/api/v1/query?query=up | jq
```

**Loki**:
```bash
# Check health
kubectl exec -n observability -it loki-0 -- wget -qO- http://localhost:3100/ready
# Expected: "ready"

# Query logs
kubectl port-forward -n observability svc/loki-gateway 3100:80
curl -s "http://localhost:3100/loki/api/v1/query?query={namespace=\"observability\"}" | jq
```

**Alloy**:
```bash
# Check pipeline status
kubectl logs -n observability -l app.kubernetes.io/name=alloy --tail=100 | grep -E "(scrape|push)"
# Should see: "successfully pushed to remote_write" and "scraped targets"
```

**Grafana**:
```bash
# Check datasource health
kubectl exec -n observability -it deploy/grafana -- \
  curl -s http://admin:${ADMIN_PASSWORD}@localhost:3000/api/datasources
# Both Prometheus and Loki should show "database": "connected"
```

### Data Flow Verification

```mermaid
sequenceDiagram
    participant Pod as Application Pod
    participant Alloy as Alloy Collector
    participant Prometheus as Prometheus
    participant Loki as Loki
    participant Grafana as Grafana

    Pod->>Alloy: Expose metrics :80/metrics
    Alloy->>Alloy: Scrape metrics every 15s
    Alloy->>Prometheus: Remote write metrics

    Pod->>Alloy: Write logs to stdout/stderr
    Alloy->>Alloy: Tail container logs
    Alloy->>Loki: Push logs via API

    Grafana->>Prometheus: Query metrics (PromQL)
    Grafana->>Loki: Query logs (LogQL)
    Grafana->>Grafana: Render dashboards
```

**Test end-to-end**:
```bash
# 1. Deploy test app with metrics
kubectl create deployment nginx --image=nginx:latest -n default
kubectl expose deployment nginx --port=80 -n default

# 2. Check metrics in Prometheus
# Query: up{job="kubernetes-pods", namespace="default"}

# 3. Check logs in Loki
# Query: {namespace="default", app="nginx"}

# 4. View in Grafana
# Create dashboard with both queries
```

---

## Next Steps

### 1. Import Essential Dashboards

**Kubernetes cluster monitoring**:
```yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: kubernetes-cluster
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana
  json: |
    # Dashboard ID: 7249 (Kubernetes Cluster Monitoring)
```

**Recommended dashboards**:
- **15759**: Kubernetes / Views / Global
- **15760**: Kubernetes / Views / Namespaces
- **15761**: Kubernetes / Views / Pods
- **12019**: Loki / Logs Explorer
- **19268**: Node Exporter Full

### 2. Configure Alerting

**Create PrometheusRule**:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cluster-alerts
  namespace: observability
spec:
  groups:
    - name: cluster
      interval: 30s
      rules:
        - alert: HighMemoryUsage
          expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Node {{ $labels.instance }} has high memory usage"
```

**Configure Alertmanager**:
```yaml
# Add to prometheus-operator HelmRelease values
alertmanager:
  config:
    receivers:
      - name: 'slack'
        slack_configs:
          - api_url: ${SLACK_WEBHOOK_URL}
            channel: '#alerts'
```

### 3. Enable Long-Term Storage

**Prometheus (Thanos)**:
```yaml
# Add to prometheus-operator values
thanos:
  enabled: true
  objectStorageConfig:
    bucket: prometheus-metrics
    endpoint: rook-ceph-rgw.storage.svc:80
```

**Loki (Ceph S3)**:
```yaml
# Migrate from filesystem to object storage
loki:
  storage:
    type: s3
    s3:
      endpoint: rook-ceph-rgw.storage.svc:80
      bucketNames: loki-chunks
      accessKeyId: ${S3_ACCESS_KEY}
      secretAccessKey: ${S3_SECRET_KEY}
```

### 4. Expose Grafana via Gateway

**Create HTTPRoute**:
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: grafana
  namespace: observability
spec:
  parentRefs:
    - name: envoy-external
      namespace: network
  hostnames:
    - grafana.${CLOUDFLARE_DOMAIN}
  rules:
    - backendRefs:
        - name: grafana-service
          port: 3000
```

**Update Grafana config**:
```yaml
config:
  server:
    root_url: "https://grafana.${CLOUDFLARE_DOMAIN}"
    serve_from_sub_path: false
```

### 5. Optimize Performance

**Prometheus query performance**:
- Enable query caching
- Configure recording rules for expensive queries
- Tune retention: 30d for recent, Thanos for long-term

**Loki query performance**:
- Use indexed labels sparingly (namespace, app, pod)
- Avoid high-cardinality labels (user_id, request_id)
- Configure compaction for storage efficiency

**Alloy resource tuning**:
```yaml
resources:
  limits:
    memory: 1Gi    # Increase if high log volume
  requests:
    cpu: 200m
    memory: 512Mi
```

### 6. Security Hardening

**Enable authentication**:
```yaml
# Grafana OAuth via Cloudflare Access
config:
  auth.generic_oauth:
    enabled: true
    name: Cloudflare Access
    client_id: ${OAUTH_CLIENT_ID}
    client_secret: ${OAUTH_CLIENT_SECRET}
```

**Network policies**:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus
  namespace: observability
spec:
  podSelector:
    matchLabels:
      app: prometheus
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: observability
      ports:
        - port: 9090
```

### 7. Capacity Planning

**Monitor resource usage**:
```bash
# Prometheus disk usage
kubectl exec -n observability prometheus-prometheus-operator-kube-prometheus-prometheus-0 -- \
  df -h /prometheus

# Loki disk usage
kubectl exec -n observability loki-0 -- df -h /var/loki
```

**Set up capacity alerts**:
```yaml
- alert: PrometheusStorageFull
  expr: prometheus_tsdb_storage_blocks_bytes / prometheus_tsdb_storage_max_bytes > 0.8
  for: 10m
  annotations:
    summary: "Prometheus storage {{ $value }}% full"
```

---

## Troubleshooting

### Prometheus Not Scraping Targets

**Symptoms**: Targets show "down" in Prometheus UI

**Diagnosis**:
```bash
kubectl get servicemonitors -n observability
kubectl describe servicemonitor <name> -n observability
kubectl logs -n observability -l app.kubernetes.io/name=prometheus
```

**Common causes**:
- ServiceMonitor label selector mismatch
- Network policy blocking scraping
- Target pod not exposing /metrics

**Fix**:
```yaml
# Ensure ServiceMonitor matches service labels
selector:
  matchLabels:
    app: my-app  # Must match service labels
```

### Loki Not Receiving Logs

**Symptoms**: Empty results in Grafana log explorer

**Diagnosis**:
```bash
# Check Alloy logs
kubectl logs -n observability -l app.kubernetes.io/name=alloy | grep -i loki

# Check Loki ingester
kubectl logs -n observability loki-0 | grep -i ingester

# Test Loki API
kubectl exec -n observability loki-0 -- \
  wget -qO- http://localhost:3100/loki/api/v1/query?query={namespace=\"observability\"}
```

**Common causes**:
- Alloy config error (check `loki.write` block)
- Loki ingester not ready
- Network connectivity issue

**Fix**:
```bash
# Restart Alloy
kubectl rollout restart daemonset -n observability alloy

# Check Loki health
kubectl get pods -n observability -l app.kubernetes.io/name=loki
```

### Grafana Datasource Unhealthy

**Symptoms**: "Bad Gateway" or "Connection refused" in Grafana

**Diagnosis**:
```bash
# Check datasource config
kubectl get grafanadatasources -n observability -o yaml

# Test connectivity from Grafana pod
kubectl exec -n observability deploy/grafana -- \
  curl -v http://prometheus-operator-kube-prometheus-prometheus.observability.svc:9090/api/v1/query?query=up
```

**Common causes**:
- Incorrect service URL
- Service not ready
- DNS resolution failure

**Fix**:
```yaml
# Use full FQDN
url: http://prometheus-operator-kube-prometheus-prometheus.observability.svc.cluster.local:9090
```

### High Memory Usage

**Symptoms**: OOMKilled pods, slow queries

**Diagnosis**:
```bash
# Check current usage
kubectl top pods -n observability

# Check metrics
kubectl exec -n observability prometheus-prometheus-operator-kube-prometheus-prometheus-0 -- \
  wget -qO- http://localhost:9090/api/v1/status/tsdb
```

**Tuning**:
```yaml
# Increase Prometheus memory
prometheus:
  prometheusSpec:
    resources:
      limits:
        memory: 4Gi  # Increase from 2Gi

# Reduce retention
    retention: 15d  # Reduce from 30d

# Increase Loki memory
singleBinary:
  resources:
    limits:
      memory: 2Gi  # Increase from 1Gi
```

---

## Reference Links

### Official Documentation
- [Prometheus Operator](https://prometheus-operator.dev/) - v0.86.1
- [Grafana Loki](https://grafana.com/docs/loki/latest/) - v3.4
- [Grafana Alloy](https://grafana.com/docs/alloy/latest/) - Replacing Agent/Promtail
- [Grafana Operator](https://github.com/grafana/grafana-operator) - v5.20.0

### Helm Charts
- [prometheus-community/kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [grafana/loki](https://github.com/grafana/loki/tree/main/production/helm/loki)
- [grafana/alloy-operator](https://github.com/grafana/alloy-operator)
- [grafana/grafana-operator](https://github.com/grafana/grafana-operator)

### Migration Guides
- [Migrate from Grafana Agent to Alloy](https://grafana.com/docs/alloy/latest/set-up/migrate/from-operator/)
- [Migrate from Promtail to Alloy](https://grafana.com/docs/loki/latest/send-data/promtail/migrating/)

### Community Resources
- [Awesome Prometheus Alerts](https://samber.github.io/awesome-prometheus-alerts/)
- [Grafana Dashboard Library](https://grafana.com/grafana/dashboards/)
- [PromQL Cheat Sheet](https://promlabs.com/promql-cheat-sheet/)

---

## Summary

This guide provides a complete observability stack with:
- ✅ **Metrics**: Prometheus Operator v0.86.1
- ✅ **Logs**: Loki v3.4 (monolithic or microservices)
- ✅ **Collection**: Alloy Operator v3.0 (modern replacement)
- ✅ **Visualization**: Grafana Operator v5.20.0

**Deployment sequence**: Prometheus → Loki → Alloy → Grafana

**Next actions**:
1. Deploy Prometheus Operator (Phase 1)
2. Verify metrics collection
3. Deploy Loki (Phase 2)
4. Deploy Alloy collectors (Phase 3)
5. Deploy Grafana with datasources (Phase 4)
6. Import dashboards and configure alerting

**Timeline estimate**: 2-4 hours for complete stack deployment with validation.
