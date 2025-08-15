# Unified Monitoring CLI

A comprehensive command-line interface for all homelab monitoring operations, providing domain-focused organization and consistent user experience.

## Overview

The monitoring CLI consolidates all monitoring scripts into a single entry point with domain-based organization, replacing the growing collection of individual `deno.json` tasks.

**Current Problem:**
Your `deno.json` has 20+ monitoring tasks that are becoming unwieldy:
- `health:monitor`, `health:monitor:json`
- `storage:check`, `storage:check:json`
- `network:check`, `network:check:json`
- `test:all`, `test:all:json`, `test:quick`, `test:ci`, `test:verbose`
- And many more...

**Solution:**
Replace with a structured CLI:

```bash
# Single command, multiple domains
homelab monitor <domain> <command> [options]

# Default: Quick parallel health check (no arguments)
homelab monitor

# Specific domain commands
homelab monitor flux check --json
homelab monitor storage health --growth-analysis
homelab monitor k8s health --namespace production
```

## Implementation Plan

### Development Philosophy: Test-Driven Incremental Development

**Core Principles:**
1. **Make small changes**: Each feature should be minimal and testable
2. **Test immediately**: Run commands after every change to verify behavior
3. **Inspect data**: Examine output formats, timing, error cases
4. **Commit frequently**: Every working checkpoint gets committed
5. **Validate early**: Test edge cases and error scenarios continuously

### Phase 1: Create CLI Structure

1. **Create CLI entry point**: `scripts/cli/homelab.ts`
2. **Organize commands by domain**: `scripts/cli/commands/`
3. **Migrate existing scripts**: Wrap current scripts as subcommands
4. **Update `deno.json`**: Replace multiple tasks with single entry point

### Testing Strategy at Each Checkpoint

**After Each Code Change:**
```bash
# 1. Syntax check
deno check scripts/cli/homelab.ts

# 2. Basic functionality
deno run --allow-all scripts/cli/homelab.ts --help

# 3. Feature-specific test
deno run --allow-all scripts/cli/homelab.ts monitor [args]

# 4. Inspect output format/timing
echo "Testing output format..." && [run command] | head -20

# 5. Edge case testing
[run command with invalid args/missing deps]

# 6. Commit if working
git add . && git commit -m "checkpoint: [specific feature]"
```

### Phase 2: Migration Strategy

**Before (Current `deno.json`):**
```json
{
  "tasks": {
    "health:monitor": "deno run --allow-all scripts/cluster-health-monitor.ts",
    "health:monitor:json": "deno run --allow-all scripts/cluster-health-monitor.ts --json",
    "storage:check": "deno run --allow-all scripts/storage-health-check.ts",
    "storage:check:json": "deno run --allow-all scripts/storage-health-check.ts --json",
    "network:check": "deno run --allow-all scripts/network-monitor.ts",
    "test:all": "deno run --allow-all scripts/test-all.ts"
  }
}
```

**After (Simplified `deno.json`):**
```json
{
  "tasks": {
    "monitor": "deno run --allow-all scripts/cli/homelab.ts"
  }
}
```

**Usage Migration:**
```bash
# Old way
deno task health:monitor:json
deno task storage:check --growth-analysis
deno task test:all:json

# New way  
deno task monitor k8s health --json
deno task monitor storage health --growth-analysis
deno task monitor all --json
```

## Installation

Add to your `deno.json`:

```json
{
  "tasks": {
    "monitor": "deno run --allow-all scripts/cli/homelab.ts"
  }
}
```

Or install globally:

```bash
deno install --allow-all --name homelab scripts/cli/homelab.ts
```

## Usage

### Default Quick Check

When no arguments are provided, the CLI runs a fast parallel health check across all domains (excluding Talos):

```bash
# Quick parallel health check
homelab monitor

# Output with progress spinners:
⠋ Checking Flux status...
⠙ Checking Kubernetes health...
⠹ Checking storage health...
⠸ Checking network connectivity...

✓ Flux Configuration        [0.8s]
✓ Kubernetes Health         [1.2s]
⚠ Storage Health           [0.9s]  2 warnings
✓ Network Connectivity      [1.1s]

Summary (2.1s total):
  ✓ 3 healthy  ⚠ 1 warning  ✗ 0 critical

Issues:
  ⚠ PVC monitoring/prometheus-data is 78% full
  ⚠ PVC default/postgres-data is 82% full
```

### Basic Structure

```
homelab monitor [domain] [command] [options]

Default (no args): Quick parallel health check

Domains:
  flux       GitOps and Flux-related monitoring
  k8s        Kubernetes cluster health and resources
  storage    PVC usage and storage provisioner health
  network    Network connectivity and ingress health
  hardware   Node hardware (excludes Talos by default)
  all        Comprehensive checks (slower, more thorough)

Global Options:
  --json           Output in JSON format for CI/CD integration
  --verbose, -v    Enable detailed output
  --help, -h       Show help for any command
```

### Domain: Flux

Monitor GitOps deployments and Flux components.

```bash
# Check Flux configuration best practices
homelab monitor flux check [--json]

# Monitor active deployments
homelab monitor flux deployments [--watch] [--timeout 30]

# Real-time Flux resource monitoring
homelab monitor flux watch [--interval 5]

# Check specific namespace
homelab monitor flux status --namespace production
```

### Domain: Kubernetes

Comprehensive cluster health monitoring.

```bash
# Full cluster health check
homelab monitor k8s health [--json] [--no-flux]

# Continuous monitoring
homelab monitor k8s watch [--interval 30]

# Namespace-specific check
homelab monitor k8s health --namespace kube-system

# Resource usage summary
homelab monitor k8s resources [--sort-by cpu|memory]
```

### Domain: Storage

Storage usage and provisioner health.

```bash
# Check PVC usage
homelab monitor storage health [--json]

# Include growth analysis
homelab monitor storage health --growth-analysis

# Check provisioner
homelab monitor storage provisioner

# Set custom thresholds
homelab monitor storage health --warning 70 --critical 85

# Continuous monitoring
homelab monitor storage watch --interval 300
```

### Domain: Network

Network connectivity and service health.

```bash
# Basic connectivity check
homelab monitor network health [--json]

# Full network validation
homelab monitor network health --check-dns --check-endpoints

# Check specific services
homelab monitor network ingress [--namespace network]

# DNS resolution tests
homelab monitor network dns --test example.com
```

### Domain: Hardware

Node hardware and Talos configuration.

```bash
# Hardware inventory
homelab monitor hardware inventory [--json]

# Detect hardware changes
homelab monitor hardware changes [--baseline]

# Validate Talos config
homelab monitor hardware validate

# Node maintenance status
homelab monitor hardware maintenance --node k8s-1
```

### Domain: All

Run comprehensive health checks across all domains.

```bash
# Full system check
homelab monitor all [--json]

# Quick critical checks only
homelab monitor all --quick

# CI mode (strict)
homelab monitor all --ci

# Verbose with all details
homelab monitor all --verbose
```

## Output Formats

### Human-Readable (Default)

```
>� Homelab Monitoring Suite
==========================

[1/5]  Flux Configuration Check
[2/5]  Kubernetes Health
[3/5] �  Storage Health (2 warnings)
[4/5]  Network Connectivity
[5/5]  Hardware Status

Summary:
  Total Checks: 5
  Passed: 4
  Warnings: 1
  Critical: 0
```

### JSON Format (--json)

```json
{
  "status": "warning",
  "timestamp": "2024-01-15T10:30:00Z",
  "summary": {
    "total": 5,
    "healthy": 4,
    "warnings": 1,
    "critical": 0
  },
  "domains": {
    "flux": { "status": "healthy", "issues": [] },
    "k8s": { "status": "healthy", "issues": [] },
    "storage": { 
      "status": "warning", 
      "issues": [
        "PVC default/data-postgres-0 is 82% full",
        "PVC monitoring/prometheus-data is 79% full"
      ]
    },
    "network": { "status": "healthy", "issues": [] },
    "hardware": { "status": "healthy", "issues": [] }
  },
  "issues": [
    "PVC default/data-postgres-0 is 82% full",
    "PVC monitoring/prometheus-data is 79% full"
  ]
}
```

## CI/CD Integration

### GitHub Actions

```yaml
- name: Run Homelab Health Checks
  run: |
    deno run --allow-all scripts/cli/homelab.ts monitor all --ci --json > health-report.json
    
- name: Upload Health Report
  uses: actions/upload-artifact@v3
  with:
    name: health-report
    path: health-report.json
    
- name: Parse Health Status
  run: |
    STATUS=$(jq -r .status health-report.json)
    if [ "$STATUS" = "critical" ]; then
      exit 2
    elif [ "$STATUS" = "warning" ]; then
      exit 1
    fi
```

### GitLab CI

```yaml
health-check:
  script:
    - homelab monitor all --ci --json | tee health-report.json
    - STATUS=$(jq -r .status health-report.json)
    - |
      case $STATUS in
        critical) exit 2 ;;
        warning) exit 1 ;;
        healthy) exit 0 ;;
        *) exit 3 ;;
      esac
  artifacts:
    reports:
      junit: health-report.json
```

### Local Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running health checks..."
if ! homelab monitor all --quick --json > /tmp/health-check.json; then
  echo "Health check failed!"
  jq '.issues[]' /tmp/health-check.json
  exit 1
fi
```

## Advanced Usage

### Custom Monitoring Profiles

Create monitoring profiles in `~/.homelab/profiles.json`:

```json
{
  "production": {
    "domains": ["flux", "k8s", "storage"],
    "options": {
      "storage": { "warning": 70, "critical": 85 },
      "k8s": { "no-flux": false }
    }
  },
  "development": {
    "domains": ["k8s", "network"],
    "options": {
      "k8s": { "namespace": "development" }
    }
  }
}
```

Use profiles:

```bash
homelab monitor profile production --json
homelab monitor profile development --watch
```

### Webhook Integration

```bash
# Send alerts to webhook
homelab monitor all --webhook https://hooks.slack.com/xxx

# Custom webhook format
homelab monitor all --webhook-format slack|teams|discord
```

### Export Metrics

```bash
# Prometheus format
homelab monitor all --export prometheus > metrics.txt

# Push to Prometheus Pushgateway
homelab monitor all --push-gateway http://pushgateway:9091
```

## Troubleshooting

### Common Issues

**No cluster access:**
```bash
# Verify kubeconfig
export KUBECONFIG=/path/to/kubeconfig
homelab monitor k8s health
```

**Permission denied:**
```bash
# Ensure all permissions are granted
deno run --allow-all scripts/cli/homelab.ts monitor all
```

**JSON parsing errors:**
```bash
# Validate JSON output
homelab monitor all --json | jq .
```

### Debug Mode

```bash
# Enable debug logging
HOMELAB_DEBUG=1 homelab monitor all --verbose

# Trace command execution
HOMELAB_TRACE=1 homelab monitor flux check
```

### Performance Optimization

```bash
# Run checks in parallel (default)
homelab monitor all --parallel

# Run sequentially for debugging
homelab monitor all --sequential

# Limit concurrent checks
homelab monitor all --concurrency 2
```

## Configuration

### Environment Variables

```bash
# Set default output format
export HOMELAB_OUTPUT_FORMAT=json

# Set monitoring intervals
export HOMELAB_MONITOR_INTERVAL=60

# Custom timeout
export HOMELAB_TIMEOUT=120
```

### Config File

Create `~/.homelab/config.yaml`:

```yaml
monitoring:
  defaults:
    format: table
    verbose: false
  
  domains:
    storage:
      warning_threshold: 75
      critical_threshold: 90
    
    k8s:
      include_flux: true
      
    network:
      check_dns: true
      check_endpoints: true
  
  notifications:
    slack:
      webhook_url: ${SLACK_WEBHOOK_URL}
      enabled: true
```

## Exit Codes

The CLI uses standardized exit codes:

- `0`: All checks passed (healthy)
- `1`: Warnings detected
- `2`: Critical issues found
- `3`: Script execution error

## Implementation Benefits

### Immediate Advantages

1. **Reduced Complexity**: Single entry point vs 20+ tasks in `deno.json`
2. **Consistent Interface**: Unified help, options, and output formats
3. **Discoverability**: `homelab monitor --help` shows all available commands
4. **Maintainability**: Centralized argument parsing and validation
5. **Extensibility**: Easy to add new domains and commands

### CLI Architecture

```
scripts/cli/
├── homelab.ts              # Main CLI entry point
├── commands/
│   ├── monitor/
│   │   ├── index.ts        # Monitor command dispatcher + default quick check
│   │   ├── flux.ts         # Flux domain commands
│   │   ├── k8s.ts          # Kubernetes domain commands
│   │   ├── storage.ts      # Storage domain commands
│   │   ├── network.ts      # Network domain commands
│   │   ├── hardware.ts     # Hardware domain commands
│   │   └── all.ts          # Comprehensive health checks
│   └── shared/
│       ├── types.ts        # Shared types and interfaces
│       ├── utils.ts        # Common utilities
│       ├── output.ts       # Output formatting
│       ├── spinner.ts      # Progress indicators
│       └── parallel.ts     # Parallel execution helpers
├── tests/
│   ├── unit/
│   │   ├── utils.test.ts   # Unit tests for utilities
│   │   ├── spinner.test.ts # Spinner system tests
│   │   └── parallel.test.ts # Parallel execution tests
│   ├── integration/
│   │   ├── cli.test.ts     # CLI integration tests
│   │   ├── commands.test.ts # Command integration tests
│   │   └── output.test.ts  # Output format tests
│   ├── fixtures/
│   │   ├── mock-data.ts    # Test data and mocks
│   │   └── test-helpers.ts # Testing utilities
│   └── run-tests.ts        # Test runner
└── legacy/
    └── wrapper.ts          # Backwards compatibility wrapper
```

### Testing Suite

The CLI includes a comprehensive testing suite at `scripts/cli/tests/` to ensure reliability and prevent regressions:

**Test Organization:**
- **Unit tests**: Test individual functions and components in isolation
- **Integration tests**: Test complete CLI workflows and command interactions
- **Fixtures**: Mock data, test helpers, and reusable testing utilities

**Test Commands:**
```bash
# Run all CLI tests
deno run --allow-all scripts/cli/tests/run-tests.ts

# Run specific test category
deno test --allow-all scripts/cli/tests/unit/
deno test --allow-all scripts/cli/tests/integration/

# Run single test file
deno test --allow-all scripts/cli/tests/unit/utils.test.ts

# Test with coverage
deno test --allow-all --coverage=coverage/ scripts/cli/tests/
deno coverage coverage/ --html
```

**Testing Strategy:**
1. **Each component is tested** as it's implemented
2. **Mock external dependencies** (kubectl, flux commands) for fast, reliable tests
3. **Test both success and failure scenarios** for robust error handling
4. **Validate output formats** for both human-readable and JSON outputs
5. **Performance benchmarks** to ensure speed targets are met

### Default Quick Check Implementation

The default command (`homelab monitor` with no args) implements:

1. **Parallel Execution**: All checks run simultaneously
2. **Progress Indicators**: Animated spinners for each domain
3. **Speed Optimization**: Minimal checks, no Talos operations
4. **Clean Output**: Real-time updates with final summary

**Quick Check Scope:**
- **Flux**: Basic status (`flux get all -A` equivalent)
- **Kubernetes**: Pod/node readiness, critical namespaces only
- **Storage**: PVC usage > 75%, provisioner pod status
- **Network**: Ingress controller pods, basic connectivity

**Performance Targets:**
- Total execution time: < 3 seconds
- Individual checks: < 1.5 seconds each
- Spinner refresh rate: 10Hz for smooth animation

### Current Task Mapping

| Current Task | New Command | Notes |
|--------------|-------------|-------|
| `test:quick` | `monitor` (default) | Fast parallel check, no args needed |
| `health:monitor` | `monitor k8s health` | |
| `health:monitor:json` | `monitor k8s health --json` | |
| `storage:check` | `monitor storage health` | |
| `storage:check:json` | `monitor storage health --json` | |
| `network:check` | `monitor network health` | |
| `test:all` | `monitor all` | Comprehensive, slower checks |
| `test:all:json` | `monitor all --json` | |
| `check-flux-config` | `monitor flux check` | |
| `monitor-flux` | `monitor flux watch` | |

### Quick vs Comprehensive Commands

**Quick (Default `monitor`):**
- Parallel execution, < 3 seconds total
- Essential checks only
- No Talos operations
- Progress spinners
- Perfect for frequent monitoring

**Comprehensive (`monitor all`):**
- Sequential execution for thoroughness
- Deep validation and analysis
- Includes hardware/Talos checks
- Detailed reporting
- Best for troubleshooting

## Future Enhancements

### Planned Features

1. **Interactive Mode**
   ```bash
   homelab monitor --interactive
   ```

2. **Historical Trending**
   ```bash
   homelab monitor trends --days 7
   ```

3. **Automated Remediation**
   ```bash
   homelab monitor all --auto-fix
   ```

4. **Custom Check Plugins**
   ```bash
   homelab monitor custom my-check --script ./checks/custom.ts
   ```

5. **Report Generation**
   ```bash
   homelab monitor report --format pdf --email admin@example.com
   ```

### Migration Timeline with Incremental Testing

**Week 1: Foundation & Core Structure**
- Day 1: Basic CLI entry point + argument parsing
  - Checkpoint: `homelab monitor --help` works
  - Commit: "feat(cli): add basic CLI structure with help"
- Day 2: Add shared types and utilities
  - Test: Import/export works, no runtime errors
  - Commit: "feat(cli): add shared types and utilities"
- Day 3: Implement spinner system
  - Test: Basic spinner animation works
  - Commit: "feat(cli): add progress spinner system"
- Day 4: Build parallel execution framework
  - Test: Run 2-3 dummy parallel tasks with spinners
  - Commit: "feat(cli): add parallel execution with progress tracking"

**Week 2: Core Commands (Incremental Testing)**
- Day 1: Implement basic `monitor` default command skeleton
  - Test: `homelab monitor` shows "not implemented" for each domain
  - Inspect: Verify spinner placeholders appear correctly
  - Commit: "feat(cli): add default monitor command structure"
- Day 2: Add Flux quick check
  - Test: `homelab monitor` runs flux check only, verify data format
  - Inspect: Check actual vs expected flux status output
  - Compare: Run alongside existing `deno task check-flux-config`
  - Commit: "feat(cli): implement flux quick check"
- Day 3: Add Kubernetes quick check
  - Test: `homelab monitor` runs flux + k8s, verify parallel execution
  - Inspect: Measure actual timing, verify both spinners animate
  - Debug: Test with cluster unreachable, verify error handling
  - Commit: "feat(cli): implement kubernetes quick check"
- Day 4: Add Storage quick check
  - Test: `homelab monitor` runs 3 domains, check timing < 3s
  - Inspect: Verify PVC data matches existing `deno task storage:check`
  - Performance: Use `time homelab monitor` to validate speed targets
  - Commit: "feat(cli): implement storage quick check"
- Day 5: Add Network quick check
  - Test: `homelab monitor` full default command, validate output format
  - Inspect: Compare JSON output schema with existing scripts
  - Integration: Test all 4 domains running in parallel
  - Commit: "feat(cli): implement network quick check, complete default command"

**Week 3: Domain-Specific Commands (Test Each Domain)**
- Day 1: Implement `monitor flux` subcommands
  - Test: `monitor flux check`, `monitor flux watch` work independently
  - Compare: Side-by-side with `deno task check-flux-config`
  - Inspect: Verify all flux subcommand outputs match expectations
  - Commit: "feat(cli): implement flux domain commands"
- Day 2: Implement `monitor k8s` subcommands
  - Test: `monitor k8s health --json`, verify JSON schema
  - Validate: JSON output parseable with `jq`
  - Cross-check: Compare with existing `deno task health:monitor:json`
  - Commit: "feat(cli): implement kubernetes domain commands"
- Day 3: Implement `monitor storage` subcommands
  - Test: `monitor storage health --growth-analysis`
  - Inspect: Verify PVC analysis data format and accuracy
  - Performance: Test provisioner checks work as expected
  - Commit: "feat(cli): implement storage domain commands"
- Day 4: Implement `monitor network` subcommands
  - Test: `monitor network health --check-dns`
  - Debug: Test DNS failures, ingress issues
  - Validate: Network connectivity checks are accurate
  - Commit: "feat(cli): implement network domain commands"
- Day 5: Implement `monitor all` comprehensive command
  - Test: Compare output with current `deno task test:all`
  - Performance: Measure vs existing comprehensive suite
  - Integration: Verify all domain flags work together
  - Commit: "feat(cli): implement comprehensive monitoring command"

**Week 4: Integration & Polish (Validate Everything)**
- Day 1: Add JSON output support across all commands
  - Test: Every command with `--json` flag, validate schema consistency
  - Validate: `cat output.json | jq .` for each command
  - Cross-check: Ensure JSON matches existing script outputs
  - Commit: "feat(cli): add standardized JSON output"
- Day 2: Implement backwards compatibility wrapper
  - Test: Ensure existing `deno.json` tasks still work
  - Regression: Run full existing test suite: `deno task test:all`
  - Compare: Old vs new outputs side-by-side
  - Commit: "feat(cli): add backwards compatibility for existing tasks"
- Day 3: Add error handling and edge cases
  - Test: Network failures, missing kubectl, invalid args
  - Debug scenarios: Cluster down, wrong kubeconfig, permission denied
  - Validate: Graceful error messages and exit codes
  - Commit: "feat(cli): improve error handling and edge cases"
- Day 4: Performance optimization and final testing
  - Test: Measure actual performance vs targets (< 3s default)
  - Benchmark: `time homelab monitor` and analyze bottlenecks
  - Optimize: Profile and improve slow operations
  - Commit: "perf(cli): optimize parallel execution performance"
- Day 5: Update documentation and examples
  - Test: All examples in docs work as written
  - Validate: Copy/paste every code example and run it
  - Integration: Full end-to-end testing of documented workflows
  - Commit: "docs(cli): update documentation with working examples"

### Checkpoint Validation Commands

**Essential tests to run at each checkpoint:**
```bash
# Syntax and type checking
deno check scripts/cli/homelab.ts

# Basic functionality
deno run --allow-all scripts/cli/homelab.ts --help
deno run --allow-all scripts/cli/homelab.ts monitor --help

# Feature testing
deno run --allow-all scripts/cli/homelab.ts monitor
time deno run --allow-all scripts/cli/homelab.ts monitor

# JSON validation 
deno run --allow-all scripts/cli/homelab.ts monitor --json | jq .

# Comparison testing (run alongside existing)
deno task test:all:json > old.json
deno run --allow-all scripts/cli/homelab.ts monitor all --json > new.json
diff <(jq -S . old.json) <(jq -S . new.json)

# Error scenario testing
deno run --allow-all scripts/cli/homelab.ts monitor invalid-command
KUBECONFIG=/nonexistent deno run --allow-all scripts/cli/homelab.ts monitor
```

## Related Documentation

- [Monitoring Scripts Overview](../scripts-quick-reference.md)
- [Flux Configuration Best Practices](../flux-configuration-analysis.md)
- [Storage Management](../talos-linux/disks-and-storage.md)
- [Network Architecture](../cluster-template/hardware-upgrades.md)