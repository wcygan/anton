# Ceph Daily Health Check Runbook

## Overview
This runbook provides step-by-step instructions for performing daily health checks on the Ceph distributed storage cluster.

## Schedule
- **Frequency**: Daily
- **Duration**: 5-10 minutes
- **Critical**: Yes - skip only if cluster is known to be under maintenance

## Prerequisites
- kubectl access to the cluster
- Access to Grafana dashboards (optional but recommended)

## Health Check Procedure

### 1. Check Overall Cluster Health

```bash
# Execute Ceph status check
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
```

**Expected Output**:
- `health: HEALTH_OK` - Cluster is healthy
- All OSDs should show as `up` and `in`
- Monitor quorum should show 3 monitors

**Actions if not healthy**:
- `HEALTH_WARN` - Review warnings and follow troubleshooting guide
- `HEALTH_ERR` - Immediate action required, escalate if necessary

### 2. Check OSD Status

```bash
# Check OSD tree
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd tree

# Check OSD disk usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd df
```

**Expected**:
- All 6 OSDs should be `up` and weight should be 1.0
- Disk usage variance should be <10% between OSDs
- No OSDs should be >85% full

### 3. Check Pool Health

```bash
# List pools and their status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df

# Check pool statistics
kubectl -n storage exec deploy/rook-ceph-tools -- rados df
```

**Expected**:
- All pools should show appropriate replication (size 3)
- No pools should show degraded objects

### 4. Check Monitor Status

```bash
# Check monitor quorum
kubectl -n storage exec deploy/rook-ceph-tools -- ceph mon stat

# Check monitor health
kubectl -n storage exec deploy/rook-ceph-tools -- ceph mon dump
```

**Expected**:
- 3 monitors in quorum
- All monitors should be reachable

### 5. Check PVC Status

```bash
# Check all PVCs are bound
kubectl get pvc -A | grep -v Bound

# Verify all PVCs using ceph-block
kubectl get pvc -A -o json | jq -r '.items[] | select(.spec.storageClassName != "ceph-block") | "\(.metadata.namespace)/\(.metadata.name)"'
```

**Expected**:
- No output (all PVCs are Bound and using ceph-block)

### 6. Check Rook Operator Health

```bash
# Check Rook operator logs for errors
kubectl -n storage logs -l app=rook-ceph-operator --tail=50 | grep -E "(ERROR|FATAL)" || echo "No errors found"

# Check all Rook pods are running
kubectl -n storage get pods | grep -v Running | grep -v Completed
```

**Expected**:
- No error logs in last 50 lines
- All pods in Running or Completed state

### 7. Performance Quick Check

```bash
# Check cluster I/O stats
kubectl -n storage exec deploy/rook-ceph-tools -- ceph iostat 5 1

# Check slow operations
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail | grep -i slow || echo "No slow ops"
```

**Expected**:
- No slow operations
- I/O statistics show reasonable read/write rates

## Grafana Dashboard Review (Optional)

If Grafana is accessible:

1. Navigate to Ceph Cluster dashboard
2. Check for any red/critical alerts
3. Review 24-hour trends for:
   - Cluster capacity usage
   - IOPS trends
   - Network throughput
   - OSD latency

## Daily Health Summary Template

```markdown
Date: [YYYY-MM-DD]
Time: [HH:MM]
Performed by: [Name]

Cluster Health: [ ] HEALTH_OK [ ] HEALTH_WARN [ ] HEALTH_ERR
OSDs Status: [X/6] healthy
Monitor Quorum: [ ] Yes [ ] No
PVC Status: [ ] All bound
Rook Operator: [ ] Healthy
Performance: [ ] Normal [ ] Degraded

Issues Found:
- [Issue 1]
- [Issue 2]

Actions Taken:
- [Action 1]
- [Action 2]

Follow-up Required: [ ] Yes [ ] No
```

## Escalation

If any critical issues are found:

1. Check troubleshooting guide: `docs/ceph/operations/troubleshooting.md`
2. Review recent changes in Git history
3. Check Rook Ceph documentation: https://rook.io/docs/rook/latest/

## Automation Script

A script is available to automate these checks:
```bash
./scripts/storage-health-check.ts --detailed
```