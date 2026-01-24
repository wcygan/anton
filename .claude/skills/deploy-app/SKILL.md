---
name: deploy-app
description: Create new GitOps application deployment with proper structure. Use when deploying a new app, adding a helm chart, or creating a new service.
disable-model-invocation: true
argument-hint: <app-name> [namespace]
allowed-tools: Read, Write, Grep, Glob, Bash(helm:*), Bash(flux:*)
---

# Deploy New Application

Creates a complete GitOps deployment structure for the Anton cluster.

## Instructions

### 1. Gather Information

Required:
- **App name**: kebab-case (e.g., `my-app`)
- **Namespace**: Where to deploy (default: app name)
- **Chart source**: Helm repo URL or existing repo name

Optional:
- Chart version (recommend pinning)
- Custom values
- Dependencies on other Kustomizations

### 2. Verify Chart Exists

```bash
# Search for chart
helm search repo <repo>/<chart> --versions | head -5

# If repo not added, check available repos
helm repo list
```

### 3. Create Directory Structure

```
kubernetes/apps/<namespace>/<app-name>/
├── ks.yaml              # Flux Kustomization
└── app/
    ├── kustomization.yaml
    └── helmrelease.yaml
```

### 4. Generate Files

Use the templates in `templates/` directory, customizing:
- Namespace
- App name
- Chart reference
- Interval (Critical: 5m, Core: 15m, Standard: 30m-1h)
- Dependencies

### 5. Key Patterns (from CLAUDE.md)

- **NO `retryInterval`** - removed from Flux v2 schema
- **Dependencies**: Use actual namespace, not flux-system
- **Source refs**: Always include `namespace: flux-system`
- **Ingress**: Default to `internal` class
- **Kustomization**: MUST specify namespace

### 6. Validate Before Commit

```bash
# Validate manifests
deno task validate

# Check for common issues
flux check
```

## Output

Create the files and provide:
1. File paths created
2. Next steps (commit, push, verify)
3. Commands to monitor deployment

## Example Usage

```
/deploy-app grafana-oncall monitoring
```

Creates deployment for grafana-oncall in monitoring namespace.
