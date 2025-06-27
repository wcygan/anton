# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository. It automatically loads into conversations to provide
project-specific context and instructions.

## CRITICAL: Golden Rules for Safe Operations

**MANDATORY**: Before making ANY changes to the cluster, consult the golden rules at `/docs/golden-rules/`. These rules prevent catastrophic failures and are based on real incidents that caused cluster outages.

Key documents:
- **[Kubernetes Operations](./docs/golden-rules/kubernetes-operations.md)** - NEVER delete Flux kustomizations without analysis
- **[GitOps Practices](./docs/golden-rules/gitops-practices.md)** - All changes MUST go through Git
- **[Storage Operations](./docs/golden-rules/storage-operations.md)** - Storage resources need special handling
- **[Secret Management](./docs/golden-rules/secret-management.md)** - Never commit unencrypted secrets

The #1 rule: **Think before you delete. Suspend, don't delete.**

## MCP Server Usage for Informed Decision Making

**CRITICAL**: When working with this Kubernetes homelab, leverage MCP servers for accurate, documentation-based decisions:

### Context7 MCP Server

Use the Context7 MCP server to access official documentation for any technology used in this project:

1. **Resolve Library IDs First**: 
   ```
   /mcp context7:resolve-library-id <library-name>
   ```
   Example: For Rook documentation, use `rook` to get `/rook/rook`

2. **Fetch Documentation**: 
   ```
   /mcp context7:get-library-docs <library-id> [topic] [tokens]
   ```
   Example: `/mcp context7:get-library-docs /kubernetes/website "persistent volumes" 5000`

**Common Libraries for this Homelab**:
- `/kubernetes/website` - Kubernetes core concepts and resources
- `/rook/rook` - Rook Ceph storage orchestration
- `/fluxcd/flux2` - Flux GitOps toolkit
- `/cilium/cilium` - Cilium CNI and networking
- `/prometheus-operator/prometheus-operator` - Monitoring stack

### Sequential Thinking MCP Server

Use the Sequential Thinking server for complex problem-solving and decision-making:

```
/mcp sequential-thinking:sequential_thinking <prompt>
```

**Use Cases**:
- Analyzing upgrade paths and breaking changes
- Debugging complex multi-component issues
- Planning architectural changes
- Evaluating security implications

### Decision-Making Process

When making technical decisions or troubleshooting:

1. **Gather Facts**: Use Context7 to fetch relevant official documentation
2. **Check History**: Review milestones for similar deployments and past lessons
3. **Analyze**: Use Sequential Thinking for complex reasoning about the facts
4. **Verify**: Cross-reference with existing cluster configuration via Kubernetes MCP
5. **Implement**: Make changes based on documented best practices and proven patterns

**Example Workflow**:
```bash
# 1. Research storage options
/mcp context7:get-library-docs /rook/rook "ceph cluster configuration" 5000

# 2. Check project history for similar implementations
grep -l "storage" docs/milestones/*.md | xargs head -50

# 3. Analyze implications
/mcp sequential-thinking:sequential_thinking "Given a 3-node cluster with 2 NVMe drives per node, analyze the optimal Ceph replication strategy considering performance, resilience, and capacity"

# 4. Verify current state
/mcp kubernetes:kubectl_get "cephcluster" "storage" "storage"

# 5. Implement based on findings and past successes
```

This approach ensures all decisions are grounded in official documentation and well-reasoned analysis, not guesswork or outdated information.

## Repository Overview

This is "Anton" - a production-grade Kubernetes homelab running on 3 MS-01 mini
PCs using Talos Linux and Flux GitOps. The cluster implements patterns for
automated deployment, monitoring, and security.

## Project History & Milestones

### Understanding Past Deployments

Before implementing new features or troubleshooting issues, check the milestone documentation for relevant historical context:

**Location**: `docs/milestones/`
**Format**: `YYYY-MM-DD-milestone-name.md`

### When to Reference Milestones

**ALWAYS** check milestones when:
- Deploying similar technology (e.g., check Loki milestone before deploying other logging tools)
- Troubleshooting persistent issues (past challenges often resurface)
- Planning major changes (learn from previous migrations)
- Onboarding to understand cluster evolution

### Quick Milestone Search

```bash
# Find all storage-related milestones
ls docs/milestones/*storage*.md

# Search for specific technology deployments
grep -l "Loki" docs/milestones/*.md

# Find milestones with specific challenges
grep -l "Challenges" docs/milestones/*.md | xargs grep -A5 "Challenges"
```

### Learning from Past Deployments

Each milestone contains:
- **Implementation Details**: Exact configurations that worked
- **Challenges & Resolutions**: Problems encountered and how they were solved
- **Lessons Learned**: Key takeaways to apply to future work
- **Validation Methods**: How success was measured

**Example Usage**:
Before deploying a new monitoring tool, check:
1. `docs/milestones/2025-06-10-loki-deployment.md` - Logging implementation patterns
2. Look for "Challenges" section - Common Helm chart issues and fixes
3. Review "Configuration Changes" - Proven configuration patterns

## Quick Reference

### Essential Commands
- **Check History**: Review `docs/milestones/` for past deployment patterns and lessons learned
- **Initial Setup**: `task init` → `task configure` → `task bootstrap:talos` →
  `task bootstrap:apps`
- **Deploy App**: Add to `kubernetes/apps/{namespace}/` → `task reconcile`
- **Debug Issues**: `flux get hr -A` →
  `kubectl describe hr {name} -n {namespace}`
- **Upgrade Cluster**: `task talos:upgrade-node IP={ip}` →
  `task talos:upgrade-k8s`
- **Monitor Health**: 
  - Interactive: `./scripts/k8s-health-check.ts --verbose`
  - Automated/CI: `./scripts/k8s-health-check.ts --json`
  - Full suite: `deno task test:all:json`

### Build & Test Commands
- **Validate Changes**: `deno task validate` (parallel execution, 5x faster)
- **Check Flux Config**: `./scripts/check-flux-config.ts`
- **Run Tests**: `deno task test:all`
- **Force Reconciliation**: `task reconcile`

## Core Architecture

### Infrastructure Stack

- **OS**: Talos Linux (immutable, API-driven)
- **GitOps**: Flux v2.5.1 with hierarchical Kustomizations
- **CNI**: Cilium in kube-proxy replacement mode
- **Ingress**: Dual NGINX controllers (internal/external)
- **External Access**: Cloudflare tunnel via cloudflared
- **Storage**: Local Path Provisioner
- **Secrets**: 1Password + External Secrets Operator (preferred)

### GitOps Structure

- Two root Kustomizations: `cluster-meta` (repos) → `cluster-apps`
  (applications)
- Apps organized by namespace: `kubernetes/apps/{namespace}/{app-name}/`
- Each app has: `ks.yaml` (Kustomization) + `app/` directory
- HelmReleases use OCIRepository sources from `kubernetes/flux/meta/repos/`

## Common Development Commands

### Initial Cluster Setup (One-Time)

```bash
# Generate config from templates
task init

# Configure cluster (generates Talos/k8s configs)
task configure

# Bootstrap Talos
task bootstrap:talos

# Bootstrap apps (Cilium, Flux, core services)
task bootstrap:apps
```

### Talos Management

```bash
# Apply config to node
task talos:apply-node IP=192.168.1.98 MODE=auto

# Upgrade Talos on node
task talos:upgrade-node IP=192.168.1.98

# Upgrade Kubernetes
task talos:upgrade-k8s

# Reset cluster (destructive!)
task talos:reset
```

## Adding New Applications

### Pre-Deployment Verification

1. **Verify Helm chart exists and version is available**:
   ```bash
   helm search repo <repo>/<chart> --versions
   ```

2. **Check current Flux schema** (no `retryInterval` in v2):
   ```bash
   flux install --export | grep -A20 HelmRelease
   ```

3. **Validate dependencies exist**:
   ```bash
   flux get kustomization -A | grep <dependency-name>
   ```

### App Deployment Steps

1. Create namespace directory: `kubernetes/apps/{namespace}/`
2. Create app structure:
   ```
   {namespace}/
   ├── {app-name}/
   │   ├── ks.yaml          # Flux Kustomization
   │   └── app/
   │       ├── kustomization.yaml  # MUST specify namespace!
   │       └── helmrelease.yaml (or other resources)
   ```

3. Standard Kustomization pattern (`ks.yaml`):
   ```yaml
   apiVersion: kustomize.toolkit.fluxcd.io/v1
   kind: Kustomization
   metadata:
     name: &app { app-name }
     namespace: flux-system
   spec:
     targetNamespace: { namespace }
     commonMetadata:
       labels:
         app.kubernetes.io/name: *app
     interval: 1h
     # NO retryInterval field in Flux v2!
     timeout: 10m
     prune: true
     wait: true
     path: ./kubernetes/apps/{namespace}/{app-name}/app
     sourceRef:
       kind: GitRepository
       name: flux-system
       namespace: flux-system
     dependsOn: # Use actual namespace, not flux-system
       - name: <dependency-kustomization-name>
         namespace: <dependency-actual-namespace>
   ```

4. For HelmReleases, reference HelmRepository from
   `kubernetes/flux/meta/repos/`:
   - Add new repos to `kubernetes/flux/meta/repos/` if needed
   - Update `kubernetes/flux/meta/repos/kustomization.yaml` to include new repo
     file

## Key Patterns & Conventions

### Flux Intervals

- Critical infrastructure: `5m`
- Core services: `15m`
- Standard applications: `30m` to `1h`

### Resource Management

- Always specify resource requests/limits in HelmReleases
- Use finite retries (e.g., `retries: 3`) not infinite (`retries: -1`)
- Add health checks for critical services
- Include `wait: true` for dependencies

### Networking

- Internal services: use `internal` ingress class
- External services: use `external` ingress class + external-dns annotation
  (only used when EXPLICITLY STATED; default to `internal`)
- Split DNS via k8s-gateway for internal resolution

## Secrets Management

### Recommended Approach: 1Password + External Secrets Operator

For all new applications, use 1Password with External Secrets Operator:

1. Store secrets in 1Password vault
2. Create `OnePasswordItem` CR to sync secrets:
   ```yaml
   apiVersion: onepassword.com/v1
   kind: OnePasswordItem
   metadata:
     name: app-credentials
     namespace: app-namespace
   spec:
     itemPath: "vaults/Homelab/items/app-name"
   ```
3. Reference the synced Kubernetes Secret in your app

#### External Secrets v0.17.0+ Breaking Change

**IMPORTANT**: External Secrets Operator v0.17.0 removed support for `v1beta1` API.
- **Always use** `apiVersion: external-secrets.io/v1` (not v1beta1)
- **Applies to**: SecretStore, ClusterSecretStore, ExternalSecret, ClusterExternalSecret
- **Current version**: v0.17.0 (check with `kubectl get deployment -n external-secrets external-secrets -o jsonpath='{.spec.template.spec.containers[0].image}'`)

#### 1Password Integration

For 1Password secrets, use `ExternalSecret` resources with explicit field mapping:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword-connect
    kind: ClusterSecretStore
  target:
    name: app-secrets
    creationPolicy: Owner
  data:
    # Map each field individually - field names must match exactly
    - secretKey: database-url      # Key in K8s secret
      remoteRef:
        key: app-config           # Item name in 1Password
        property: database_url    # Field name in 1Password (case-sensitive!)
    - secretKey: api-key
      remoteRef:
        key: app-config
        property: api_key
```

**Important Notes:**
- **Do NOT use** `OnePasswordItem` CRD unless you have 1Password Operator installed
- **Field names are case-sensitive** - must match exactly as defined in 1Password
- **Use setup script** for deployment: `./scripts/setup-1password-connect.ts`
- **Cannot store credentials in Git** - use manual deployment for Connect server

Example ClusterSecretStore for 1Password:
```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-connect
spec:
  provider:
    onepassword:
      connectHost: http://onepassword-connect.external-secrets.svc.cluster.local:8080
      vaults:
        anton: 1  # Use your vault name
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            namespace: external-secrets
            key: token
```

### Legacy: SOPS (Deprecated)

SOPS encryption is only for existing/legacy secrets:

- Files matching `*.sops.yaml` are auto-encrypted
- Uses `age.key` in repo root
- **Do not use for new applications**

## Monitoring & Debugging

### MCP Server for Kubernetes Introspection

**IMPORTANT**: This project has the MCP (Model Context Protocol) Server for Kubernetes configured. When performing Kubernetes introspection, debugging, or monitoring tasks, use the MCP server via `/mcp` command instead of manually running kubectl commands and pasting outputs.

The MCP server provides direct access to:
- **Resource inspection**: `kubectl_get`, `kubectl_describe`, `kubectl_list`
- **Debugging**: `kubectl_logs`, `kubectl_rollout`, status checks
- **Monitoring**: Real-time resource status, events, and metrics
- **Management**: Scaling, patching, port-forwarding

To use: Type `/mcp` in Claude Code to access Kubernetes tools directly.

For detailed usage, see: [MCP Kubernetes Usage Guide](docs/mcp/kubernetes-usage.md)

### Dashboard Organization & Management

**IMPORTANT**: Follow these principles for Grafana dashboard management:

#### Centralization Preferences
- **Consolidate, don't proliferate**: Enhance existing dashboards instead of creating new versions
- **Single source of truth**: One dashboard per functional area (e.g., one Flux dashboard, one cluster overview)
- **Avoid duplicates**: Remove "-optimized", "-v2", or similar versioned dashboard variants

#### Dashboard Structure
- **Location**: All custom dashboards in `/kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/`
- **Avoid scatter**: Don't create separate `/grafana-dashboards/` directories unless absolutely necessary
- **Consistent naming**: Use descriptive, non-versioned names (e.g., `flux-cluster.json`, not `flux-cluster-v2.json`)

#### Enhancement Strategy
- **Update in place**: Add recording rules and performance optimizations to existing dashboards
- **Modular sections**: Use dashboard rows to organize related metrics (e.g., "Performance", "Errors", "Storage")
- **Recording rules**: Leverage pre-computed metrics for faster loading
- **Progressive enhancement**: Improve existing dashboards incrementally

#### Example Structure
```
kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/
├── flux-cluster.json              # Combined Flux GitOps + performance
├── homelab-cluster-overview.json  # Main cluster health dashboard
├── ceph-cluster.json              # Storage monitoring
├── loki-dashboard.json            # Centralized logging
└── grafana-performance.json       # Grafana self-monitoring
```

#### Anti-Patterns to Avoid
- ❌ Creating multiple versions: `dashboard.json`, `dashboard-optimized.json`, `dashboard-v2.json`
- ❌ Separate directories for similar functionality: `/grafana-dashboards/optimized/`
- ❌ Version suffixes in titles: "Dashboard (Optimized)", "Dashboard V2"
- ❌ Duplicate panels across multiple dashboards

### Talos Linux Troubleshooting

For detailed Talos-specific troubleshooting including node reboots, kubeconfig issues, and storage verification, see:
- **[Talos Troubleshooting Guide](docs/talos-linux/troubleshooting.md)** - Common issues and resolution steps

### Monitoring Tools

All scripts use Deno and require `--allow-all`. Each monitoring script supports
both human-readable and JSON output formats:

- **k8s-health-check.ts**: Comprehensive cluster health monitoring
  - Human-readable: `deno task health:monitor` or `./scripts/k8s-health-check.ts`
  - JSON output: `deno task health:monitor:json` or add `--json` flag
- **flux-deployment-check.ts**: GitOps deployment verification with `--watch`
  for real-time
- **flux-monitor.ts**: Real-time Flux resource monitoring
- **check-flux-config.ts**: Configuration best practices analyzer
  - Human-readable: `deno task check-flux-config`
  - JSON output: `deno task check-flux-config:json` or add `--json` flag
- **cluster-health-monitor.ts**: Cluster-wide health monitoring
  - Human-readable: `deno task health:monitor`
  - JSON output: `deno task health:monitor:json` (incompatible with `--watch`)
- **network-monitor.ts**: Network and ingress health monitoring
  - Human-readable: `deno task network:check`
  - JSON output: `deno task network:check:json`
- **storage-health-check.ts**: PVC usage and storage health
  - Human-readable: `deno task storage:check`
  - JSON output: `deno task storage:check:json`
- **test-all.ts**: Unified test suite for all monitoring scripts
  - Human-readable: `deno task test:all`
  - JSON output: `deno task test:all:json`
- **validate-manifests.ts**: Pre-commit manifest validation with parallel execution
  - Run via: `deno task validate` or `./scripts/validate-manifests.ts`
  - 5-6x faster than shell version through parallelism

### JSON Output Standards

All monitoring scripts that support JSON output follow a standardized schema:

```typescript
interface MonitoringResult {
  status: "healthy" | "warning" | "critical" | "error";
  timestamp: string;
  summary: {
    total: number;
    healthy: number;
    warnings: number;
    critical: number;
  };
  details: any; // Script-specific data
  issues: string[]; // Array of human-readable issues
}
```

Exit codes are standardized across all scripts:
- `0`: All checks passed (healthy)
- `1`: Warnings detected (degraded but functional)
- `2`: Critical issues detected (requires immediate attention)
- `3`: Execution error (script/connectivity failure)

### CI/CD Integration with JSON

For automated pipelines and monitoring integration:

```bash
# Run all tests with JSON output for parsing
deno task test:all:json > test-results.json

# Check specific component and parse results
./scripts/network-monitor.ts --json | jq '.status'

# Get only critical issues
./scripts/k8s-health-check.ts --json | jq '.issues[]'

# Check exit code for CI/CD decisions
./scripts/storage-health-check.ts --json
if [ $? -eq 2 ]; then
  echo "Critical storage issues detected!"
fi
```

### Common Debugging Commands

**PREFERRED**: Use `/mcp` command in Claude Code for direct Kubernetes access instead of running these commands manually.

```bash
# Check Flux status
flux check
flux get all -A
flux get sources git -A

# Force reconciliation
task reconcile

# Check events and logs
kubectl -n flux-system get events --sort-by='.lastTimestamp'
kubectl -n {namespace} logs {pod-name} -f
kubectl -n {namespace} describe {kind} {name}
```

### Debugging Patterns

- Always check Flux dependencies first: `kubectl get kustomization -A`
- For app issues, trace: Kustomization → HelmRelease → Pods
- Check git sync: `flux get sources git -A`
- **Force resource recreation when cached**:
  ```bash
  kubectl delete helmchart -n flux-system <namespace>-<name>
  flux reconcile hr <name> -n <namespace> --with-source
  ```
- **Check correct dependency naming**:
  ```bash
  flux get kustomization -A | grep <pattern>
  # Dependencies use: name: <kustomization-name>, namespace: <actual-namespace>
  ```

## CI/CD Integration

- GitHub webhook configured for push-based reconciliation
- Renovate for automated dependency updates
- Pre-commit validation via `deno task validate`

## Common Operations

### Rolling Cluster Upgrades

1. Always upgrade Talos first: `task talos:upgrade-node IP=192.168.1.98`
2. Wait for node Ready before proceeding to next
3. Then upgrade Kubernetes: `task talos:upgrade-k8s`
4. Monitor with: `./scripts/cluster-health-monitor.ts`

### Emergency Recovery

- If Flux stuck: `flux suspend/resume kustomization <name> -n flux-system`
- If node NotReady: Check `talosctl -n <IP> dmesg` for boot issues
- If PVC unbound: Verify `local-path-provisioner` in storage namespace

## Anton Cluster Specifics

### Hardware Details

- Nodes: k8s-1 (192.168.1.98), k8s-2 (.99), k8s-3 (.100)
- All nodes are control-plane (no dedicated workers)
- Storage: 
  - **Primary**: Rook-Ceph distributed storage (default)
    - 6x 1TB NVMe drives (2 per node)
    - Storage class: `ceph-block` (default)
    - 3-way replication across hosts
  - **Legacy**: Local-path provisioner (for migration period)

### Namespace Organization

- `external-secrets`: All secret management (1Password, ESO)
- `network`: All ingress/DNS (internal/external nginx, cloudflared)
- `monitoring`: Prometheus stack, Grafana
- `storage`: Rook-Ceph operator, cluster, and toolbox
- `kubeai`: AI model serving infrastructure

## Development Workflow Integration

### Before Committing

1. Validate manifests: `deno task validate` (uses parallel execution)
2. Check Flux config: `./scripts/check-flux-config.ts`
3. For secrets: Use 1Password OnePasswordItem CRs

### After Changes

1. Force reconciliation: `task reconcile`
2. Monitor deployment: `./scripts/flux-monitor.ts`

### Common Pitfalls

- Missing `namespace: flux-system` in sourceRef → "GitRepository not found"
- Infinite retries in HelmRelease → Resource exhaustion
- Missing resource constraints → Pod scheduling issues
- Wrong ingress class → Service unreachable
- **Invalid `retryInterval` field** → Schema validation errors (removed in Flux
  v2)
- **Wrong dependency namespace** → Use actual namespace, not flux-system
- **Git commits required** → Flux only deploys committed changes
- **Chart version mismatch** → Always verify with `helm search repo`
- **Missing namespace in kustomization.yaml** → Resources created in wrong namespace
- **Ceph monitoring disabled** → Set `rulesNamespaceOverride: monitoring` when enabling Prometheus rules

## Rook-Ceph Storage Configuration

### Architecture Overview

- **Operator**: Manages Ceph lifecycle in `storage` namespace
- **Cluster**: Named "storage" to avoid clusterID mismatches
- **Block Storage**: Default via `ceph-block` storage class
- **Dashboard**: Accessible via Tailscale at `ceph-dashboard`
- **Monitoring**: Prometheus rules in `monitoring` namespace

### Critical Configuration

```yaml
# HelmRelease values for rook-ceph-cluster
monitoring:
  enabled: true
  createPrometheusRules: true
  rulesNamespaceOverride: monitoring  # Co-locate with other rules
cephClusterSpec:
  external:
    enable: false  # Required field for template validation
  clusterName: storage  # Must match for CSI provisioning
```

### Common Ceph Operations

```bash
# Check cluster health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Monitor OSD status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd status

# View storage usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df
```

### Ceph Operations TLDR

- **Daily Health Check**: `./scripts/storage-health-check.ts --detailed` or see `docs/ceph/operations/daily-health-check.md`
- **OSD Replacement**: Mark out → Wait rebalance → Remove → Replace disk → Auto-provision (see `docs/ceph/operations/osd-replacement.md`)
- **Troubleshooting**: Check `ceph health detail` → Review logs → Follow `docs/ceph/operations/troubleshooting.md`
- **Capacity**: Monitor at 50% (plan), 70% (order), 80% (expand) - currently using 116Gi of 2TB usable
- **Backups**: Volsync configured for automated backups - see `docs/ceph/operations/backup-restore.md`

## Configuration Analysis & Version Management

### AI Agent Guidelines for Chart Updates

When analyzing Kubernetes configurations and comparing against latest versions:

#### Guiding Principles

- **Declarative First**: All changes must be made via Git repository
  modifications, not direct kubectl/helm commands
- **Version Pinning**: Charts and images are intentionally pinned for
  predictable deployments
- **Impact Analysis**: Don't just update versions - analyze breaking changes,
  value schema changes, and compatibility
- **Follow Patterns**: Maintain consistency with existing repository structure
  and conventions
- **Safety First**: Distinguish between patch/minor/major upgrades with
  appropriate warnings

#### Analysis Workflow

**Phase 1: Discovery**

1. Locate HelmRelease at
   `kubernetes/apps/<namespace>/<app>/app/helmrelease.yaml`
2. Extract: chart name, pinned version, sourceRef, custom values
3. Find source repository in `kubernetes/flux/meta/repos/`

**Phase 2: Comparison**

1. Determine latest stable versions (patch/minor/major)
2. Compare values.yaml between current and target versions
3. Identify deprecated/changed configuration keys
4. Check custom values compatibility with new schema
5. Review official changelogs for breaking changes

**Phase 3: Remediation**

1. Provide specific version upgrade recommendation
2. Explain impact level (patch/minor/major)
3. Supply exact YAML diffs for HelmRelease updates
4. Include any required values migration
5. Note container image updates if applicable

This structured approach ensures safe, informed upgrades that align with GitOps
principles.

## Advanced Troubleshooting & Debugging

### Systematic Troubleshooting Methodology

When Flux deployments fail, follow this top-down investigation approach starting
with high-level abstractions and drilling down only when necessary.

#### Step 1: Initial Triage - The Big Picture

**Always start here** to get system-wide health status:

```bash
# Critical first command - shows health of all Flux resources
flux get all -A

# Identify failing resources with Ready: False status
# Note the KIND, NAME, and NAMESPACE of any failures
```

#### Step 2: Isolate the Failure

Once you've identified a failing resource, investigate specifically:

```bash
# Most valuable debugging command - shows Conditions and Events
flux describe helmrelease <name> -n <namespace>
flux describe kustomization <name> -n flux-system

# Check responsible controller logs
kubectl logs -n flux-system deployment/helm-controller -f      # HelmRelease issues
kubectl logs -n flux-system deployment/kustomize-controller -f # Kustomization issues
kubectl logs -n flux-system deployment/source-controller -f    # Source issues

# Force reconciliation with fresh source fetch
flux reconcile helmrelease <name> -n <namespace> --with-source
```

#### Step 3: Common Failure Patterns

**A. Source Errors (GitRepository/HelmRepository Not Ready)**

- **Symptoms**: Sources not ready, "GitRepository not found" errors
- **Fix**: Check authentication, verify `namespace: flux-system` in sourceRef
- **Debug**: `flux describe gitrepository flux-system -n flux-system`

**B. Helm Chart Failures (HelmRelease Not Ready)**

- **Schema Validation**: Values don't match chart schema
  - Use: `helm show values <repo>/<chart> --version <version>`
- **Immutable Fields**: Resource cannot be updated
  - Solution: `flux suspend` → `kubectl delete` → `flux resume`
- **Hook Failures**: Check Job/Pod logs for failing post-install hooks

**C. Kustomize Build Failures (Kustomization Not Ready)**

- **Debug locally**:
  `flux build kustomization <name> -n flux-system --path ./kubernetes/apps/...`
- **Common causes**: YAML syntax errors, missing file references, invalid
  patches

**D. Dependency Errors**

- **Missing resources**: Application needs CRDs, secrets, or other dependencies
- **Fix**: Add `dependsOn` to Kustomization with correct namespace:
  ```yaml
  spec:
    dependsOn:
      - name: dependency-kustomization-name
        namespace: dependency-actual-namespace # NOT flux-system unless it really is
  ```
- **Common dependencies**:
  - `external-secrets` in namespace `external-secrets`
  - `cert-manager` in namespace `cert-manager`
  - `local-path-provisioner` in namespace `storage`

**E. SOPS Secret Decryption**

- **Check**: `sops-age` secret exists in `flux-system` namespace
- **Validate**: `sops -d <file.sops.yaml>` works locally
- **Verify**: `.sops.yaml` configuration is correct

#### Step 4: Advanced Recovery Techniques

**Suspend and Resume (Soft Reset)**

```bash
flux suspend kustomization <name> -n flux-system
# Manual fixes if needed
flux resume kustomization <name> -n flux-system
```

**Trace Resource Origin**

```bash
flux trace --api-version apps/v1 --kind Deployment --name <name> -n <namespace>
```

**Force Chart Re-fetch**

```bash
# Delete cached HelmChart to force complete re-fetch
kubectl delete helmchart -n flux-system <namespace>-<helmrelease-name>
flux reconcile helmrelease <name> -n <namespace> --with-source
```

**Emergency Debugging Commands**

```bash
# Check all events across cluster
kubectl get events -A --sort-by='.lastTimestamp'

# Monitor real-time Flux activity
flux logs --follow --tail=50

# Validate configuration before applying
deno task validate  # Fast parallel validation
./scripts/check-flux-config.ts
```

**Talos-Specific Issues**

For Talos Linux specific issues (node access, kubeconfig problems, storage verification):
- See [Talos Troubleshooting Guide](docs/talos-linux/troubleshooting.md)

## App Deployment Debugging Workflow

When deploying a new app via GitOps, follow this systematic approach:

### 1. Initial Deployment

```bash
# Commit and push changes first - Flux only deploys from Git
git add kubernetes/apps/<namespace>/
git commit -m "feat: add <app-name> deployment"
git push

# Force immediate reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps
```

### 2. Check Deployment Status

```bash
# Check if namespace and kustomization created
kubectl get namespace <namespace>
flux get kustomization -A | grep <app-name>

# Check HelmRelease status
flux get hr -A | grep <app-name>

# Check if pods are running
kubectl get pods -n <namespace>
```

### 3. Common Fixes

**HelmChart not found or wrong version**:

```bash
# Verify chart exists
helm repo add <repo> <url>
helm search repo <repo>/<chart> --versions

# Delete cached HelmChart to force refresh
kubectl delete helmchart -n flux-system <namespace>-<app-name>
```

**Stale resource after changes**:

```bash
# Delete the resource to force recreation
kubectl delete helmrelease <app-name> -n <namespace>
flux reconcile kustomization cluster-apps
```

**Schema validation errors**:

- Remove `retryInterval` from Kustomization/HelmRelease (not valid in Flux v2)
- Check HelmRelease values against chart schema
- Verify all required fields are present

## AI Agent Preferences for Monitoring

When asked to check system health or monitor the cluster:

1. **Use MCP Server for Real-Time Data**:
   - **ALWAYS** use `/mcp` command for live Kubernetes introspection
   - The MCP server provides direct kubectl access without manual command execution
   - Combine MCP data with monitoring scripts for comprehensive analysis

2. **Use JSON output for automated parsing**:
   - Prefer `--json` flag on monitoring scripts for structured data
   - Parse JSON output to provide concise summaries
   - Example: `./scripts/network-monitor.ts --json | jq '.summary'`

3. **Combine multiple checks efficiently**:
   ```bash
   # Run comprehensive test suite with JSON output
   deno task test:all:json
   
   # Or run specific checks for targeted analysis
   ./scripts/k8s-health-check.ts --json
   ./scripts/storage-health-check.ts --json --check-provisioner
   ```

4. **Interpret exit codes correctly**:
   - Exit code 0: System healthy
   - Exit code 1: Non-critical warnings
   - Exit code 2: Critical issues requiring attention
   - Exit code 3: Script execution errors

5. **Summarize issues concisely**:
   - Extract critical issues from JSON `.issues` array
   - Group related problems together
   - Prioritize actionable items

6. **MCP + Scripts Workflow**:
   - Use MCP for immediate resource inspection and troubleshooting
   - Run monitoring scripts for aggregated health checks
   - Cross-reference MCP live data with script outputs for validation

## Code Style & Conventions

### Script Performance & Parallelism

When writing Deno scripts for this project, **ALWAYS** leverage parallelism where possible:

#### Parallel Execution Patterns

1. **File Processing**: Use `Promise.all()` for concurrent operations
   ```typescript
   // ❌ Sequential - Slow
   for (const file of files) {
     await validateManifest(file);
   }
   
   // ✅ Parallel - Fast (5-6x speedup typical)
   const results = await Promise.all(
     files.map(file => validateManifest(file))
   );
   ```

2. **Multiple Command Execution**: Run independent commands concurrently
   ```typescript
   // ❌ Sequential
   const pods = await $`kubectl get pods -o json`.json();
   const nodes = await $`kubectl get nodes -o json`.json();
   const namespaces = await $`kubectl get namespaces -o json`.json();
   
   // ✅ Parallel
   const [pods, nodes, namespaces] = await Promise.all([
     $`kubectl get pods -o json`.json(),
     $`kubectl get nodes -o json`.json(),
     $`kubectl get namespaces -o json`.json(),
   ]);
   ```

3. **Batch Operations**: Group related operations for parallel execution
   ```typescript
   // Process manifests in parallel batches
   const batchSize = 10;
   for (let i = 0; i < items.length; i += batchSize) {
     const batch = items.slice(i, i + batchSize);
     await Promise.all(batch.map(item => processItem(item)));
   }
   ```

4. **Resource Monitoring**: Check multiple resources simultaneously
   ```typescript
   // Check all critical namespaces in parallel
   const namespaces = ["kube-system", "flux-system", "storage"];
   const healthChecks = await Promise.all(
     namespaces.map(ns => checkNamespaceHealth(ns))
   );
   ```

#### Performance Guidelines

- **Target 3-5x speedup** for I/O-bound operations through parallelism
- **Monitor CPU usage** - aim for >400% on multi-core systems
- **Set reasonable concurrency limits** to avoid overwhelming the API server
- **Use `Promise.allSettled()` when you need all results regardless of failures**

Example: The `validate-manifests.ts` script achieves 5.7x speedup (5.4s → 0.95s) by validating all Kubernetes manifests in parallel instead of sequentially.

### GitOps Principles
- **IMPORTANT**: All changes MUST be made via Git commits - Flux only deploys from Git
- **YOU MUST** validate manifests before committing: `deno task validate`
- **ALWAYS** use semantic commit messages: `feat:`, `fix:`, `docs:`, `refactor:`
- **NEVER** use kubectl apply directly - always go through GitOps

### YAML Best Practices
- **ALWAYS** specify namespace in kustomization.yaml files
- **NEVER** use `retryInterval` in Flux v2 resources (removed from schema)
- **ALWAYS** pin chart versions for predictable deployments
- **YOU MUST** check dependency namespaces match actual deployment namespaces

### Security Guidelines
- **NEVER** commit secrets directly - use 1Password + External Secrets Operator
- **ALWAYS** use ExternalSecret with `apiVersion: external-secrets.io/v1` (not v1beta1)
- **NEVER** log or expose sensitive information
- **YOU MUST** follow least privilege principles for RBAC

## Important Reminders
- Do what has been asked; nothing more, nothing less
- NEVER create files unless they're absolutely necessary for achieving your goal
- ALWAYS prefer editing an existing file to creating a new one
- When fixing issues, update the original file instead of creating new versions (e.g., fix "helmrelease.yaml" directly, don't create "helmrelease-fixed.yaml")
- When committing changes, ONLY commit files directly related to your current task to avoid conflicts with other agents working on the same branch
- NEVER proactively create documentation files (*.md) or README files unless explicitly requested
