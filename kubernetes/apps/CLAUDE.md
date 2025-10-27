# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with Kubernetes applications in this repository.

## Project Overview

This directory contains Flux-managed Kubernetes applications organized by namespace. Each app follows a strict 3-file pattern that makes adding new applications predictable and safe.

**Key Concept**: Every app has exactly 3 mandatory files:
1. `{app}/ks.yaml` - Tells Flux to watch Git for changes
2. `{app}/app/kustomization.yaml` - Lists all Kubernetes resources
3. `{app}/app/helmrelease.yaml` + `{app}/app/ocirepository.yaml` - Deploys Helm chart

## The 3-File Pattern (Mandatory Structure)

```
kubernetes/apps/{namespace}/
├── namespace.yaml              # Creates namespace (prune disabled)
├── kustomization.yaml          # Lists all apps in this namespace
└── {app-name}/
    ├── ks.yaml                 # Flux Kustomization (watches Git)
    └── app/
        ├── kustomization.yaml  # Lists resources to apply
        ├── helmrelease.yaml    # Helm chart deployment
        ├── ocirepository.yaml  # Where to pull chart from
        └── secret.sops.yaml    # (Optional) Encrypted secrets
```

**Why this structure?**
- Flux watches `ks.yaml` → detects Git changes → applies resources in `app/`
- Kustomize reads `app/kustomization.yaml` → applies all listed resources
- HelmRelease references OCIRepository → pulls chart → deploys with values
- Secrets encrypted with SOPS → Flux decrypts before applying

## Adding a New Application (Simple Checklist)

Use this exact sequence (no variations):

```bash
# 1. Create directory structure
mkdir -p kubernetes/apps/{namespace}/{app-name}/app

# 2. Create ks.yaml (Flux watcher)
cat > kubernetes/apps/{namespace}/{app-name}/ks.yaml <<EOF
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: {app-name}
spec:
  interval: 1h
  path: ./kubernetes/apps/{namespace}/{app-name}/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: {namespace}
  wait: false
  postBuild:
    substituteFrom:
      - name: cluster-secrets
        kind: Secret
EOF

# 3. Create app/kustomization.yaml (resource list)
cat > kubernetes/apps/{namespace}/{app-name}/app/kustomization.yaml <<EOF
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./ocirepository.yaml
EOF

# 4. Create app/ocirepository.yaml (chart source)
cat > kubernetes/apps/{namespace}/{app-name}/app/ocirepository.yaml <<EOF
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: {app-name}
spec:
  interval: 15m
  url: oci://ghcr.io/{org}/charts/{chart}
  ref:
    tag: {version}
EOF

# 5. Create app/helmrelease.yaml (deployment)
cat > kubernetes/apps/{namespace}/{app-name}/app/helmrelease.yaml <<EOF
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: {app-name}
spec:
  chartRef:
    kind: OCIRepository
    name: {app-name}
  interval: 1h
  values:
    # Chart-specific configuration
EOF

# 6. Add app to namespace kustomization
echo "  - ./{app-name}/ks.yaml" >> kubernetes/apps/{namespace}/kustomization.yaml

# 7. Validate and encrypt
task configure
```

## Variable Substitution Flow

Variables flow through 3 stages (in order):

**Stage 1: Template Rendering** (`cluster.yaml` → manifests)
- Run: `task configure`
- Jinja2 replaces: `{{ cloudflare_domain }}` → actual value
- Output: `${SECRET_DOMAIN}` in manifests (Flux variable)

**Stage 2: Flux Substitution** (Secret → `${VAR}`)
- Flux reads: `kubernetes/components/sops/cluster-secrets.sops.yaml`
- Replaces: `${SECRET_DOMAIN}`, `${SECRET_DOMAIN_TWO}`, etc.
- Happens: At reconciliation time (when Flux applies)

**Stage 3: Helm Templating** (`{{ .Release.Name }}`)
- Helm replaces: `{{ .Values.foo }}`, `{{ .Release.Name }}`
- Happens: During HelmRelease installation
- After: Flux substitution completes

**Common mistake**: Using `${VAR}` in HelmRelease values without adding `postBuild.substituteFrom` in ks.yaml

## File-by-File Breakdown

### ks.yaml (Flux Kustomization CR)

**Purpose**: Tells Flux to watch this app's directory for changes

**Critical fields**:
- `spec.path` - MUST be `./kubernetes/apps/{namespace}/{app}/app`
- `spec.targetNamespace` - MUST match namespace directory name
- `spec.prune: true` - Auto-cleanup old resources (always use true)
- `spec.wait: false` - Don't block if app fails (use true for critical services only)
- `spec.postBuild.substituteFrom` - Required for `${SECRET_DOMAIN}` substitution

**Example** (kubernetes/apps/default/echo/ks.yaml:1):
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: echo
spec:
  interval: 1h
  path: ./kubernetes/apps/default/echo/app
  postBuild:
    substituteFrom:
      - name: cluster-secrets
        kind: Secret
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: default
  wait: false
```

### app/kustomization.yaml (Resource List)

**Purpose**: Lists all Kubernetes objects to apply

**Mandatory resources**:
- `./helmrelease.yaml` - Always required
- `./ocirepository.yaml` - Always required (for OCI charts)

**Optional resources**:
- `./secret.sops.yaml` - Encrypted secrets
- `./httproute.yaml` - Gateway API routes
- `./certificate.yaml` - TLS certificates
- `./dnsendpoint.yaml` - DNS records
- Custom CRDs specific to the app

**Example** (kubernetes/apps/network/envoy-gateway/app/kustomization.yaml:1):
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./certificate.yaml
  - ./envoy.yaml
  - ./helmrelease.yaml
  - ./ocirepository.yaml
  - ./podmonitor.yaml
```

### app/helmrelease.yaml (Helm Chart)

**Purpose**: Deploys a Helm chart with specific values

**Critical fields**:
- `spec.chartRef.kind: OCIRepository` - References ocirepository.yaml
- `spec.chartRef.name` - MUST match OCIRepository metadata.name
- `spec.values` - Chart-specific configuration

**Example** (kubernetes/apps/kube-system/cilium/app/helmrelease.yaml:1):
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: cilium
spec:
  chartRef:
    kind: OCIRepository
    name: cilium
  interval: 1h
  values:
    ipam:
      mode: kubernetes
    k8sServiceHost: ${KUBERNETES_API_ADDR}
    k8sServicePort: 6443
```

### app/ocirepository.yaml (Chart Source)

**Purpose**: Tells Flux where to download the Helm chart

**Critical fields**:
- `spec.url` - OCI registry URL (e.g., `oci://ghcr.io/org/charts/name`)
- `spec.ref.tag` - Chart version (use semver)
- `metadata.name` - MUST match HelmRelease's `spec.chartRef.name`

**Example** (kubernetes/apps/kube-system/cilium/app/ocirepository.yaml:1):
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: cilium
spec:
  interval: 15m
  url: oci://ghcr.io/cilium/charts/cilium
  ref:
    tag: 1.18.3
```

### app/secret.sops.yaml (Encrypted Secrets)

**Purpose**: Store sensitive data encrypted with SOPS

**When to use**:
- API tokens (Cloudflare, GitHub)
- Database passwords
- TLS certificates (if not from cert-manager)

**How to create**:
```bash
# 1. Create unencrypted secret
cat > kubernetes/apps/{namespace}/{app}/app/secret.sops.yaml <<EOF
---
apiVersion: v1
kind: Secret
metadata:
  name: {secret-name}
stringData:
  token: "your-secret-here"
EOF

# 2. Encrypt with SOPS (run via task configure)
sops --encrypt --in-place kubernetes/apps/{namespace}/{app}/app/secret.sops.yaml

# 3. Add to kustomization.yaml resources
echo "  - ./secret.sops.yaml" >> kubernetes/apps/{namespace}/{app}/app/kustomization.yaml
```

**Example** (kubernetes/apps/network/cloudflare-dns/app/secret.sops.yaml:1):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-dns-secret
stringData:
  token: ENC[AES256_GCM,data:encrypted-value-here]
sops:
  age:
    - recipient: age1de4xdcq6h5yk4jjyyqe6qws344xsk055rdzvpr79mehvv7q7rdfqnyetjc
  encrypted_regex: ^(data|stringData)$
```

## Common Mistakes (and Fixes)

### Mistake 1: Wrong spec.path in ks.yaml
**Symptom**: Flux can't find resources, Kustomization stuck in "Not Ready"

**Fix**: Path MUST be `./kubernetes/apps/{namespace}/{app}/app`
```yaml
# ✗ Wrong
spec:
  path: ./kubernetes/apps/{namespace}/{app}

# ✓ Correct
spec:
  path: ./kubernetes/apps/{namespace}/{app}/app
```

### Mistake 2: Missing postBuild.substituteFrom
**Symptom**: `${SECRET_DOMAIN}` not replaced, literal string in resources

**Fix**: Always add to ks.yaml
```yaml
spec:
  postBuild:
    substituteFrom:
      - name: cluster-secrets
        kind: Secret
```

### Mistake 3: OCIRepository name mismatch
**Symptom**: HelmRelease fails with "chart not found"

**Fix**: Names MUST match exactly
```yaml
# ocirepository.yaml
metadata:
  name: my-app

# helmrelease.yaml
spec:
  chartRef:
    name: my-app  # Must match!
```

### Mistake 4: Forgot to add app to namespace kustomization
**Symptom**: App never deploys, no errors in Flux

**Fix**: Add to `kubernetes/apps/{namespace}/kustomization.yaml`
```yaml
resources:
  - ./namespace.yaml
  - ./my-app/ks.yaml  # Must list here!
```

### Mistake 5: Unencrypted secrets committed
**Symptom**: Secrets visible in Git history

**Fix**: ALWAYS run `task configure` before committing
- Encrypts all `*.sops.*` files
- Validates all manifests
- Checks for common mistakes

### Mistake 6: Missing SOPS component in namespace
**Symptom**: Encrypted secrets not decrypted, pods fail to start

**Fix**: Add to `kubernetes/apps/{namespace}/kustomization.yaml`
```yaml
components:
  - ../../components/sops  # Required for decryption
```

## Namespace Organization

Current namespaces and their purposes:

| Namespace | Purpose | Apps |
|-----------|---------|------|
| `cert-manager` | TLS certificate management | cert-manager |
| `default` | Example/sample apps | echo, echo-two |
| `flux-system` | GitOps operator (self-managing) | flux-operator, flux-instance |
| `kube-system` | Cluster infrastructure | cilium, coredns, metrics-server, reloader, spegel |
| `network` | Gateway & DNS services | cloudflare-dns, cloudflare-tunnel, envoy-gateway, k8s-gateway |

**When to create a new namespace**:
- Logical separation (e.g., `observability`, `storage`, `databases`)
- RBAC isolation required
- Resource quota enforcement needed

**How to create**:
```bash
# 1. Create directory
mkdir -p kubernetes/apps/{new-namespace}

# 2. Create namespace.yaml
cat > kubernetes/apps/{new-namespace}/namespace.yaml <<EOF
---
apiVersion: v1
kind: Namespace
metadata:
  name: {new-namespace}
  annotations:
    kustomize.toolkit.fluxcd.io/prune: disabled
EOF

# 3. Create kustomization.yaml
cat > kubernetes/apps/{new-namespace}/kustomization.yaml <<EOF
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
components:
  - ../../components/sops
resources:
  - ./namespace.yaml
EOF

# 4. Add to root flux kustomization
# (Flux will auto-discover via kubernetes/apps/ structure)
```

## Exposing Services via HTTPRoute

To make an app accessible via URL:

**Step 1**: Create HTTPRoute in `app/httproute.yaml`
```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: {app-name}
spec:
  hostnames: ["{{ .Release.Name }}.${SECRET_DOMAIN}"]
  parentRefs:
    - name: envoy-external          # or envoy-internal
      namespace: network
      sectionName: https
  rules:
    - backendRefs:
        - name: {service-name}
          port: 80
```

**Step 2**: Add to `app/kustomization.yaml`
```yaml
resources:
  - ./httproute.yaml
```

**Step 3**: Apply and verify
```bash
task configure
git add -A && git commit -m "feat: add httproute for {app}"
git push

# Verify DNS record created
kubectl get httproute -n {namespace}
```

**Access**:
- External: `https://{app-name}.${SECRET_DOMAIN}` (via Cloudflare tunnel)
- Internal: `https://{app-name}.internal.${SECRET_DOMAIN}` (via k8s-gateway DNS)

## Debugging Apps

### Check Flux reconciliation status
```bash
# All Kustomizations
flux get ks -A

# Specific app
flux get ks -n {namespace} {app-name}

# Force reconcile
flux reconcile ks -n {namespace} {app-name}
```

### Check HelmRelease status
```bash
# All HelmReleases
flux get hr -A

# Specific app
flux get hr -n {namespace} {app-name}

# Describe for errors
kubectl describe helmrelease -n {namespace} {app-name}
```

### Check if secret decryption works
```bash
# Verify SOPS component enabled
kubectl get kustomizations.kustomize.toolkit.fluxcd.io -n {namespace} -o yaml | grep sops

# Check secret exists
kubectl get secret -n {namespace} {secret-name}

# Verify decrypted values (won't show encrypted content)
kubectl get secret -n {namespace} {secret-name} -o jsonpath='{.data}'
```

### Common debug commands
```bash
# View all resources in app
kubectl get all -n {namespace} -l app.kubernetes.io/name={app-name}

# Pod logs
kubectl logs -n {namespace} -l app.kubernetes.io/name={app-name}

# Events
kubectl get events -n {namespace} --sort-by='.lastTimestamp'

# Gateway status
kubectl get gateway -n network

# HTTPRoute status
kubectl get httproute -A
```

## Key Insights

1. **3-file pattern is mandatory** - No variations, always ks.yaml + app/kustomization.yaml + resources
2. **Flux watches Git** - Changes in repository trigger reconciliation (every 1h or via webhook)
3. **SOPS encryption required** - Never commit unencrypted `*.sops.*` files
4. **Variable substitution is ordered** - Template → Flux → Helm (can't skip stages)
5. **Namespace kustomization is the parent** - Must list all apps via `./app-name/ks.yaml`
6. **postBuild required for variables** - Without it, `${SECRET_DOMAIN}` won't resolve
7. **task configure validates everything** - Run before every commit

## Quick Reference

| Command | Purpose |
|---------|---------|
| `task configure` | Validate + encrypt all manifests |
| `task reconcile` | Force Flux to sync from Git |
| `flux get ks -A` | Check all Kustomization statuses |
| `flux get hr -A` | Check all HelmRelease statuses |
| `kubectl get httproute -A` | Check all exposed services |
