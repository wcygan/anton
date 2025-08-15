# Hardware Management Scripts - Quick Reference

## Node Information

- **Node Names**: k8s-1, k8s-2, k8s-3
- **Node IPs**: 192.168.1.98, 192.168.1.99, 192.168.1.100

## Script Usage

### 1. Node Maintenance Manager (`node:maintain`)

**Purpose**: Safely drain/restore nodes for maintenance

**Accepts**: Both k8s node names (k8s-1) and IP addresses (192.168.1.98)

```bash
# Check node status
deno task node:maintain -n k8s-1 -a status
deno task node:maintain -n 192.168.1.98 -a status

# Simulate draining (safe - no changes)
deno task node:maintain -n k8s-2 -a drain --dry-run

# Actually drain node (with confirmation)
deno task node:maintain -n k8s-1 -a drain

# Restore after maintenance
deno task node:maintain -n k8s-1 -a restore
```

### 2. Hardware Change Detector (`hw:detect`)

**Purpose**: Detect hardware changes and generate config patches

**Accepts**: Only Talos IP addresses (192.168.1.98, 192.168.1.99, 192.168.1.100)

```bash
# Save current hardware baseline
deno task hw:detect -n 192.168.1.98 --save-baseline

# List available snapshots for a node
deno task hw:detect -n 192.168.1.98 --list-snapshots

# Detect changes (dry-run)
deno task hw:detect -n 192.168.1.99 --dry-run

# Compare with specific snapshot
deno task hw:detect -n 192.168.1.98 -b snapshots/hardware/k8s-1/1749320294.json
```

### 3. Cluster Health Monitor (`health:monitor`)

**Purpose**: Monitor overall cluster health

**Accepts**: No node parameter (cluster-wide)

```bash
# One-time health check
deno task health:monitor

# Continuous monitoring
deno task health:monitor --watch

# Critical issues only
deno task health:monitor --critical-only

# Include Flux status
deno task health:monitor --flux
```

## Testing Results ✅

All scripts tested successfully:

1. **Node Maintenance**:
   - ✅ Works with both node names and IPs
   - ✅ Dry-run mode prevents changes
   - ✅ Shows detailed status and resource usage
   - ✅ Talos integration working

2. **Hardware Detection**:
   - ✅ Collects detailed hardware inventory
   - ✅ Maps IPs to hostnames via talconfig.yaml
   - ✅ Detects differences in hardware configs
   - ✅ Shows unique serials/MACs per node
   - ✅ Organized snapshots:
     `/snapshots/hardware/<hostname>/<unix-timestamp>.json`
   - ✅ MAC address sanitization for public repository safety

3. **Health Monitor**:
   - ✅ Comprehensive cluster health reporting
   - ✅ Resource usage monitoring
   - ✅ Critical issue detection
   - ✅ Flux integration ready

## Safety Features

- All scripts have `--dry-run` modes
- Node maintenance requires explicit confirmation
- Hardware detection shows changes before applying
- Health monitor is read-only by design
- Error handling with graceful failures

## Common Workflows

### Pre-Hardware Upgrade

```bash
# 1. Check cluster health
deno task health:monitor --critical-only

# 2. Save hardware baseline
deno task hw:detect -n 192.168.1.98 --save-baseline

# 3. Check node status
deno task node:maintain -n k8s-1 -a status

# 4. Simulate drain
deno task node:maintain -n k8s-1 -a drain --dry-run
```

### During Hardware Upgrade

```bash
# 1. Drain node for maintenance
deno task node:maintain -n k8s-1 -a drain

# 2. [Perform hardware upgrade]

# 3. Detect changes
deno task hw:detect -n 192.168.1.98

# 4. Restore node
deno task node:maintain -n k8s-1 -a restore
```

### Monitoring During Maintenance

```bash
# Run in separate terminal
deno task health:monitor --watch --critical-only
```
