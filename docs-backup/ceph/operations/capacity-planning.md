# Ceph Capacity Planning Guide

## Overview
This guide helps plan and manage storage capacity for the Ceph cluster, ensuring adequate space for growth while maintaining performance.

## Current Capacity

### Physical Capacity
- **Total Raw**: 6TB (6x 1TB NVMe drives)
- **Usable (3x replication)**: ~2TB
- **Current Usage**: 116Gi (~5.7%)
- **Available**: ~1.88TB

### Per-Node Distribution
- **k8s-1**: 2x 1TB NVMe (OSD.0, OSD.1)
- **k8s-2**: 2x 1TB NVMe (OSD.2, OSD.3)
- **k8s-3**: 2x 1TB NVMe (OSD.4, OSD.5)

## Monitoring Capacity

### Daily Checks
```bash
# Overall cluster usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df

# Per-OSD usage
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd df tree

# Pool statistics
kubectl -n storage exec deploy/rook-ceph-tools -- rados df
```

### Capacity Metrics to Track

1. **Cluster Fill Rate**
   ```bash
   # Calculate daily growth rate
   # Today's usage - Yesterday's usage = Daily growth
   ```

2. **Pool Distribution**
   ```bash
   # Check which pools consume most space
   kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd pool stats
   ```

3. **PVC Growth Patterns**
   ```bash
   # Track PVC sizes over time
   kubectl get pv -o json | jq -r '.items[] | select(.spec.csi.driver=="storage.csi.ceph.com") | "\(.spec.capacity.storage) \(.spec.claimRef.namespace)/\(.spec.claimRef.name)"' | sort -h
   ```

## Capacity Thresholds

### Warning Levels
- **50% Full (1TB)**: Start planning for expansion
- **70% Full (1.4TB)**: Order new drives
- **80% Full (1.6TB)**: Implement expansion plan
- **85% Full (1.7TB)**: Critical - immediate action required

### Automatic Warnings
Ceph will warn at:
- **nearfull ratio**: 85% (default)
- **full ratio**: 95% (default)

Check current settings:
```bash
kubectl -n storage exec deploy/rook-ceph-tools -- ceph config get mon mon_osd_nearfull_ratio
kubectl -n storage exec deploy/rook-ceph-tools -- ceph config get mon mon_osd_full_ratio
```

## Growth Projections

### Current Growth Rate
Based on migration data:
- **Initial Storage**: 116Gi
- **Largest Workload**: Airflow logs (100Gi)
- **Average PVC Size**: 23.2Gi

### Projection Formula
```
Days until full = (Available capacity - Current usage) / Daily growth rate

Example:
- Available: 1.88TB (1925Gi)
- Current: 116Gi
- If growing at 5Gi/day: 362 days until full
```

### Workload Categories

1. **Databases** (Low growth - 1-2Gi/month)
   - PostgreSQL
   - DragonFly cache

2. **Logs** (High growth - 10-50Gi/month)
   - Airflow triggerer logs
   - Application logs

3. **Application Data** (Variable)
   - Open WebUI
   - Future workloads

## Expansion Planning

### Option 1: Add More Drives (Recommended)
Each node has space for additional NVMe drives:
- Current: 2 drives per node
- Maximum: 4 drives per node (check motherboard specs)
- Expansion: +6TB raw (+2TB usable)

### Option 2: Replace with Larger Drives
- Current: 1TB drives
- Upgrade to: 2TB or 4TB drives
- Process: One drive at a time using OSD replacement procedure

### Option 3: Add More Nodes
- Current: 3 nodes
- Add: 3 more nodes for 2x capacity
- Consideration: Increases replication overhead

## Capacity Optimization

### 1. Enable Compression (Already Active)
```bash
# Verify compression is enabled
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd pool get replicapool compression_mode
```

Compression ratios:
- Logs: 5-10x compression typical
- Databases: 2-3x compression typical
- Already compressed data: No benefit

### 2. Adjust Replication
**WARNING**: Reduces data durability

Current: 3 replicas (can survive 2 failures)
Options:
- 2 replicas: 50% more capacity, survive 1 failure
- Erasure coding: More capacity, higher CPU usage

### 3. Data Lifecycle Management

Implement policies for:
- Log rotation (Airflow logs > 30 days)
- Backup retention
- Temporary data cleanup

Example log cleanup:
```bash
# Find and remove old logs
kubectl exec -n airflow deployment/airflow-scheduler -- find /opt/airflow/logs -type f -mtime +30 -delete
```

## Monitoring Dashboard

### Grafana Queries

1. **Capacity Trend**
   ```promql
   ceph_cluster_total_used_bytes / ceph_cluster_total_bytes * 100
   ```

2. **Growth Rate (GB/day)**
   ```promql
   rate(ceph_cluster_total_used_bytes[1d]) / 1024 / 1024 / 1024
   ```

3. **Days Until Full**
   ```promql
   (ceph_cluster_total_bytes - ceph_cluster_total_used_bytes) / rate(ceph_cluster_total_used_bytes[7d])
   ```

## Automation Scripts

### Capacity Report Script
```bash
#!/bin/bash
# capacity-report.sh

echo "=== Ceph Capacity Report ==="
echo "Date: $(date)"
echo ""

# Get capacity
kubectl -n storage exec deploy/rook-ceph-tools -- ceph df

echo ""
echo "=== Growth Projection ==="
# Add growth calculation here

echo ""
echo "=== Recommendations ==="
# Add threshold checks here
```

### Alerting Rules

Add to Prometheus:
```yaml
groups:
- name: capacity
  rules:
  - alert: CephCapacity80Percent
    expr: (ceph_cluster_total_used_bytes / ceph_cluster_total_bytes) > 0.8
    for: 10m
    annotations:
      summary: "Ceph cluster is 80% full"
      
  - alert: HighGrowthRate
    expr: rate(ceph_cluster_total_used_bytes[1d]) > 10737418240  # 10GB/day
    for: 1d
    annotations:
      summary: "Storage growing faster than 10GB/day"
```

## Pre-Expansion Checklist

Before adding capacity:

- [ ] Current usage documented
- [ ] Growth rate calculated
- [ ] Expansion option selected
- [ ] Hardware ordered/available
- [ ] Maintenance window scheduled
- [ ] Backup verified
- [ ] Expansion procedure reviewed

## Quick Reference

```bash
# Current capacity
ceph df

# Per-OSD usage
ceph osd df tree

# Pool usage
rados df

# Compression stats
ceph osd pool get replicapool compression_ratio

# Set warning thresholds
ceph config set global mon_osd_nearfull_ratio 0.80
ceph config set global mon_osd_full_ratio 0.90
```

## Capacity Planning Worksheet

| Metric | Current | 30 Days | 90 Days | 180 Days |
|--------|---------|---------|---------|----------|
| Used | 116Gi | ___ Gi | ___ Gi | ___ Gi |
| Available | 1809Gi | ___ Gi | ___ Gi | ___ Gi |
| Growth Rate | ___Gi/day | | | |
| Days to 80% | ___ | | | |

Update monthly to track trends.