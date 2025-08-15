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

## AI Agent Alignment Through Speed

**The faster hooks execute, the better the AI agent alignment:**

### ⚡ Sub-Second Response (Ideal)
- **namespace-protector** - Instant path validation
- **prompt-guardian** - Real-time risk assessment
- Creates **seamless conversation flow**

### 🚀 <5 Second Response (Excellent)  
- **secret-scanner** - Multi-pattern analysis
- **cluster-context** - Health status injection
- Maintains **natural interaction pace**

### ✅ <10 Second Response (Acceptable)
- **manifest-validator** - Schema validation
- **storage-health** - Infrastructure checks
- Preserves **conversational continuity**

### ❌ >10 Second Response (Breaks Flow)
- **Degrades user experience**
- **Interrupts AI thought process**
- **Should trigger optimization**

## Hook Execution Flow (Sequential)

**PreToolUse (Write/Edit/MultiEdit)** - Total: ~8-18s
1. **namespace-protector** (1s) - Instant protection
2. **secret-scanner** (2-5s) - Credential detection  
3. **manifest-validator** (5-10s) - Configuration validation

**Early failure exits immediately** - If hook returns exit code 2, operation blocks instantly.

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

## Performance Monitoring & Optimization

### Speed Monitoring
```bash
# Check hook execution times in logs
grep "completed in" /tmp/claude-hooks-*.log

# Monitor for slow hooks (>5s)
grep -E "completed in [5-9][0-9][0-9][0-9]ms|completed in [0-9]+[0-9]s" /tmp/claude-hooks-*.log
```

### Optimization Strategies
- **Parallel execution** - Run independent checks simultaneously
- **Early termination** - Exit immediately on first critical issue
- **Caching** - Store repeated query results (5-minute TTL)
- **Selective triggering** - Only run when conditions match
- **Minimal I/O** - Reduce filesystem and network operations

### Troubleshooting Performance

#### Hook Taking >10s (CRITICAL)
1. **Check system load**: `htop`, `kubectl top nodes`
2. **Review network latency**: `kubectl get nodes` response time
3. **Optimize hook logic**: Add early exits, reduce I/O
4. **Consider async patterns**: Cache results, background updates

#### Hook Timeouts
- **Increase timeout** in `.claude/settings.json` (last resort)
- **Profile execution**: Add timing logs to identify bottlenecks
- **Split complex hooks**: Break into smaller, faster operations

#### False Positives
- **Use override flags**: `FORCE_*=true` for legitimate edge cases
- **Refine patterns**: Update regex/logic to reduce false matches
- **Add allow-lists**: Skip known-safe patterns

### Emergency Procedures
```bash
# Disable all hooks immediately
CLAUDE_HOOKS_DISABLED=true claude

# Disable specific slow hook
SKIP_STORAGE_CHECK=true claude

# Bypass protection for emergency ops
FORCE_NAMESPACE_EDIT=true claude
```

## Configuration

Hooks are configured in `.claude/settings.json`. See the file for current configuration.

## Golden Rules Enforced (Speed + Safety)

These hooks **rapidly enforce** the cluster's golden rules:

1. **Think before you delete. Suspend, don't delete.** ⚡ *~1s response*
2. **All changes MUST go through Git (GitOps)** ⚡ *~2s validation*  
3. **Never commit unencrypted secrets** ⚡ *~3s scanning*
4. **Storage resources need special handling** ⚡ *~5s health check*

**The combination of speed + enforcement creates an AI agent that operates within safe boundaries while maintaining natural conversation flow.**

## AI Agent Success Metrics

### Conversation Quality
- **<3s total hook time** = Seamless interaction
- **<10s total hook time** = Acceptable flow
- **>10s total hook time** = Degraded experience requiring optimization

### Safety Alignment  
- **0 blocked dangerous operations** that bypassed hooks
- **100% compliance** with golden rules
- **Proactive suggestions** instead of reactive fixes

### System Health
- **Real-time cluster awareness** through context injection
- **Immediate feedback** on deployment success/failure  
- **Automated rollback guidance** when issues occur

For more details, see `/docs/golden-rules/` in the repository.