# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the bootstrap phase of the Anton cluster.

## Project Overview

Bootstrap is the one-time initialization phase that creates a working Kubernetes cluster with Flux installed. After bootstrap completes, Flux takes over and continuously manages the cluster via GitOps.

**Key Concept**: Bootstrap deploys the minimum viable cluster (networking, DNS, cert-manager, Flux). Everything else is managed by Flux afterward.

## Bootstrap vs Flux (Simple Decision Rule)

Use this decision tree to determine where to put new services:

```
Does the service block cluster startup?
├─ YES → Bootstrap (helmfile.d/)
│   Examples:
│   • Cilium (CNI - pods can't start without networking)
│   • CoreDNS (DNS - services can't resolve)
│   • Cert-manager (TLS - many apps need certificates)
│   • Flux (meta-requirement - Flux must exist to manage itself)
│
└─ NO → Flux manages it (kubernetes/apps/)
    Examples:
    • Monitoring (observability is optional)
    • Gateways (traffic routing enhances working cluster)
    • User applications (not infrastructure)
    • Databases (apps depend on cluster, not vice versa)
```

**Critical rule**: If you can add it AFTER the cluster is running, it belongs in `kubernetes/apps/`, not bootstrap.

## The 5-Phase Execution Sequence

Bootstrap runs via `task bootstrap:apps` which executes `scripts/bootstrap-apps.sh` in 5 phases:

### Phase 1: Wait for Nodes
**What**: Wait until Talos nodes transition to Ready state
**Why**: Talos initializes networking before marking nodes Ready. Applying resources too early fails.

```bash
# Waits for nodes with Ready=False
wait_for_nodes()
```

### Phase 2: Apply Namespaces
**What**: Create namespaces from `kubernetes/apps/*/` directory structure
**Why**: HelmReleases will fail if target namespace doesn't exist. Must create before Phase 5.

```bash
# Creates: flux-system, kube-system, cert-manager, network, default
apply_namespaces()
```

### Phase 3: Apply SOPS Secrets
**What**: Install SOPS decryption keys and GitHub deploy key
**Why**: Flux needs these to decrypt secrets and pull from Git. Must install before Flux starts.

**Files applied to flux-system namespace**:
- `bootstrap/github-deploy-key.sops.yaml` - SSH key for private repos
- `bootstrap/sops-age.sops.yaml` - Age encryption key
- `kubernetes/components/sops/cluster-secrets.sops.yaml` - Cluster variables

```bash
apply_sops_secrets()
```

### Phase 4: Apply CRDs
**What**: Extract and install Custom Resource Definitions
**Why**: Helm charts reference CRD fields immediately. Installing CRDs first prevents failures.

**CRDs extracted from**:
- `external-dns` charts (DNSEndpoint CRD)
- `envoy-gateway` charts (Gateway API CRDs)
- `kube-prometheus-stack` charts (Monitoring CRDs)

```bash
# Uses helmfile template to extract only CRDs
apply_crds()
```

### Phase 5: Sync Helm Releases
**What**: Deploy 6 bootstrap applications in dependency order
**Why**: Each app depends on the previous one being healthy. Strict sequencing prevents cascading failures.

**Dependency chain** (from bootstrap/helmfile.d/01-apps.yaml:1):
```
cilium (CNI)
  ↓ needs cilium
coredns (DNS)
  ↓ needs coredns
spegel (image cache)
  ↓ needs spegel
cert-manager (TLS)
  ↓ needs cert-manager
flux-operator (Flux CRDs)
  ↓ needs flux-operator
flux-instance (GitOps engine)
```

```bash
# Helmfile respects "needs:" declarations
sync_helm_releases()
```

**Why this specific order matters**:
1. Cilium first - Pods can't communicate without CNI
2. CoreDNS second - Services can't resolve DNS without it
3. Spegel third - Image caching speeds up subsequent deployments (optional but helpful)
4. Cert-manager fourth - Flux webhook needs TLS certificates
5. Flux-operator fifth - Installs Flux CRDs
6. Flux-instance last - Starts watching Git repository

## When Flux Takes Over (The Handoff)

Bootstrap deploys `flux-instance` HelmRelease which reads `kubernetes/flux/cluster/ks.yaml`. This Kustomization tells Flux to watch `kubernetes/apps/` for all future changes.

**Handoff timeline**:
```
task bootstrap:apps completes
    ↓
flux-instance HelmRelease deployed
    ↓
Flux reads GitRepository config
    ↓
GitRepository points to: github.com/wcygan/anton.git branch main
    ↓
Flux applies: kubernetes/flux/cluster/ks.yaml
    ↓
Flux watches: kubernetes/apps/ (all namespaces)
    ↓
Flux manages everything from now on (every 1h or via webhook)
```

**Key insight**: Apps deployed during bootstrap (cilium, coredns, cert-manager) have HelmRelease definitions in BOTH places:
- Bootstrap: `bootstrap/helmfile.d/01-apps.yaml` (initial deployment)
- Flux: `kubernetes/apps/{namespace}/{app}/app/helmrelease.yaml` (ongoing management)

These definitions use the SAME values (via template bridge), ensuring consistency.

## Single Source of Truth (Template Bridge)

Bootstrap reads values FROM the same HelmRelease files that Flux uses. This prevents version drift.

**How it works** (bootstrap/helmfile.d/templates/values.yaml.gotmpl:1):
```go-template
{{ (fromYaml (readFile (printf "../../../kubernetes/apps/%s/%s/app/helmrelease.yaml"
  .Release.Namespace .Release.Name))).spec.values | toYaml }}
```

**Translation**: Bootstrap's helmfile reads `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml` for Cilium values, NOT separate config.

**Why this matters**:
- Change `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml` → Both bootstrap AND Flux use new values
- No version mismatch between initial bootstrap and Flux reconciliation
- Single file to edit when updating app configuration

## Bootstrap File Structure

```
bootstrap/
├── helmfile.d/
│   ├── 00-crds.yaml           # CRD extraction only (3 charts)
│   ├── 01-apps.yaml           # 6 bootstrap releases with dependencies
│   └── templates/
│       └── values.yaml.gotmpl # Reads from kubernetes/apps/ HelmReleases
├── github-deploy-key.sops.yaml    # SSH key for Git (encrypted)
├── sops-age.sops.yaml              # SOPS decryption key (encrypted)
└── (other generated files from task configure)
```

### 00-crds.yaml (CRD Extraction)

**Purpose**: Pre-install CRDs before their corresponding Helm releases

**Why separate file**: Helm charts install CRDs on first release, but other charts might need those CRDs immediately. Installing CRDs first avoids race conditions.

**How it works**:
```yaml
releases:
  - name: external-dns-crds
    chart: bitnami/external-dns
    installed: false  # Don't install the full release
    hooks:
      - events: ["presync"]
        command: "helm"
        args:
          - "template"
          - "--include-crds"  # Extract only CRDs
          - "{{`{{.Release.Name}}`}}"
          - "{{`{{.Release.Chart}}`}}"
          - "|"
          - "kubectl"
          - "apply"
          - "--server-side"
          - "-f"
          - "-"
```

**Charts processed**:
1. `external-dns` - DNSEndpoint CRD (used by cloudflare-dns)
2. `envoy-gateway` - Gateway API CRDs (used by envoy-gateway)
3. `kube-prometheus-stack` - Monitoring CRDs (ServiceMonitor, PodMonitor, etc.)

### 01-apps.yaml (Bootstrap Releases)

**Purpose**: Deploy 6 core applications in strict dependency order

**Structure** (bootstrap/helmfile.d/01-apps.yaml:1):
```yaml
releases:
  - name: cilium
    namespace: kube-system
    chart: cilium/cilium
    version: 1.18.3
    # No needs: (first in chain)

  - name: coredns
    namespace: kube-system
    chart: coredns/coredns
    version: 1.45.0
    needs: [kube-system/cilium]  # Wait for Cilium

  - name: spegel
    namespace: kube-system
    chart: spegel/spegel
    version: 0.4.0
    needs: [kube-system/coredns]  # Wait for CoreDNS

  - name: cert-manager
    namespace: cert-manager
    chart: jetstack/cert-manager
    version: v1.19.1
    needs: [kube-system/spegel]

  - name: flux-operator
    namespace: flux-system
    chart: oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator
    version: 0.32.0
    needs: [cert-manager/cert-manager]

  - name: flux-instance
    namespace: flux-system
    chart: oci://ghcr.io/controlplaneio-fluxcd/charts/flux-instance
    version: 0.32.0
    needs: [flux-system/flux-operator]  # Last in chain
```

**Critical**: `needs:` declarations enforce ordering. Helmfile won't deploy an app until its dependencies are healthy.

## What Breaks If Order Changes

| If You Change | What Breaks | Why |
|---------------|-------------|-----|
| **CRDs after releases** | Helm chart fails to install | Charts reference CRD fields (e.g., `DNSEndpoint`) immediately |
| **Secrets after CRDs** | Flux can't decrypt | Flux needs `sops-age` Secret to read encrypted files |
| **Apps without namespaces** | kubectl apply fails | Target namespace doesn't exist; Kubernetes rejects resources |
| **Bootstrap before nodes ready** | Pod networking broken | Talos hasn't initialized network interfaces yet |
| **Flux before cert-manager** | flux-operator crashes | Webhook needs TLS certificate that doesn't exist |
| **Change coredns before cilium** | DNS resolution fails | CoreDNS pods can't get IPs without CNI |

**Key insight**: The dependency chain isn't arbitrary. Each app truly depends on the previous one's functionality.

## Variable Flow from cluster.yaml

Bootstrap uses variables from `cluster.yaml` that flow through template rendering:

**In cluster.yaml**:
```yaml
cluster_api_addr: "192.168.1.101"
cluster_dns_gateway_addr: "192.168.1.102"
cloudflare_domain: "example.com"
cloudflare_token: "..."
```

**Flow**:
```
cluster.yaml
    ↓
task configure (Jinja2 templating)
    ↓
kubernetes/apps/*/*/app/helmrelease.yaml (filled with values)
    ↓
bootstrap/helmfile.d/templates/values.yaml.gotmpl (reads them)
    ↓
helmfile sync (deploys with those values)
```

**Example**: Cilium needs `${KUBERNETES_API_ADDR}` from `cluster.yaml`:
1. `cluster.yaml` has `cluster_api_addr: "192.168.1.101"`
2. Template renders `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml` with `${KUBERNETES_API_ADDR}`
3. Bootstrap helmfile reads this HelmRelease
4. Flux postBuild substitution replaces `${KUBERNETES_API_ADDR}` → `192.168.1.101`

## Common Bootstrap Scenarios

### Scenario 1: Adding a new bootstrap app

**When**: New infrastructure component that blocks cluster startup

**Steps**:
```bash
# 1. Add HelmRelease to kubernetes/apps/ (Flux will manage it later)
mkdir -p kubernetes/apps/{namespace}/{app}/app
# ... create ks.yaml, helmrelease.yaml, ocirepository.yaml

# 2. Add to bootstrap/helmfile.d/01-apps.yaml
# Insert in dependency chain with "needs:" declaration

# 3. Test rendering
task configure

# 4. Bootstrap will use values from kubernetes/apps/ HelmRelease
```

### Scenario 2: Updating bootstrap app version

**Steps**:
```bash
# 1. Edit kubernetes/apps/{namespace}/{app}/app/helmrelease.yaml
# Change chart version or values

# 2. Re-render
task configure

# 3. Bootstrap will use new values automatically
# (values.yaml.gotmpl reads from this file)
```

### Scenario 3: Debugging bootstrap failure

**Phase-specific checks**:
```bash
# Phase 1 (nodes)
kubectl get nodes

# Phase 2 (namespaces)
kubectl get namespaces

# Phase 3 (secrets)
kubectl get secrets -n flux-system

# Phase 4 (CRDs)
kubectl get crds | grep -E "(gateway|dnsendpoint|servicemonitor)"

# Phase 5 (releases)
helmfile -f bootstrap/helmfile.d/01-apps.yaml status
kubectl get pods -n kube-system
kubectl get pods -n flux-system
```

### Scenario 4: Re-running bootstrap (idempotent)

Bootstrap is safe to re-run:
```bash
task bootstrap:apps
```

**Why it's safe**:
- Phase 2 skips existing namespaces
- Phase 3 overwrites secrets (same content)
- Phase 4 applies CRDs server-side (idempotent)
- Phase 5 uses helmfile sync (upgrades if changed, skips if unchanged)

## Key Insights

1. **Bootstrap is one-time** - After Flux takes over, you never re-bootstrap (except cluster rebuild)
2. **Dependency chain is strict** - Can't change order without breaking cluster
3. **Single source of truth** - HelmRelease files in kubernetes/apps/ used by BOTH bootstrap and Flux
4. **Phase order matters** - Each phase depends on previous completing successfully
5. **Idempotent design** - Safe to re-run bootstrap without breaking existing cluster
6. **Handoff is automatic** - flux-instance deployment triggers GitOps management
7. **CRDs must install first** - Prevents race conditions with charts that use CRDs

## Quick Reference

| Command | Purpose |
|---------|---------|
| `task bootstrap:apps` | Run all 5 bootstrap phases |
| `helmfile -f bootstrap/helmfile.d/01-apps.yaml status` | Check bootstrap release status |
| `flux check` | Verify Flux is running after bootstrap |
| `kubectl get pods -n flux-system` | Check Flux pods |
| `flux get sources git -A` | Verify GitRepository connection |
| `flux reconcile ks flux-cluster` | Force Flux to sync after bootstrap |

## When to Modify Bootstrap

**DO modify when**:
- Adding infrastructure that blocks cluster startup
- Updating versions of bootstrap apps
- Changing bootstrap dependency order (carefully!)

**DON'T modify when**:
- Adding user applications (use kubernetes/apps/)
- Adding optional services (use kubernetes/apps/)
- Testing new features (prototype in kubernetes/apps/ first)
