# How to add Loki and Alloy to your Flux setup

Here's how to integrate Loki with Grafana Alloy in your `kube-prometheus-stack`:

## MCP Server Usage for Setup

Use MCP servers to ensure correct implementation:

### Pre-Setup Research
```bash
# Get latest Helm chart versions
/mcp context7:get-library-docs /grafana/loki "helm chart installation" 3000
/mcp context7:get-library-docs /grafana/alloy "helm chart deployment" 3000

# Understand configuration options
/mcp context7:get-library-docs /grafana/loki "simple scalable vs monolithic" 4000

# Check for breaking changes
/mcp sequential-thinking:sequential_thinking "Analyze the migration path from Loki chart v5.x to v6.x, highlighting breaking changes in values.yaml structure"
```

### During Setup
```bash
# Verify Helm repository addition
/mcp kubernetes:kubectl_get "helmrepository" "flux-system" "grafana-charts"

# Monitor Flux Kustomization
/mcp kubernetes:kubectl_get "kustomization" "flux-system" "--watch"

# Check deployment status
/mcp kubernetes:kubectl_get "statefulset" "monitoring" "loki"
/mcp kubernetes:kubectl_get "daemonset" "monitoring" "alloy"

# Debug configuration issues
/mcp kubernetes:kubectl_logs "monitoring" "-l app.kubernetes.io/name=loki" "--tail=100"
```

### Configuration Validation
```bash
# Validate Alloy River configuration
/mcp sequential-thinking:sequential_thinking "Review this Alloy River configuration for best practices: loki.source.kubernetes with discovery.kubernetes pods role, filtering kube-system namespace"

# Check Loki schema configuration
/mcp context7:get-library-docs /grafana/loki "tsdb index schema v13" 3000
```

**1. Add Grafana Helm Repository (if not already done)**

This step remains the same, as both Loki and Alloy charts can be found here or
in Grafana's OCI registry.

Create `kubernetes/flux/meta/repos/grafana-charts.yaml`:

```yaml
# kubernetes/flux/meta/repos/grafana-charts.yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: grafana-charts
  namespace: flux-system
spec:
  interval: 1h
  url: https://grafana.github.io/helm-charts
```

Update `kubernetes/flux/meta/repos/kustomization.yaml`:

```yaml
# kubernetes/flux/meta/repos/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  # ... your existing repositories ...
  - ./prometheus-community.yaml
  - ./grafana-charts.yaml # Ensure this line is present
  - ./1password-connect.yaml
  # ... rest of your repositories ...
```

**2. Create Loki Application Structure (Promtail Disabled)**

The Loki deployment itself remains largely the same, but internal Promtail will
be disabled.

`kubernetes/apps/monitoring/loki/ks.yaml`:

```yaml
# kubernetes/apps/monitoring/loki/ks.yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app loki
  namespace: flux-system
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
    - name: local-path-provisioner
      namespace: storage
    - name: kube-prometheus-stack
      namespace: monitoring
  interval: 15m
  path: ./kubernetes/apps/monitoring/loki/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: monitoring
  timeout: 10m
  wait: true
  healthChecks:
    - apiVersion: apps/v1
      kind: StatefulSet # Loki in single binary mode runs as a StatefulSet
      name: loki # Default HelmRelease name for Loki statefulset
      namespace: monitoring
```

_(Removed Promtail DaemonSet health check from here)_

`kubernetes/apps/monitoring/loki/app/kustomization.yaml` (remains the same):

```yaml
# kubernetes/apps/monitoring/loki/app/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
```

`kubernetes/apps/monitoring/loki/app/helmrelease.yaml` (update to disable
Promtail):

```yaml
# kubernetes/apps/monitoring/loki/app/helmrelease.yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: loki
  namespace: monitoring
spec:
  interval: 15m
  chart:
    spec:
      chart: loki
      version: "6.11.0" # Pin to a specific chart version
      sourceRef:
        kind: HelmRepository
        name: grafana-charts
        namespace: flux-system
      interval: 5m
  targetNamespace: monitoring
  install:
    remediation:
      retries: 3
  upgrade:
    remediation:
      retries: 3
      remediateLastFailure: true
    cleanupOnFail: true
  values:
    loki:
      auth_enabled: false
      commonConfig:
        replication_factor: 1
      configMap:
        schema_config:
          configs:
            - from: "2024-01-01"
              store: tsdb
              object_store: filesystem
              schema: v13
              index:
                prefix: loki_tsdb_index_
                period: 24h
        compactor:
          working_directory: /var/loki/compactor
          retention_enabled: true
          delete_request_store: boltdb-shipper
          retention_delete_delay: 2h
          retention_delete_worker_count: 150
        limits:
          retention_period: 48h # 2-day retention
          enforce_metric_name: false
          reject_old_samples: true
          reject_old_samples_max_age: 168h
          max_query_series: 5000
          ingestion_rate_mb: 100
          ingestion_burst_size_mb: 200
      storage:
        type: filesystem
      serviceMonitor:
        enabled: true

    persistence:
      enabled: true
      storageClassName: local-path
      size: 20Gi

    promtail:
      enabled: false # Disable Promtail from the Loki chart

    grafana:
      enabled: false
    gateway:
      enabled: false
    backend:
      replicas: 1
    read:
      replicas: 0
    write:
      replicas: 0
```

**3. Create Grafana Alloy Application Structure**

Now, set up Grafana Alloy to collect logs.

Create `kubernetes/apps/monitoring/alloy/ks.yaml`:

```yaml
# kubernetes/apps/monitoring/alloy/ks.yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app alloy
  namespace: flux-system
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
    - name: loki # Alloy needs Loki to be available to send logs
      namespace: monitoring
  interval: 15m
  path: ./kubernetes/apps/monitoring/alloy/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: monitoring # Deploy Alloy to the 'monitoring' namespace
  timeout: 10m
  wait: true
  healthChecks:
    - apiVersion: apps/v1
      kind: DaemonSet
      name: alloy # Default HelmRelease name for an Alloy DaemonSet
      namespace: monitoring
```

Create `kubernetes/apps/monitoring/alloy/app/kustomization.yaml`:

```yaml
# kubernetes/apps/monitoring/alloy/app/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./configmap-alloy.yaml
  - ./helmrelease.yaml
```

Create `kubernetes/apps/monitoring/alloy/app/configmap-alloy.yaml` for the Alloy
configuration:

```yaml
# kubernetes/apps/monitoring/alloy/app/configmap-alloy.yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: alloy-config
  namespace: monitoring
data:
  alloy.river: |
    logging {
      level  = "info"
      format = "logfmt"
    }

    // Discover and tail logs from all Kubernetes pods on the node
    // It automatically enriches logs with labels like pod, container, namespace, and node_name.
    loki.source.kubernetes "default" {
      forward_to = [loki.write.default.receiver]
      // The component automatically uses the HOSTNAME env var to filter logs for the current node.
      // You can add more specific selectors if needed within a 'client' block.
      // client {
      //   api_server = null // Defaults to in-cluster config
      // }
    }

    // Send logs to the Loki service
    loki.write "default" {
      endpoint {
        url = "http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push"
      }
      external_labels = {
        cluster = "wcygan-anton", // Customize with your cluster name
        collector = "alloy",
      }
    }

    // Optional: Expose Alloy's own metrics for Prometheus to scrape
    prometheus.scrape "self" {
      targets = [{"__address__" = "127.0.0.1:12345"}] // Default Alloy metrics port
      forward_to = [prometheus.remote_write.default.receiver] // If you want to send to a remote_write endpoint
                                                               // Or just let Prometheus scrape it via ServiceMonitor
    }
    // Dummy remote_write to satisfy the scrape component if not sending elsewhere.
    // If using ServiceMonitor (recommended), this remote_write isn't strictly needed for self-scrape.
    prometheus.remote_write "default" {
      endpoint {
        url = "http://this-is-a-dummy-url.com/api/v1/write" // Will not be used if only self-scraping for local Prometheus
      }
    }
```

Create `kubernetes/apps/monitoring/alloy/app/helmrelease.yaml`:

```yaml
# kubernetes/apps/monitoring/alloy/app/helmrelease.yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: alloy # This will be the release name
  namespace: monitoring
spec:
  interval: 15m
  chart:
    spec:
      # Use the OCI chart for Alloy.
      # Check for the latest version from: https://github.com/grafana/alloy/releases
      chart: oci://ghcr.io/grafana/alloy-charts/alloy
      version: "v1.1.1" # Example: Pin to a specific Alloy chart version
      sourceRef: # OCI charts don't use HelmRepository sourceRef, but this is how Flux handles OCI
        kind: OCIRepository # This kind implicitly means the chart is from an OCI registry
        name: grafana-alloy-charts # A dummy name for the OCI source if not globally defined
      # For OCI, `url` is part of the chart spec.
      # If you have a global OCIRepository defined for ghcr.io/grafana/alloy-charts, you can reference it.
      # Otherwise, Flux resolves the chart path directly.
      # For clarity, ensure you have an OCIRepository defined in flux-system similar to:
      # apiVersion: source.toolkit.fluxcd.io/v1beta2
      # kind: OCIRepository
      # metadata:
      #   name: grafana-alloy-charts
      #   namespace: flux-system
      # spec:
      #   interval: 1h
      #   url: oci://ghcr.io/grafana/alloy-charts
      #   ref:
      #     tag: vX.Y.Z # A tag that ensures the chart images are pulled, or a digest
      interval: 5m
  targetNamespace: monitoring
  install:
    remediation:
      retries: 3
  upgrade:
    remediation:
      retries: 3
      remediateLastFailure: true
    cleanupOnFail: true
  values:
    # Deploy Alloy as a DaemonSet to collect logs from each node
    controller:
      type: "daemonset" # This is often the default or set via presets like 'logging'
    # The Alloy chart has presets. Using the 'logging' preset is common.
    # configReloader:
    #   enabled: true # Usually enabled by default

    # Mount the ConfigMap containing alloy.river
    configMap:
      create: false # We are creating it separately
      name: "alloy-config"
      content: "" # Important: Set to empty string when using an existing ConfigMap and specifying `configMap.name`
    # The chart will use the file `alloy.river` from the existing ConfigMap.

    # RBAC for Kubernetes service discovery and log reading
    # The chart should configure appropriate RBAC by default.
    # Ensure it has permissions to read pod logs and discover pods.

    # Expose Alloy's metrics for Prometheus
    serviceMonitor:
      enabled: true
      # namespace: monitoring # Redundant if deploying HR in monitoring
      # scheme: http
      # port: http-metrics # Default metrics port in chart is often 'http-metrics' or 12345
      # path: /metrics

    # Ensure Alloy pods have access to /var/log/pods
    # This is typically handled by the chart's daemonset spec with hostPath volumes.
    # Example (actual values depend on the chart's structure):
    daemonset:
      extraVolumeMounts:
        - name: varlog
          mountPath: /var/log
          readOnly: true
      extraVolumes:
        - name: varlog
          hostPath:
            path: /var/log
```

_Note on Alloy Helm Chart_: The official Helm chart for Alloy is at
`oci://ghcr.io/grafana/alloy-charts/alloy`. You might need to define an
`OCIRepository` source in your Flux setup if you haven't already for
`ghcr.io/grafana/alloy-charts`. Or, some versions of Flux Helm controller can
directly pull OCI charts specified like this. If you have a global
`OCIRepository` for `ghcr.io/grafana/alloy-charts`, ensure `chart.sourceRef`
points to it. Otherwise, Flux's Helm controller (v0.32.0+) should be ableto
fetch OCI charts directly.

**4. Configure Grafana Data Source (remains the same)**

This part of the configuration in
`kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml` doesn't
change, as Grafana will still connect to the Loki service.

```yaml
# kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml
# ... (previous content) ...
grafana:
  enabled: true
  adminPassword: "prom-operator"
  additionalDataSources:
    - name: Loki
      type: loki
      url: http://loki.monitoring.svc.cluster.local:3100
      access: proxy
      isDefault: false
# ... (rest of the content) ...
```

**5. Update Monitoring Kustomization**

Add the Alloy Kustomization to your main monitoring Kustomization.

Edit `kubernetes/apps/monitoring/kustomization.yaml`:

```yaml
# kubernetes/apps/monitoring/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
components:
  - ../../components/common
resources:
  - ./kube-prometheus-stack/ks.yaml
  - ./loki/ks.yaml
  - ./alloy/ks.yaml # Add this line
```

**6. Commit and Push Changes**

Commit these new and modified files to your Git repository. Flux will apply the
changes:

- Deploy Loki (without Promtail).
- Deploy Grafana Alloy as a DaemonSet.
- Alloy will collect logs using the `loki.source.kubernetes` component and send
  them to Loki.
- Your Grafana instance will be able to query these logs from Loki.

**Explanation of Changes for Alloy:**

- **Promtail Disabled**: In Loki's HelmRelease (`loki/app/helmrelease.yaml`),
  `promtail.enabled` is set to `false`.
- **Alloy Deployment**: A new application `alloy` is created in the `monitoring`
  namespace. It's deployed as a DaemonSet using its official Helm chart
  ([oci://ghcr.io/grafana/alloy-charts/alloy](https://github.com/grafana/alloy)).
- **Alloy Configuration (`alloy.river`)**:
  - The configuration uses `loki.source.kubernetes` to discover and tail logs
    from all pods on the node where the Alloy instance is running. This
    component automatically adds standard Kubernetes labels (pod, namespace,
    container, node, etc.).
    [Migrate from Promtail to Grafana Alloy | Grafana Alloy documentation](https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/)
    highlights that Alloy can replace Promtail.
  - Logs are then forwarded to `loki.write`, which sends them to your Loki
    service (`http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push`).
  - `external_labels` like `cluster` and `collector` are added for better
    context.
- **Dependencies**: The Alloy Kustomization (`alloy/ks.yaml`) depends on Loki's
  Kustomization to ensure the Loki service endpoint is available.
- **Metrics**: The Alloy chart is configured with `serviceMonitor.enabled: true`
  so Prometheus can scrape Alloy's own operational metrics.

This setup provides a modern way to collect logs using Grafana Alloy, which is
designed to be a unified telemetry collector.