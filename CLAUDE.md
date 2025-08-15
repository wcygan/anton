# CLAUDE.md

This file provides guidance to Claude Code when working with this Kubernetes homelab repository.

## 🚨 CRITICAL: Golden Rules

- **Think before you delete. Suspend, don't delete.**
- All changes MUST go through Git (GitOps)
- Never commit unencrypted secrets
- Storage resources need special handling

## 🎯 Repository Overview

**Anton Cluster**: Production-grade Kubernetes homelab on 3 MS-01 nodes using Talos Linux and Flux GitOps.

### Quick Reference
```bash
# Essential Commands
task init && task configure          # Initial setup
task bootstrap:talos && task bootstrap:apps  # Bootstrap cluster
task reconcile                        # Force Flux reconciliation
flux get all -A                      # Check all Flux resources
./scripts/k8s-health-check.ts --json # Health check

# Node IPs
k8s-1: 192.168.1.98
k8s-2: 192.168.1.99  
k8s-3: 192.168.1.100
```

## 🤖 Specialized Sub-Agents

Use these agents for complex cluster operations:

| Agent | Purpose | When to Use |
|-------|---------|------------|
| **cluster-health-auditor** | CVE scanning, maintenance planning | Monthly audits, after upgrades |
| **cluster-tech-lead** | Architectural guidance, integration planning | New operators, GitOps reviews |
| **integration-analyzer** | Multi-component troubleshooting | Integration failures, dependency issues |
| **k8s-ops-architect** | Monitoring strategy, operational excellence | Alert design, resource governance |
| **resource-optimization-analyst** | Resource efficiency, technical debt | Pod instability, optimization |

**Example**: `"Analyze cluster for CVEs and create maintenance plan"` → cluster-health-auditor

## 📚 MCP Servers for Documentation

### Context7 (Official Docs)
```bash
# Get library ID
/mcp context7:resolve-library-id rook
# Fetch documentation
/mcp context7:get-library-docs /rook/rook "ceph configuration" 5000
```

Common libraries: `/kubernetes/website`, `/rook/rook`, `/fluxcd/flux2`, `/cilium/cilium`

### Kubernetes MCP
Use `/mcp` for direct cluster access instead of manual kubectl commands.

## 🚀 GitOps Workflow

### App Deployment Structure
```
kubernetes/apps/{namespace}/{app-name}/
├── ks.yaml              # Flux Kustomization
└── app/
    ├── kustomization.yaml  # MUST specify namespace!
    └── helmrelease.yaml
```

### Key Patterns
- **Flux v2**: NO `retryInterval` field (removed from schema)
- **Dependencies**: Use actual namespace, not flux-system
- **Source refs**: Always include `namespace: flux-system`
- **Intervals**: Critical: 5m, Core: 15m, Standard: 30m-1h
- **Ingress**: Default `internal`, use `external` only when explicit

### Pre-Deployment Checklist
1. Verify chart exists: `helm search repo <repo>/<chart> --versions`
2. Check dependencies: `flux get kustomization -A | grep <dep>`
3. Validate manifests: `deno task validate`
4. Commit to Git (Flux only deploys from Git)

## 🔐 Secrets Management

**Preferred**: 1Password + External Secrets Operator
- Use `apiVersion: external-secrets.io/v1` (NOT v1beta1)
- Field names are case-sensitive
- Setup: `./scripts/setup-1password-connect.ts`

**Legacy**: SOPS for existing secrets only (*.sops.yaml files)

## 🛠️ Troubleshooting

### Systematic Debugging
1. **Initial triage**: `flux get all -A` (find Ready: False)
2. **Investigate**: `flux describe helmrelease <name> -n <namespace>`
3. **Controller logs**: 
   - helm-controller (HelmRelease issues)
   - kustomize-controller (Kustomization issues)
   - source-controller (Source issues)
4. **Force refresh**: `flux reconcile hr <name> -n <namespace> --with-source`

### Common Fixes
```bash
# Force chart re-fetch
kubectl delete helmchart -n flux-system <namespace>-<name>
flux reconcile hr <name> -n <namespace> --with-source

# Suspend/Resume for stuck resources
flux suspend kustomization <name> -n flux-system
flux resume kustomization <name> -n flux-system

# Check events
kubectl get events -A --sort-by='.lastTimestamp'
```

### Failure Patterns
- **GitRepository not found**: Check sourceRef namespace
- **Schema validation**: Remove `retryInterval`, verify values
- **Dependency errors**: Ensure correct namespace in dependsOn
- **Immutable fields**: Suspend → Delete → Resume

## 📊 Monitoring & Health

### Monitoring Scripts (Deno)
All scripts support `--json` for CI/CD integration:
- `k8s-health-check.ts` - Comprehensive health
- `storage-health-check.ts` - Storage and PVCs
- `flux-deployment-check.ts` - GitOps verification
- `test-all.ts` - Full test suite
- `validate-manifests.ts` - Parallel validation (5x faster)

### Exit Codes
- 0: Healthy
- 1: Warnings (degraded)
- 2: Critical (immediate attention)
- 3: Script error

### Grafana Dashboards
- **Location**: `/kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/`
- **Principle**: Consolidate, don't proliferate (one dashboard per function)
- **Avoid**: Version suffixes, duplicate dashboards

## 🗄️ Storage (Rook-Ceph)

- **Primary**: Ceph distributed storage (`ceph-block` default class)
- **6x 1TB NVMe** (2 per node), 3-way replication
- **Dashboard**: Accessible via Tailscale at `ceph-dashboard`

### Daily Operations
```bash
# Health check
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status

# Storage usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df
```

## 📝 Project History

Check `/docs/milestones/` for past deployments and lessons learned:
```bash
# Find relevant milestones
ls docs/milestones/*storage*.md
grep -l "Loki" docs/milestones/*.md
```

## ⚡ Performance Guidelines

### Script Parallelism
```typescript
// ✅ Parallel - Fast
const results = await Promise.all(
  files.map(file => validateManifest(file))
);

// ❌ Sequential - Slow
for (const file of files) {
  await validateManifest(file);
}
```

### Critical Reminders
- All changes via Git commits (GitOps)
- Validate before committing: `deno task validate`
- Use semantic commits: `feat:`, `fix:`, `docs:`
- Never kubectl apply directly
- Pin chart versions for predictability
- Specify namespace in kustomization.yaml
- Check dependency namespaces carefully

## 🏗️ Architecture

- **OS**: Talos Linux (immutable, API-driven)
- **GitOps**: Flux v2.5.1
- **CNI**: Cilium (kube-proxy replacement)
- **Ingress**: Dual NGINX (internal/external)
- **External**: Cloudflare tunnel
- **Namespaces**: external-secrets, network, monitoring, storage, kubeai

## Important Reminders
- Do what's asked; nothing more, nothing less
- Prefer editing existing files over creating new ones
- Only commit files directly related to current task
- Never proactively create documentation unless requested