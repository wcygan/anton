# Hooks Implementation Plan for Kubernetes Homelab

## Overview
Implement safety hooks for Claude Code to prevent cluster damage and enhance operational safety. Each hook will be implemented and tested individually before proceeding to the next.

## Implementation Order (by Risk Priority)

### Phase 1: Critical Safety (Prevent Disasters)

#### 1. Manifest Validator Hook
**Priority**: HIGHEST - Prevents invalid configs from being written
**Location**: `scripts/hooks/manifest-validator.ts`
**Trigger**: PreToolUse on Write|Edit|MultiEdit for kubernetes/ paths
**Function**:
- Validate YAML syntax
- Check Kubernetes schema with kubeconform
- Validate Flux resources (no retryInterval, correct namespaces)
- Validate Helm releases with helm template
**Exit Codes**:
- 0: Valid, proceed
- 1: Warnings (proceed with caution message)
- 2: Invalid (block operation)

#### 2. Namespace Protector Hook
**Priority**: CRITICAL - Shields core infrastructure
**Location**: `scripts/hooks/namespace-protector.ts`
**Trigger**: PreToolUse on Write|Edit|Delete
**Protected Paths**:
- `kubernetes/apps/kube-system/`
- `kubernetes/apps/flux-system/`
- `kubernetes/apps/storage/rook-ceph*/`
- `kubernetes/flux/`
**Function**:
- Check if path affects protected resources
- Require FORCE_NAMESPACE_EDIT=true to proceed
- Log all attempts to modify protected areas
**Exit Codes**:
- 0: Safe path or override set
- 2: Protected path, block operation

#### 3. Secret Scanner Hook
**Priority**: HIGH - Prevents credential leaks
**Location**: `scripts/hooks/secret-scanner.ts`
**Trigger**: PreToolUse on Write|Edit|MultiEdit
**Function**:
- Scan for base64 encoded strings (potential secrets)
- Check for common secret patterns (API keys, passwords)
- Verify SOPS encryption for .sops.yaml files
- Ensure no plaintext secrets in non-encrypted files
**Exit Codes**:
- 0: No secrets detected
- 2: Potential secret leak detected

### Phase 2: Operational Safety

#### 4. Prompt Guardian Hook
**Priority**: HIGH - Catches dangerous operations early
**Location**: `scripts/hooks/prompt-guardian.ts`
**Trigger**: UserPromptSubmit
**Dangerous Patterns**:
- "delete namespace"
- "remove pvc"
- "wipe storage"
- "reset cluster"
- "delete all"
**Function**:
- Analyze user prompt for risky operations
- Inject safety context and warnings
- Suggest safer alternatives
**Exit Codes**:
- 0: Safe operation
- 1: Risky operation (inject warnings)

#### 5. Cluster Context Injector
**Priority**: MEDIUM - Improves agent awareness
**Location**: `scripts/hooks/cluster-context.ts`
**Trigger**: UserPromptSubmit (first message)
**Function**:
- Get current cluster health status
- List critical workloads and their states
- Check Flux sync status
- Identify any ongoing issues
- Inject context as system message
**Exit Codes**:
- 0: Context injected
- 1: Partial context (cluster degraded)

### Phase 3: Post-Operation Validation

#### 6. Flux Health Monitor
**Priority**: MEDIUM - Ensures changes deploy correctly
**Location**: `scripts/hooks/flux-health-check.ts`
**Trigger**: PostToolUse after Bash commands with "flux reconcile"
**Function**:
- Wait for reconciliation to complete
- Check for failed resources
- Report deployment status
- Suggest rollback if failures detected
**Exit Codes**:
- 0: Healthy deployment
- 1: Warnings in deployment
- 2: Failed deployment

#### 7. Storage Health Guardian
**Priority**: HIGH - Protects data layer
**Location**: `scripts/hooks/storage-health-check.ts`
**Trigger**: PostToolUse on storage-related paths
**Function**:
- Check Ceph cluster health
- Verify OSD status
- Monitor PG states
- Block if cluster degraded
**Exit Codes**:
- 0: Storage healthy
- 2: Storage degraded (block further operations)

### Phase 4: Session Management

#### 8. Session Summary Generator
**Priority**: LOW - Helpful for review
**Location**: `scripts/hooks/session-summary.ts`
**Trigger**: Stop
**Function**:
- List all files modified
- Show Flux resources changed
- Generate rollback commands
- Create session report
**Exit Codes**:
- 0: Summary generated

## Implementation Steps for Each Hook

### For Each Hook:
1. **Create script file** with proper shebang and permissions
2. **Implement core logic** with clear error messages
3. **Add to settings.json** with minimal config first
4. **Test manually** to verify functionality
5. **Test with Claude** to ensure proper integration
6. **Adjust timeout/output** based on performance
7. **Document** any special considerations

## Testing Strategy

### Unit Testing Each Hook:
```bash
# Test with valid input
echo "valid yaml" | ./scripts/hooks/manifest-validator.ts
# Test with invalid input
echo "invalid: [yaml" | ./scripts/hooks/manifest-validator.ts
# Check exit codes
echo $?
```

### Integration Testing:
1. Create test scenarios for each hook
2. Verify hooks trigger at correct times
3. Ensure hooks don't interfere with normal operations
4. Test override mechanisms (FORCE_* variables)

## Settings.json Structure

Start minimal and expand:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "cd $CLAUDE_PROJECT_DIR && ./scripts/hooks/manifest-validator.ts",
            "description": "Validate K8s manifests",
            "timeout": 10000,
            "suppressOutput": false
          }
        ]
      }
    ]
  }
}
```

## Success Criteria

Each hook must:
- ✅ Execute in under 10 seconds
- ✅ Provide clear, actionable feedback
- ✅ Have an override mechanism for emergencies
- ✅ Not interfere with read-only operations
- ✅ Log attempts for audit purposes
- ✅ Handle errors gracefully

## Rollout Plan

1. **Day 1**: Implement manifest-validator (most critical)
2. **Day 2**: Add namespace-protector and secret-scanner
3. **Day 3**: Deploy prompt-guardian and cluster-context
4. **Day 4**: Add flux-health and storage-health monitors
5. **Day 5**: Complete with session-summary

## Monitoring Hook Effectiveness

Track:
- Number of prevented errors
- False positive rate
- Performance impact
- User override frequency

## Emergency Procedures

If hooks cause issues:
1. Disable via `CLAUDE_HOOKS_DISABLED=true`
2. Remove problematic hook from settings.json
3. Debug with verbose logging
4. Fix and re-enable gradually