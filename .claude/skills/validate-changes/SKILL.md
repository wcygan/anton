---
name: validate-changes
description: Validate Kubernetes manifests before commit. Runs deno task validate and checks for common GitOps issues.
user-invocable: false
---

# Validate Changes

Automatically validates Kubernetes manifests when changes are about to be committed.

## Activation

This skill activates automatically when:
- User mentions "commit", "push", or "ready to deploy"
- User has made changes to kubernetes/ directory
- User asks to check or validate their changes

## Instructions

### 1. Run Validation Suite

```bash
# Primary validation
deno task validate

# Check for common issues
flux check --pre
```

### 2. Check for Common Mistakes

**Schema issues:**
- `retryInterval` field (removed from Flux v2)
- Wrong API versions (e.g., v1beta1 instead of v1)

**Namespace issues:**
- Missing `namespace:` in kustomization.yaml
- Wrong namespace in `dependsOn` references
- Missing `namespace: flux-system` in sourceRef

**HelmRelease issues:**
- Chart version not pinned
- Missing remediation configuration

### 3. Git Status Check

```bash
# Show what will be committed
git status --short

# Check for sensitive files
git diff --cached --name-only | grep -E '\.(env|key|pem|secret)' && echo "WARNING: Potentially sensitive files staged"
```

### 4. Quick Smoke Tests

```bash
# Validate YAML syntax
for f in $(git diff --cached --name-only | grep -E '\.ya?ml$'); do
    yq eval '.' "$f" > /dev/null 2>&1 || echo "YAML syntax error: $f"
done
```

## Output Format

```
## Validation Results

**Status**: PASS / FAIL

### Checks
- [x] Manifest validation
- [x] Schema compliance
- [x] Namespace configuration
- [ ] Issue found: <description>

### Files Changed
- kubernetes/apps/monitoring/loki/app/helmrelease.yaml

### Ready to Commit
Yes / No - fix issues first
```

## Do NOT

- Block commits for warnings (only errors)
- Run full test suite (that's separate)
- Modify files automatically
