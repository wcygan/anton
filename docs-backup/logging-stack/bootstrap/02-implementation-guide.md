# Loki + Alloy Implementation Guide

## Overview

This guide provides step-by-step instructions for deploying the Loki + Alloy logging stack on the Kubernetes homelab. Follow these steps in order to ensure a successful deployment.

## MCP Server Usage During Implementation

Use MCP servers throughout the implementation for real-time validation and troubleshooting:

### Pre-Implementation Checks
```bash
# Verify cluster readiness
/mcp kubernetes:kubectl_get "nodes" 
/mcp kubernetes:kubectl_generic "top" "nodes"

# Check existing resources
/mcp kubernetes:kubectl_get "helmrelease" "monitoring"
/mcp kubernetes:kubectl_get "helmrepository" "flux-system" 
```

### During Deployment
```bash
# Monitor Flux reconciliation
/mcp kubernetes:kubectl_get "kustomization" "flux-system" "--watch"
/mcp kubernetes:kubectl_get "helmrelease" "monitoring" "--watch"

# Check pod status
/mcp kubernetes:kubectl_get "pods" "monitoring" "-l app.kubernetes.io/name=loki"
/mcp kubernetes:kubectl_describe "pod" "monitoring" "loki-write-0"

# View logs for troubleshooting
/mcp kubernetes:kubectl_logs "monitoring" "loki-write-0" "--tail=100"
```

### Configuration Validation
```bash
# Get Helm chart values documentation
/mcp context7:get-library-docs /grafana/loki "helm values configuration" 5000

# Validate S3 configuration
/mcp sequential-thinking:sequential_thinking "Review this Loki S3 configuration for Ceph compatibility: endpoint: rook-ceph-rgw-storage.storage.svc.cluster.local, s3ForcePathStyle: true, region: us-east-1"
```

## Pre-Implementation: S3 Validation (REQUIRED)

Before starting the implementation, ensure S3 is operational:

```bash
# 1. Verify ObjectStore is enabled
ls kubernetes/apps/storage/rook-ceph-objectstore/ks.yaml
# Should exist (not ks.yaml.disabled)

# 2. Check RGW pods are running
kubectl get pods -n storage -l app=rook-ceph-rgw
# All pods should show Ready 1/1 or 2/2

# 3. Verify S3 endpoint
kubectl get svc -n storage rook-ceph-rgw-storage
# Should show ClusterIP and port 80

# 4. Test S3 connectivity
kubectl run -it --rm s3-test --image=minio/mc:latest --restart=Never -- \
  mc alias set test http://rook-ceph-rgw-storage.storage.svc.cluster.local test test
```

**If any of these checks fail**, see [S3 Prerequisites Guide](00-s3-prerequisites.md)

## Phase 1: Infrastructure Preparation

### MCP Commands for Phase 1
```bash
# Verify S3 is ready
/mcp kubernetes:kubectl_get "cephobjectstore" "storage" 
/mcp kubernetes:kubectl_get "pods" "storage" "-l app=rook-ceph-rgw"

# Check existing Helm repositories
/mcp kubernetes:kubectl_get "helmrepository" "flux-system"
```

### Step 1.1: Create Grafana Helm Repository

Create the Helm repository configuration for Grafana charts:

```bash
# Create the repository file
cat > kubernetes/flux/meta/repos/grafana.yaml << 'EOF'
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: grafana
  namespace: flux-system
spec:
  interval: 1h
  type: oci
  url: oci://grafana.github.io/helm-charts
EOF

# Update kustomization to include the new repo
cd kubernetes/flux/meta/repos/
# Add grafana.yaml to kustomization.yaml
```

### Step 1.2: Create S3 Buckets in Ceph

**Note**: This assumes Ceph ObjectStore is already enabled per the pre-implementation checks.

Verify the Object Store is healthy:

```bash
# Check Ceph status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Verify RGW is operational
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd pool ls | grep rgw
```

### Step 1.3: Create Object Bucket Claim

Create the bucket for Loki storage:

```yaml
# kubernetes/apps/monitoring/loki/app/objectbucketclaim.yaml
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: loki-bucket
  namespace: monitoring
spec:
  generateBucketName: loki
  storageClassName: ceph-bucket
  additionalConfig:
    maxObjects: "1000000"
    maxSize: "500Gi"
```

### Step 1.4: Configure S3 Credentials

Create External Secret for S3 credentials:

```yaml
# kubernetes/apps/monitoring/loki/app/externalsecret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: loki-s3-secret
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword-connect
    kind: ClusterSecretStore
  target:
    name: loki-s3-secret
    creationPolicy: Owner
  data:
    - secretKey: AWS_ACCESS_KEY_ID
      remoteRef:
        key: loki-s3-credentials
        property: access_key_id
    - secretKey: AWS_SECRET_ACCESS_KEY
      remoteRef:
        key: loki-s3-credentials
        property: secret_access_key
```

## Phase 2: Loki Deployment

### MCP Commands for Phase 2
```bash
# Monitor deployment progress
/mcp kubernetes:kubectl_get "helmrelease" "monitoring" "loki" "--watch"
/mcp kubernetes:kubectl_get "pods" "monitoring" "-l app.kubernetes.io/name=loki" "--watch"

# Check for errors
/mcp kubernetes:kubectl_describe "helmrelease" "monitoring" "loki"
/mcp kubernetes:kubectl_logs "monitoring" "-l app.kubernetes.io/name=loki" "--tail=50"

# Verify S3 connectivity from Loki
/mcp kubernetes:kubectl_exec "monitoring" "loki-write-0" "--" "curl" "-I" "http://rook-ceph-rgw-storage.storage.svc.cluster.local"
```

### Step 2.1: Create Loki HelmRelease

```yaml
# kubernetes/apps/monitoring/loki/app/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: loki
  namespace: monitoring
spec:
  interval: 30m
  timeout: 15m
  chart:
    spec:
      chart: loki
      version: 6.23.0  # Check for latest version
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: flux-system
  install:
    crds: Skip
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    crds: Skip
    remediation:
      strategy: rollback
      retries: 3
  values:
    # Simple scalable deployment mode
    deploymentMode: SimpleScalable
    
    loki:
      # Disable multi-tenancy for homelab
      auth_enabled: false
      
      # Use TSDB for index storage
      schemaConfig:
        configs:
          - from: "2024-04-01"
            store: tsdb
            object_store: s3
            schema: v13
            index:
              prefix: loki_index_
              period: 24h
      
      # S3 storage configuration
      storage:
        type: s3
        s3:
          endpoint: rook-ceph-rgw-storage.storage.svc.cluster.local
          region: us-east-1  # Required but ignored by Ceph
          bucketnames:
            chunks: loki-chunks
            ruler: loki-ruler
            admin: loki-admin
          s3ForcePathStyle: true
          insecure: true
      
      # Querier configuration
      querier:
        multi_tenant_queries_enabled: false
        max_concurrent: 20
      
      # Query frontend configuration
      query_frontend:
        compress_responses: true
        max_outstanding_per_tenant: 200
      
      # Limits configuration
      limits_config:
        retention_period: 720h  # 30 days
        retention_stream: []
        enforce_metric_name: false
        reject_old_samples: true
        reject_old_samples_max_age: 168h
        max_cache_freshness_per_query: 10m
        creation_grace_period: 10m
        ingestion_rate_mb: 50
        ingestion_burst_size_mb: 100
        max_query_parallelism: 100
        max_streams_per_user: 10000
        max_global_streams_per_user: 10000
    
    # Write component
    write:
      replicas: 3
      persistence:
        enabled: true
        storageClass: ceph-block
        size: 10Gi
      resources:
        requests:
          cpu: 1
          memory: 2Gi
        limits:
          cpu: 2
          memory: 4Gi
    
    # Read component
    read:
      replicas: 3
      persistence:
        enabled: true
        storageClass: ceph-block
        size: 5Gi
      resources:
        requests:
          cpu: 1
          memory: 2Gi
        limits:
          cpu: 2
          memory: 4Gi
    
    # Backend component
    backend:
      replicas: 1
      persistence:
        enabled: true
        storageClass: ceph-block
        size: 5Gi
      resources:
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: 1
          memory: 2Gi
    
    # Gateway configuration
    gateway:
      enabled: true
      replicas: 2
      ingress:
        enabled: false  # We'll use internal access only
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: 1
          memory: 1Gi
    
    # Monitoring
    monitoring:
      dashboards:
        enabled: true
        namespace: monitoring
      rules:
        enabled: true
        namespace: monitoring
      serviceMonitor:
        enabled: true
        namespace: monitoring
      selfMonitoring:
        enabled: true
        grafanaAgent:
          installOperator: false
    
    # Test
    test:
      enabled: false
```

### Step 2.2: Create Kustomization Files

```yaml
# kubernetes/apps/monitoring/loki/app/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
  - ./externalsecret.yaml
  - ./objectbucketclaim.yaml
  - ./helmrelease.yaml
```

```yaml
# kubernetes/apps/monitoring/loki/ks.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app loki
  namespace: flux-system
spec:
  targetNamespace: monitoring
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 30m
  timeout: 10m
  prune: true
  wait: true
  path: ./kubernetes/apps/monitoring/loki/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  dependsOn:
    - name: kube-prometheus-stack
      namespace: monitoring
    - name: external-secrets
      namespace: external-secrets
    - name: rook-ceph-cluster
      namespace: storage
```

## Phase 3: Alloy Configuration (Modern Log Agent)

### MCP Commands for Phase 3
```bash
# Research Alloy configuration options
/mcp context7:get-library-docs /grafana/alloy "kubernetes discovery" 3000

# Monitor Alloy deployment
/mcp kubernetes:kubectl_get "daemonset" "monitoring" "alloy" "--watch"
/mcp kubernetes:kubectl_get "pods" "monitoring" "-l app.kubernetes.io/name=alloy"

# Verify log collection
/mcp kubernetes:kubectl_logs "monitoring" "-l app.kubernetes.io/name=alloy" "--tail=50" | grep "level=info"

# Check Alloy metrics
/mcp kubernetes:kubectl_exec "monitoring" "alloy-xxxxx" "--" "curl" "localhost:12345/metrics" | grep "alloy_"
```

### Step 3.1: Create Alloy HelmRelease

**Note**: Alloy is the modern replacement for Promtail, offering better performance and features.

```yaml
# kubernetes/apps/monitoring/alloy/app/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: alloy
  namespace: monitoring
spec:
  interval: 30m
  timeout: 15m
  chart:
    spec:
      chart: alloy
      version: 1.1.1  # Latest stable version
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: flux-system
  install:
    crds: Skip
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    crds: Skip
    remediation:
      strategy: rollback
      retries: 3
  values:
    alloy:
      configMap:
        create: true
        content: |
          logging {
            level = "info"
          }
          
          // Kubernetes discovery
          discovery.kubernetes "pods" {
            role = "pod"
          }
          
          // Relabel pods
          discovery.relabel "pods" {
            targets = discovery.kubernetes.pods.targets
            
            // Keep only running pods
            rule {
              source_labels = ["__meta_kubernetes_pod_phase"]
              regex         = "Pending|Succeeded|Failed|Completed|Unknown"
              action        = "drop"
            }
            
            // Add labels
            rule {
              source_labels = ["__meta_kubernetes_namespace"]
              target_label  = "namespace"
            }
            
            rule {
              source_labels = ["__meta_kubernetes_pod_name"]
              target_label  = "pod"
            }
            
            rule {
              source_labels = ["__meta_kubernetes_pod_container_name"]
              target_label  = "container"
            }
            
            rule {
              source_labels = ["__meta_kubernetes_pod_node_name"]
              target_label  = "node"
            }
            
            // Add all pod labels
            rule {
              action = "labelmap"
              regex  = "__meta_kubernetes_pod_label_(.+)"
            }
            
            // Set path to container logs
            rule {
              source_labels = ["__meta_kubernetes_pod_uid", "__meta_kubernetes_pod_container_name"]
              target_label  = "__path__"
              separator     = "/"
              replacement   = "/var/log/pods/*$1/$2/*.log"
            }
          }
          
          // Collect logs
          loki.source.kubernetes_logs "pods" {
            targets    = discovery.relabel.pods.output
            forward_to = [loki.process.logs.receiver]
          }
          
          // Process logs
          loki.process "logs" {
            forward_to = [loki.write.default.receiver]
            
            // Parse JSON logs
            stage.json {
              expressions = {
                output = "log",
                level  = "level",
              }
            }
            
            // Extract level from message
            stage.regex {
              expression = "(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)"
            }
            
            // Add labels
            stage.labels {
              values = {
                level = "",
              }
            }
            
            // Drop debug logs from noisy sources
            stage.drop {
              source = "namespace"
              expression = "kube-system|kube-public"
            }
          }
          
          // Write to Loki
          loki.write "default" {
            endpoint {
              url = "http://loki-gateway.monitoring.svc.cluster.local/loki/api/v1/push"
              
              headers = {
                "X-Scope-OrgID" = "1",
              }
            }
            
            // Batching configuration
            batching {
              timeout = "10s"
              size_bytes = 1048576  // 1MB
            }
          }
          
          // Export metrics
          prometheus.exporter.self "alloy" {}
          
          // Scrape own metrics
          prometheus.scrape "alloy" {
            targets = prometheus.exporter.self.alloy.targets
            forward_to = [prometheus.remote_write.monitoring.receiver]
          }
          
          // Send metrics to Prometheus
          prometheus.remote_write "monitoring" {
            endpoint {
              url = "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090/api/v1/write"
            }
          }
    
    # Controller configuration
    controller:
      type: daemonset
      
      # Resources
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: 1
          memory: 1Gi
      
      # Volume mounts for log access
      volumes:
        - name: varlog
          hostPath:
            path: /var/log
        - name: varlibdockercontainers
          hostPath:
            path: /var/lib/docker/containers
      
      volumeMounts:
        - name: varlog
          mountPath: /var/log
          readOnly: true
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
      
      # Security context
      securityContext:
        privileged: true
        runAsUser: 0
    
    # Service monitor
    serviceMonitor:
      enabled: true
```

### Step 3.2: Create Alloy Kustomization

```yaml
# kubernetes/apps/monitoring/alloy/app/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
  - ./helmrelease.yaml
```

```yaml
# kubernetes/apps/monitoring/alloy/ks.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app alloy
  namespace: flux-system
spec:
  targetNamespace: monitoring
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 30m
  timeout: 10m
  prune: true
  wait: true
  path: ./kubernetes/apps/monitoring/alloy/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  dependsOn:
    - name: loki
      namespace: monitoring
```

## Phase 4: Integration & Testing

### MCP Commands for Phase 4
```bash
# Verify all components are running
/mcp kubernetes:kubectl_get "pods" "monitoring" "-l app.kubernetes.io/part-of=loki"
/mcp kubernetes:kubectl_get "pods" "monitoring" "-l app.kubernetes.io/name=alloy"

# Test log ingestion with a test pod
/mcp kubernetes:kubectl_generic "run" "test-logger" "--image=busybox" "--restart=Never" "--" "sh" "-c" "while true; do echo 'Test log message $(date)'; sleep 5; done"

# Query logs via Loki API
/mcp kubernetes:kubectl_exec "monitoring" "loki-read-0" "--" "curl" "-s" "http://localhost:3100/loki/api/v1/query" "--data-urlencode" "query={pod=\"test-logger\"}"

# Check Grafana datasource connectivity
/mcp kubernetes:kubectl_exec "monitoring" "-l app.kubernetes.io/name=grafana" "--" "curl" "-s" "http://loki-gateway:80/ready"
```

### Step 4.1: Configure Grafana Data Source

Add Loki data source to Grafana:

```yaml
# Add to kube-prometheus-stack values
grafana:
  additionalDataSources:
    - name: Loki
      type: loki
      access: proxy
      url: http://loki-gateway.monitoring.svc.cluster.local
      isDefault: false
      jsonData:
        maxLines: 5000
```

### Step 4.2: Import Dashboards

1. Log Overview Dashboard
2. Pod Logs Dashboard
3. Namespace Logs Dashboard
4. Loki Performance Dashboard

### Step 4.3: Test Log Ingestion

```bash
# Deploy test pod
kubectl run test-logger --image=busybox --restart=Never -- \
  sh -c 'while true; do echo "Test log message $(date)"; sleep 5; done'

# Check logs in Grafana
# Query: {pod="test-logger"}

# Cleanup
kubectl delete pod test-logger
```

## Phase 5: Migration & Optimization

### Step 5.1: Update Airflow Configuration

Modify Airflow to use stdout logging:

```yaml
# Update airflow helmrelease
airflow:
  config:
    AIRFLOW__LOGGING__REMOTE_LOGGING: "False"
    AIRFLOW__LOGGING__LOGGING_LEVEL: "INFO"
    AIRFLOW__CORE__COLORED_CONSOLE_LOG: "False"
```

### Step 5.2: Implement Log Filtering

Add namespace-specific retention:

```yaml
# High-retention namespaces
stage.match {
  selector = '{namespace=~"airflow|production"}'
  
  stage.labels {
    values = {
      retention = "90d",
    }
  }
}

# Standard retention
stage.match {
  selector = '{namespace!~"airflow|production"}'
  
  stage.labels {
    values = {
      retention = "30d",
    }
  }
}
```

### Step 5.3: Performance Tuning

1. **Index Optimization**
   - Enable bloom filters for high-cardinality labels
   - Configure appropriate chunk_target_size
   - Tune max_look_back_period

2. **Query Optimization**
   - Use LogQL best practices
   - Implement query result caching
   - Set appropriate query timeouts

## Validation Checklist

- [ ] All pods in monitoring namespace are Running
- [ ] Loki gateway is accessible
- [ ] Test logs appear in Grafana
- [ ] Metrics are being collected
- [ ] S3 buckets are created and accessible
- [ ] Retention policies are applied
- [ ] Dashboards are imported
- [ ] Alerts are configured

## Troubleshooting

### MCP-Powered Troubleshooting
```bash
# Get comprehensive deployment status
/mcp kubernetes:kubectl_get "all" "monitoring" "-l app.kubernetes.io/part-of=loki"

# Check Flux reconciliation status
/mcp kubernetes:kubectl_describe "kustomization" "flux-system" "loki"
/mcp kubernetes:kubectl_describe "helmrelease" "monitoring" "loki"

# Analyze configuration issues
/mcp sequential-thinking:sequential_thinking "Loki pods are in CrashLoopBackOff with error 'failed to create S3 client'. The S3 endpoint is configured as http://rook-ceph-rgw-storage.storage.svc.cluster.local. What are the most likely causes and how to debug?"

# Get expert guidance on specific errors
/mcp context7:get-library-docs /grafana/loki "troubleshooting s3 connection" 3000
```

### Common Issues

1. **S3 Connection Errors**
   ```bash
   # Check S3 credentials
   kubectl get secret loki-s3-secret -n monitoring -o yaml
   
   # Test S3 connectivity
   kubectl exec -n storage deploy/rook-ceph-tools -- \
     s3cmd --host=rook-ceph-rgw-storage.storage ls
   ```

2. **No Logs Appearing**
   ```bash
   # Check Alloy logs
   kubectl logs -n monitoring -l app.kubernetes.io/name=alloy
   
   # Verify discovery
   kubectl exec -n monitoring -l app.kubernetes.io/name=alloy -- \
     alloy-linux-amd64 --config.file=/etc/alloy/config.river \
     --config.check
   ```

3. **High Memory Usage**
   - Reduce ingestion_burst_size_mb
   - Lower max_outstanding_per_tenant
   - Enable adaptive_concurrency

## Next Steps

1. Monitor system for 24-48 hours
2. Adjust resource allocations based on usage
3. Implement advanced features (multi-tenancy, recording rules)
4. Document operational procedures
5. Train team on LogQL queries

---

**Guide Version**: 1.0  
**Last Updated**: January 2025  
**Status**: READY FOR IMPLEMENTATION