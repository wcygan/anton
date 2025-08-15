# Claude Code Hooks for Kubernetes Homelab

**CRITICAL: All hooks are optimized for speed (<10s execution) to maintain conversational flow while providing essential guardrails.**

## Philosophy

These hooks serve as **intelligent guardrails** that:
- **Align AI agents** with operational safety goals
- **Constrain conversations** to high-quality, safe outcomes
- **Maintain system health** through proactive monitoring
- **Execute rapidly** to preserve natural interaction flow

The hooks transform Claude Code into a **production-ready cluster operator** that follows your golden rules and best practices automatically.

## Core Design Principles

### ⚡ Speed First
- **Target: <3s for critical hooks, <10s maximum**
- **Parallel execution** where possible
- **Caching** for repeated queries
- **Selective triggers** - only run when relevant
- **Fail-fast** with clear feedback

### 🎯 Quality Alignment  
- **Enforce golden rules** automatically
- **Inject context** for informed decisions
- **Suggest alternatives** for risky operations
- **Prevent common mistakes** before they happen

### 🛡️ System Health
- **Monitor deployments** after changes
- **Validate configurations** before writes
- **Track changes** for easy rollback
- **Alert on degraded states**

## Hook Performance Targets

| Hook Type | Speed Target | Timeout | Purpose |
|-----------|--------------|---------|---------|
| **Critical Protection** | <3s | 3-5s | Block dangerous operations |
| **Validation** | <5s | 10s | Ensure config quality |
| **Health Monitoring** | <8s | 8s | Post-operation verification |
| **Context Injection** | <5s | 5s | Enhance AI awareness |

## Phase 1 Hooks (Critical Protection - <5s)

### 🛡️ namespace-protector.ts ⚡ **~1s**
**Purpose**: **Instantly block** critical infrastructure modifications
**Performance**: Path-based regex matching for millisecond response
**Triggers**: PreToolUse on Write|Edit|MultiEdit
**Protected Paths**: kube-system, flux-system, storage/rook-ceph, talos/
**Override**: `FORCE_NAMESPACE_EDIT=true`

### 🔍 secret-scanner.ts ⚡ **~2-5s**  
**Purpose**: **Rapidly detect** credential leaks before commit
**Performance**: Multi-pattern regex scan with early termination
**Triggers**: PreToolUse on Write|Edit|MultiEdit
**Detects**: API keys, passwords, tokens, base64 secrets, private keys
**Override**: `FORCE_SECRET_SCAN=true`

### ✅ manifest-validator.ts ⚡ **~5-10s**
**Purpose**: **Fast validation** of Kubernetes configurations
**Performance**: Parallel YAML+schema validation, kubeconform integration
**Triggers**: PreToolUse on Write|Edit|MultiEdit  
**Validates**: YAML syntax, K8s schema, Flux v2 patterns, HelmRelease structure
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

## Phase 2-4 Hooks (Active)

## Phase 2-4 Hooks (Intelligence & Monitoring - <8s)

### 🛡️ prompt-guardian.ts ⚡ **~1-3s**
**Purpose**: **Instantly analyze** risky prompts and inject safety context
**Performance**: Regex pattern matching with cached alternatives
**Triggers**: UserPromptSubmit (before AI processing)
**AI Alignment**: Transforms dangerous requests into safe, guided conversations
**Override**: `FORCE_PROMPT_GUARDIAN=true`

### 🌐 cluster-context.ts ⚡ **~2-5s**  
**Purpose**: **Rapidly inject** cluster health for informed AI decisions
**Performance**: Parallel kubectl queries with 5-minute caching
**Triggers**: UserPromptSubmit (first prompt only)
**AI Alignment**: Provides real-time cluster state for contextual responses
**Override**: `SKIP_CLUSTER_CONTEXT=true`

### 🔄 flux-health-check.ts ⚡ **~3-8s**
**Purpose**: **Quick verification** of GitOps deployment health
**Performance**: Targeted Flux resource queries, failure-focused
**Triggers**: PostToolUse after `flux reconcile` commands
**AI Alignment**: Ensures AI gets immediate feedback on deployment success
**Override**: `SKIP_FLUX_CHECK=true`

### 🗄️ storage-health-check.ts ⚡ **~4-8s**
**Purpose**: **Fast validation** of Ceph storage integrity  
**Performance**: Parallel Ceph status + PVC checks with JSON parsing
**Triggers**: PostToolUse for storage-related operations
**AI Alignment**: Blocks AI from proceeding if storage is degraded
**Override**: `SKIP_STORAGE_CHECK=true`

### 📋 session-summary.ts ⚡ **~2-5s**
**Purpose**: **Efficient tracking** of all session changes
**Performance**: Parallel git status + file analysis with caching
**Triggers**: Stop event (session end)
**AI Alignment**: Provides comprehensive change context for future sessions
**Override**: `SKIP_SESSION_SUMMARY=true`

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