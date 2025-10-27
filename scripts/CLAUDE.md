# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with shell scripts in this repository.

## Project Overview

Shell scripts orchestrate cluster operations that are too complex for simple Task commands. All scripts follow strict conventions for error handling, logging, and reusability.

**Key Concept**: Reusable functions live in `scripts/lib/common.sh`. Never duplicate logic across scripts.

## The Core Pattern (3 Functions)

All scripts use 3 shared functions from `scripts/lib/common.sh`:

### 1. log() - Structured Logging

**What it does**: Prints timestamped, colored log messages with key=value context

**Levels**: debug, info, warn, error (error exits immediately)

**Usage**:
```bash
log info "Operation completed" "resource=pod" "namespace=default"
log error "Missing file" "path=/tmp/foo.yaml"
```

**Why structured**: Easy to grep logs, parse with tools, understand context at a glance

### 2. check_env() - Environment Validation

**What it does**: Verifies required environment variables exist before running script

**Usage**:
```bash
check_env KUBECONFIG SOPS_AGE_KEY_FILE
```

**Why upfront**: Fails fast if prerequisites missing (don't waste time running partial script)

### 3. check_cli() - Dependency Validation

**What it does**: Verifies required CLI tools are installed

**Usage**:
```bash
check_cli kubectl sops helmfile
```

**Why upfront**: Clear error message about what to install (better than cryptic command-not-found)

## Script Structure Pattern

Every script follows this template:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

# 1. Source shared library
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# 2. Define workflow functions (one per phase)
function phase_one() {
    log debug "Starting phase one"
    # ... work ...
    log info "Phase one completed"
}

function phase_two() {
    log debug "Starting phase two"
    # ... work ...
    log info "Phase two completed"
}

# 3. Main orchestration
function main() {
    # Validate prerequisites first
    check_env REQUIRED_VAR OTHER_VAR
    check_cli kubectl helm

    # Execute phases in order
    phase_one
    phase_two
}

# 4. Execute
main "$@"
```

**Why this structure**:
- `set -Eeuo pipefail` - Exit on any error (no silent failures)
- Functions = testable units (can mock/stub for testing)
- main() orchestrates flow (easy to see full workflow)
- Validation upfront (fail fast on missing dependencies)

## Error Handling Rules

### Rule 1: Immediate Exit on Error

**Use `set -Eeuo pipefail` at top of every script**:
- `-e` - Exit if any command fails
- `-E` - Inherit error trap in functions
- `-u` - Exit on undefined variable
- `-o pipefail` - Exit if any command in pipe fails

**Example**:
```bash
set -Eeuo pipefail

# This will exit immediately if kubectl fails
kubectl apply -f manifest.yaml
log info "Applied successfully"  # Only runs if kubectl succeeded
```

### Rule 2: Log Before Failures

**Always log context before operations that might fail**:

```bash
# ✗ Bad: No context if this fails
kubectl apply -f "${manifest}"

# ✓ Good: Clear context in logs
log debug "Applying manifest" "path=${manifest}"
kubectl apply -f "${manifest}"
log info "Manifest applied" "path=${manifest}"
```

**Why**: When script fails, last log message shows exactly what failed

### Rule 3: Readonly Variables for Safety

**Use `local readonly` for variables that shouldn't change**:

```bash
function apply_namespaces() {
    local -r apps_dir="${ROOT_DIR}/kubernetes/apps"

    # Can't accidentally overwrite apps_dir now
    for app in "${apps_dir}"/*/; do
        # ...
    done
}
```

**Why**: Prevents bugs from accidental variable reassignment

## How to Extend scripts/lib/common.sh

### Step 1: Identify Reusable Logic

**Ask**: Will this function be useful in multiple scripts?

**Add to common.sh if**:
- Input validation (checking files exist, parsing configs)
- Kubernetes operations (waiting for resources, checking status)
- String manipulation (formatting, parsing)
- Error handling patterns (retries, timeouts)

**Keep in script if**:
- Specific to one workflow (bootstrap-apps.sh specific logic)
- Tightly coupled to script context
- Uses many script-local variables

### Step 2: Write Self-Contained Function

**Pattern**:
```bash
# In scripts/lib/common.sh

# WHY: Kubernetes resources take time to become ready, need reliable wait
# Returns 0 if ready, exits 1 if timeout
function wait_for_resource() {
    local -r resource_type="${1}"  # e.g., "pod", "deployment"
    local -r resource_name="${2}"
    local -r namespace="${3}"
    local -r timeout_seconds="${4:-300}"  # Default 5 minutes

    log debug "Waiting for resource" \
        "type=${resource_type}" \
        "name=${resource_name}" \
        "namespace=${namespace}" \
        "timeout=${timeout_seconds}s"

    if kubectl wait --for=condition=ready \
        "${resource_type}/${resource_name}" \
        -n "${namespace}" \
        --timeout="${timeout_seconds}s" &>/dev/null;
    then
        log info "Resource ready" \
            "type=${resource_type}" \
            "name=${resource_name}"
        return 0
    else
        log error "Resource not ready within timeout" \
            "type=${resource_type}" \
            "name=${resource_name}" \
            "timeout=${timeout_seconds}s"
    fi
}
```

**Key points**:
- WHY comment explains motivation (not what - code shows what)
- Local readonly for all parameters (safety)
- Structured logging with context (key=value pairs)
- Default values where sensible (`${4:-300}`)
- Clear return codes (0 = success, 1 = failure)

### Step 3: Use in Scripts

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

source "${SCRIPT_DIR}/lib/common.sh"

function deploy_app() {
    kubectl apply -f app.yaml
    wait_for_resource "deployment" "my-app" "default" 600
}
```

## Integration with Taskfile.yml

Scripts are invoked by Task runner with validated environment:

**In Taskfile.yml**:
```yaml
tasks:
  bootstrap:
    apps:
      desc: Bootstrap apps into cluster
      cmd: bash {{.SCRIPTS_DIR}}/bootstrap-apps.sh
      preconditions:
        - test -f {{.KUBECONFIG}}
        - test -f {{.SOPS_AGE_KEY_FILE}}
        - test -f {{.SCRIPTS_DIR}}/bootstrap-apps.sh
```

**Script receives**:
- Validated preconditions (files exist, vars set)
- Clean environment (Task sets vars from Taskfile.yml)
- Working directory = repository root

**Why this separation**:
- Task handles declarative checks (preconditions)
- Script handles imperative work (applying resources)
- Task provides user-friendly error messages
- Script provides detailed operational logs

## Current Scripts Breakdown

### bootstrap-apps.sh (scripts/bootstrap-apps.sh:1)

**Purpose**: Initialize cluster with core services before Flux takes over

**Phases** (in strict order):
1. `wait_for_nodes()` - Wait for Talos nodes to be ready
2. `apply_namespaces()` - Create namespaces from kubernetes/apps/
3. `apply_sops_secrets()` - Install SOPS keys and GitHub deploy key
4. `apply_crds()` - Extract and install CRDs via helmfile
5. `sync_helm_releases()` - Deploy bootstrap apps with helmfile

**Dependencies**:
- `KUBECONFIG` - Path to kubeconfig file
- `SOPS_AGE_KEY_FILE` - Path to Age encryption key
- `kubectl`, `sops`, `helmfile` - CLI tools

**Example of apply_namespaces pattern** (scripts/bootstrap-apps.sh:27):
```bash
function apply_namespaces() {
    log debug "Applying namespaces"

    # Validate directory exists upfront
    local -r apps_dir="${ROOT_DIR}/kubernetes/apps"
    if [[ ! -d "${apps_dir}" ]]; then
        log error "Directory does not exist" "directory=${apps_dir}"
    fi

    # Process each namespace directory
    for app in "${apps_dir}"/*/; do
        namespace=$(basename "${app}")

        # Check if already exists (idempotent)
        if kubectl get namespace "${namespace}" &>/dev/null; then
            log info "Namespace already exists" "resource=${namespace}"
            continue
        fi

        # Apply with server-side apply (safer)
        if kubectl create namespace "${namespace}" --dry-run=client --output=yaml \
            | kubectl apply --server-side --filename - &>/dev/null;
        then
            log info "Namespace created" "resource=${namespace}"
        else
            log error "Failed to create namespace" "resource=${namespace}"
        fi
    done
}
```

**Pattern breakdown**:
- Readonly variable for directory path (safety)
- Explicit error if prerequisite missing (fail fast)
- Idempotent check (skip if exists)
- Server-side apply (conflict-free)
- Structured logging with context (resource name)

## Common Script Patterns

### Pattern 1: Retry Logic

**When**: External systems may be temporarily unavailable

```bash
function retry_command() {
    local -r max_attempts=5
    local -r delay_seconds=10
    local attempt=1

    while (( attempt <= max_attempts )); do
        if kubectl get nodes &>/dev/null; then
            log info "Command succeeded" "attempts=${attempt}"
            return 0
        fi

        log warn "Command failed, retrying" \
            "attempt=${attempt}" \
            "max=${max_attempts}" \
            "delay=${delay_seconds}s"

        sleep "${delay_seconds}"
        ((attempt++))
    done

    log error "Command failed after retries" "attempts=${max_attempts}"
}
```

### Pattern 2: File Processing Loop

**When**: Operating on multiple files/directories

```bash
function process_files() {
    local -r pattern="${1}"
    local -r base_dir="${ROOT_DIR}/kubernetes/apps"

    # Use array to handle spaces in filenames
    local files=()
    while IFS= read -r -d '' file; do
        files+=("${file}")
    done < <(find "${base_dir}" -name "${pattern}" -print0)

    if (( ${#files[@]} == 0 )); then
        log warn "No files found" "pattern=${pattern}"
        return 0
    fi

    for file in "${files[@]}"; do
        log debug "Processing file" "path=${file}"
        # ... process file ...
    done

    log info "Processing complete" "count=${#files[@]}"
}
```

### Pattern 3: Conditional Execution

**When**: Different behavior based on environment

```bash
function apply_optional_feature() {
    local -r feature_enabled="${ENABLE_FEATURE:-false}"

    # Early return if disabled (simple logic)
    if [[ "${feature_enabled}" != "true" ]]; then
        log info "Feature disabled, skipping"
        return 0
    fi

    log info "Feature enabled, applying"
    # ... feature logic ...
}
```

**Why early return**: Keeps happy path unindented (easier to read)

## Testing Scripts Locally

### Dry-run pattern
```bash
# Add DRY_RUN variable support
function apply_manifest() {
    local -r manifest="${1}"
    local -r dry_run="${DRY_RUN:-false}"

    if [[ "${dry_run}" == "true" ]]; then
        log info "DRY_RUN: Would apply" "manifest=${manifest}"
        return 0
    fi

    kubectl apply -f "${manifest}"
}

# Test with:
$ DRY_RUN=true bash scripts/my-script.sh
```

### Debug logging
```bash
# Enable debug logs
$ LOG_LEVEL=debug bash scripts/bootstrap-apps.sh

# Scripts automatically respect LOG_LEVEL from environment
# (log function filters based on this variable)
```

## Security Considerations

### Never Log Secrets

```bash
# ✗ Bad: Logs secret value
secret_value=$(cat secret.txt)
log info "Processing secret" "value=${secret_value}"

# ✓ Good: Log without exposing value
secret_file="secret.txt"
log info "Processing secret" "file=${secret_file}"
```

### Never Commit Unencrypted Secrets

```bash
# Always verify encryption before git operations
function validate_secrets() {
    local unencrypted=()

    while IFS= read -r -d '' file; do
        if ! sops filestatus "${file}" &>/dev/null; then
            unencrypted+=("${file}")
        fi
    done < <(find . -name "*.sops.*" -print0)

    if (( ${#unencrypted[@]} > 0 )); then
        log error "Unencrypted secrets found" "files=${unencrypted[*]}"
    fi
}
```

### Use Read-Only Operations When Possible

```bash
# Prefer kubectl get/describe over apply/delete
# Use --dry-run=client for validation
kubectl apply -f manifest.yaml --dry-run=client
```

## Common Mistakes (and Fixes)

### Mistake 1: Not using set -Eeuo pipefail

**Symptom**: Script continues after errors, produces confusing state

**Fix**: Always add at top of script
```bash
#!/usr/bin/env bash
set -Eeuo pipefail
```

### Mistake 2: Duplicate logic across scripts

**Symptom**: Same code in multiple scripts, bugs need fixing in multiple places

**Fix**: Extract to common.sh
```bash
# Before: Duplicated in 3 scripts
for script in script1.sh script2.sh script3.sh; do
    # ... same logic ...
done

# After: One function in common.sh
# In common.sh:
function shared_logic() { ... }

# In scripts:
source "${SCRIPT_DIR}/lib/common.sh"
shared_logic
```

### Mistake 3: Missing error context

**Symptom**: Script fails but unclear what/where/why

**Fix**: Log before operations
```bash
# Before:
kubectl apply -f "${file}"

# After:
log debug "Applying manifest" "file=${file}"
kubectl apply -f "${file}"
log info "Manifest applied" "file=${file}"
```

### Mistake 4: Assuming commands succeed

**Symptom**: Script continues with invalid state after command failure

**Fix**: Use `set -e` or explicit checks
```bash
# Option 1: set -e (automatic)
set -e
kubectl apply -f manifest.yaml
# Script exits if kubectl fails

# Option 2: explicit check (when you need custom error handling)
if ! kubectl apply -f manifest.yaml; then
    log error "Apply failed" "manifest=manifest.yaml"
fi
```

### Mistake 5: Forgetting to make script executable

**Symptom**: Permission denied when running script

**Fix**:
```bash
chmod +x scripts/my-script.sh
```

## Key Insights

1. **Reuse via common.sh** - Never duplicate logic across scripts
2. **Fail fast** - `set -Eeuo pipefail` catches errors immediately
3. **Structure logging** - key=value pairs enable easy parsing
4. **Readonly variables** - Prevent accidental reassignment bugs
5. **Validate upfront** - check_env and check_cli before doing work
6. **Log context** - Every operation logs what/where/why
7. **Idempotent operations** - Safe to re-run scripts (check before apply)

## Quick Reference

| Command | Purpose |
|---------|---------|
| `LOG_LEVEL=debug bash script.sh` | Enable debug logging |
| `DRY_RUN=true bash script.sh` | Test without applying changes |
| `shellcheck scripts/*.sh` | Lint all scripts |
| `bash -n script.sh` | Syntax check without execution |
