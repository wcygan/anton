# Claude Code Hooks for Kubernetes Homelab

This directory contains safety hooks that prevent common cluster management mistakes and enhance operational security.

## Overview

The hooks are designed to run automatically when Claude Code performs operations, providing multiple layers of protection:

1. **Namespace Protection** - Prevents modification of critical infrastructure
2. **Secret Scanning** - Detects potential credential leaks  
3. **Manifest Validation** - Ensures valid Kubernetes configurations

## Phase 1 Hooks (Active)

### 🛡️ namespace-protector.ts
**Purpose**: Protect critical namespaces from accidental modification

**Protected Paths**:
- `kubernetes/apps/kube-system/` - Core Kubernetes components
- `kubernetes/apps/flux-system/` - GitOps controllers  
- `kubernetes/apps/storage/rook-ceph*` - Storage system
- `kubernetes/flux/` - Flux configuration
- `kubernetes/bootstrap/` - Bootstrap configs
- `talos/` - Node OS configuration

**Override**: `FORCE_NAMESPACE_EDIT=true`

### 🔍 secret-scanner.ts  
**Purpose**: Prevent accidentally committing secrets and credentials

**Detects**:
- API keys (OpenAI, GitHub, AWS, etc.)
- Database connection strings
- Private keys and certificates
- JWT tokens  
- Base64 encoded secrets
- Kubernetes Secret data

**Override**: `FORCE_SECRET_SCAN=true`

### ✅ manifest-validator.ts
**Purpose**: Validate Kubernetes manifests before writing

**Validates**:
- YAML syntax
- Kubernetes schema (via kubeconform if available)
- Flux v2 compatibility (no retryInterval)
- HelmRelease best practices
- Dependency configurations

**Override**: `FORCE_MANIFEST_VALIDATION=true`

## Hook Execution Order

Hooks run in sequence for Write/Edit/MultiEdit operations:

1. **namespace-protector** (3s timeout) - Fast path protection
2. **secret-scanner** (5s timeout) - Content analysis  
3. **manifest-validator** (10s timeout) - Comprehensive validation

If any hook fails with exit code 2, the operation is blocked.

## Exit Codes

- **0**: Success, proceed with operation
- **1**: Warning, proceed with caution message
- **2**: Error, block the operation

## Override Mechanisms

For emergency situations, each hook can be bypassed:

```bash
# Bypass namespace protection
FORCE_NAMESPACE_EDIT=true claude

# Bypass secret scanning  
FORCE_SECRET_SCAN=true claude

# Bypass manifest validation
FORCE_MANIFEST_VALIDATION=true claude

# Bypass all hooks (emergency only)
CLAUDE_HOOKS_DISABLED=true claude
```

## Logging

All hooks log to `/tmp/claude-hooks-{hook-name}.log` in JSON format.

Enable verbose logging:
```bash
CLAUDE_HOOK_VERBOSE=true claude
```

## Testing Hooks

Test individual hooks manually:

```bash
# Test namespace protection
./scripts/hooks/namespace-protector.ts kubernetes/apps/flux-system/test.yaml

# Test secret scanning
./scripts/hooks/secret-scanner.ts config.yaml

# Test manifest validation  
./scripts/hooks/manifest-validator.ts deployment.yaml
```

## Phase 2 Hooks (Planned)

- **prompt-guardian.ts** - Analyze risky user prompts
- **cluster-context.ts** - Inject cluster state context
- **flux-health-check.ts** - Monitor deployment health
- **storage-health-check.ts** - Validate Ceph health
- **session-summary.ts** - Generate change reports

## Troubleshooting

### Hook Timeout
If hooks timeout frequently, increase timeouts in `.claude/settings.json`

### False Positives
Use override flags for legitimate operations that trigger false alarms

### Hook Failures
Check log files in `/tmp/claude-hooks-*.log` for detailed error information

### Disable All Hooks
In emergencies: `CLAUDE_HOOKS_DISABLED=true claude`

## Configuration

Hooks are configured in `.claude/settings.json`. See the file for current configuration.

## Golden Rules Enforced

These hooks enforce the cluster's golden rules:

1. **Think before you delete. Suspend, don't delete.**
2. **All changes MUST go through Git (GitOps)**
3. **Never commit unencrypted secrets**
4. **Storage resources need special handling**

For more details, see `/docs/golden-rules/` in the repository.