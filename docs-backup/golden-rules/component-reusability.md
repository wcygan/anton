# Component Reusability Golden Rules

## The Golden Rule

**Never copy-paste configurations across applications.** Use Kustomize components, Helm templates, or base configurations. Duplication leads to drift, inconsistency, and maintenance nightmares.

## Critical Rules

### 1. Always Use Kustomize Components for Shared Functionality

**WRONG:**
```yaml
# Copying the same volsync config to every app
# app1/volsync.yaml
apiVersion: volsync.backube/v1alpha1
kind: ReplicationSource
metadata:
  name: app1-backup
spec:
  sourcePVC: app1-data
  # 20 lines of identical config...

# app2/volsync.yaml (copy-pasted)
apiVersion: volsync.backube/v1alpha1
kind: ReplicationSource
metadata:
  name: app2-backup
spec:
  sourcePVC: app2-data
  # Same 20 lines...
```

**RIGHT:**
```yaml
# components/volsync/volsync.yaml
apiVersion: volsync.backube/v1alpha1
kind: ReplicationSource
metadata:
  name: "${APP}"
spec:
  sourcePVC: "${APP}"
  trigger:
    schedule: "0 */6 * * *"
  # Shared configuration

# app1/ks.yaml
spec:
  components:
    - ../../../components/volsync
  postBuild:
    substitute:
      APP: app1
      VOLSYNC_CAPACITY: 10Gi
```

**Why:** Components ensure consistency and allow central updates. Change once, apply everywhere.

### 2. Never Hardcode Environment-Specific Values

**WRONG:**
```yaml
# Hardcoded production URL in base
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  api_url: "https://api.production.com"  # What about staging?
```

**RIGHT:**
```yaml
# base/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  api_url: "${API_URL}"

# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - api_url=https://api.production.com

# overlays/staging/kustomization.yaml  
configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - api_url=https://api.staging.com
```

**Why:** Environment-specific values in base configurations break multi-environment deployments.

### 3. Always Version Shared Components

**WRONG:**
```yaml
# Using components without version tracking
components:
  - ../../../components/monitoring  # Which version?
```

**RIGHT:**
```yaml
# Method 1: Git tags for versions
components:
  - https://github.com/org/k8s-components//monitoring?ref=v1.2.0

# Method 2: Local versioning with clear structure
components:
  - ../../../components/monitoring/v2  # Versioned directory

# Document breaking changes
# components/monitoring/v2/CHANGELOG.md
# v2.0.0 - Breaking: Changed metric names
# v1.2.0 - Added new dashboard
```

**Why:** Unversioned components can break consumers when updated. Versioning enables gradual migration.

### 4. Never Mix Concerns in a Single Component

**WRONG:**
```yaml
# components/kitchen-sink/kustomization.yaml
resources:
  - monitoring.yaml
  - backup.yaml
  - networkpolicy.yaml
  - scaling.yaml
  # Too many unrelated things!
```

**RIGHT:**
```yaml
# Separate components by concern
# components/monitoring/kustomization.yaml
resources:
  - servicemonitor.yaml
  - prometheusrule.yaml

# components/backup/kustomization.yaml
resources:
  - volsync.yaml
  - backup-policy.yaml

# Apps choose what they need
components:
  - ../../../components/monitoring
  - ../../../components/backup
```

**Why:** Single-purpose components are easier to understand, test, and selectively apply.

### 5. Always Provide Sensible Defaults with Override Capability

**WRONG:**
```yaml
# Component requires tons of variables
# components/app-template/deployment.yaml
replicas: ${REPLICAS}  # No default
resources:
  requests:
    cpu: ${CPU_REQUEST}  # No default
    memory: ${MEMORY_REQUEST}  # No default
```

**RIGHT:**
```yaml
# Component with defaults
# components/app-template/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Component

replacements:
  - source:
      kind: ConfigMap
      name: component-values
      fieldPath: data.replicas
    targets:
      - select:
          kind: Deployment
        fieldPaths:
          - spec.replicas
        options:
          create: true

configMapGenerator:
  - name: component-values
    literals:
      - replicas=2  # Sensible default
      - cpu_request=100m
      - memory_request=128Mi
```

**Why:** Defaults make components immediately usable while allowing customization when needed.

## Component Design Patterns

### Standard App Template

```yaml
# components/app-template/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Component

resources:
  - deployment.yaml
  - service.yaml
  - networkpolicy.yaml

replacements:
  - source:
      kind: ConfigMap
      name: app-config
      fieldPath: data.app_name
    targets:
      - select:
          kind: Deployment
        fieldPaths:
          - metadata.name
          - spec.selector.matchLabels.app
          - spec.template.metadata.labels.app
      - select:
          kind: Service
        fieldPaths:
          - metadata.name
          - spec.selector.app

configMapGenerator:
  - name: app-config
    literals:
      - app_name=${APP_NAME}
      - image=${IMAGE:-nginx:latest}
      - port=${PORT:-8080}
```

### Monitoring Component

```yaml
# components/monitoring/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Component

resources:
  - servicemonitor.yaml
  - prometheusrule.yaml

patches:
  - target:
      kind: ServiceMonitor
    patch: |-
      - op: replace
        path: /metadata/name
        value: ${APP}-metrics
      - op: replace
        path: /spec/selector/matchLabels/app
        value: ${APP}

  - target:
      kind: PrometheusRule
    patch: |-
      - op: replace
        path: /metadata/name
        value: ${APP}-alerts
```

### Security Component

```yaml
# components/security-baseline/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Component

patches:
  - target:
      kind: Deployment
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: not-important
      spec:
        template:
          spec:
            securityContext:
              runAsNonRoot: true
              runAsUser: 1000
              runAsGroup: 1000
              fsGroup: 1000
            containers:
            - name: not-important
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities:
                  drop: ["ALL"]
```

## Helm Chart Patterns

### Subchart Pattern

```yaml
# Chart.yaml
dependencies:
  - name: common
    version: 1.x.x
    repository: https://charts.example.com
    import-values:
      - default

# values.yaml
common:
  app:
    name: myapp
    image: myapp:latest
  
  service:
    enabled: true
    type: ClusterIP
  
  ingress:
    enabled: true
    className: nginx
```

### Library Chart Pattern

```yaml
# charts/lib/templates/_deployment.yaml
{{- define "lib.deployment" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "lib.fullname" . }}
spec:
  replicas: {{ .Values.replicas | default 2 }}
  selector:
    matchLabels:
      {{- include "lib.selectorLabels" . | nindent 6 }}
  template:
    spec:
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        {{- include "lib.securityContext" . | nindent 8 }}
{{- end }}

# Using the library
{{ include "lib.deployment" . }}
```

## Testing Components

### Component Validation

```bash
# Test component with different substitutions
kustomize build --load-restrictor=LoadRestrictionsNone \
  --enable-alpha-plugins \
  <(cat <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

components:
  - ../components/monitoring

configMapGenerator:
  - name: test-values
    literals:
      - APP=test-app
      - NAMESPACE=test-ns
EOF
)
```

### Automated Testing

```yaml
# .github/workflows/test-components.yaml
name: Test Components
on:
  pull_request:
    paths:
      - 'components/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Test each component builds
        run: |
          for component in components/*/; do
            echo "Testing $component"
            kustomize build "$component" --enable-alpha-plugins
          done
```

## Pre-Operation Checklist

- [ ] Check if functionality already exists in components/
- [ ] Design component with single responsibility
- [ ] Provide sensible defaults for all parameters
- [ ] Document required and optional variables
- [ ] Version component if making breaking changes
- [ ] Test component with multiple configurations
- [ ] Update consuming applications gradually
- [ ] Document migration path for breaking changes

## Incidents

### 2024-06-20: Mass Breakage from Component Update
- **What happened:** Updated monitoring component, broke 30+ apps
- **Impact:** Lost metrics for 4 hours across all services
- **Root cause:** Breaking change in unversioned component
- **Lesson:** Always version components with breaking changes

### 2024-08-10: Configuration Drift Nightmare
- **What happened:** Copy-pasted configs drifted over 6 months
- **Impact:** Some apps had security patches, others didn't
- **Root cause:** No component reuse, just copy-paste
- **Lesson:** Never copy-paste, always use components

### 2024-10-05: Environment Config Leak
- **What happened:** Production URLs hardcoded in base leaked to dev
- **Impact:** Dev environment hitting production APIs
- **Root cause:** Environment-specific values in shared base
- **Lesson:** Always parameterize environment-specific values