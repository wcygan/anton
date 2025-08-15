# Ceph PG Optimization Guide

## Overview

This guide documents how to resolve "too many PGs per OSD" warnings in Ceph and optimize PG distribution.

## Problem Description

Ceph has a limit on the number of Placement Groups (PGs) per OSD. The default limit is 250 PGs per OSD. When this limit is exceeded, you'll see:

```
HEALTH_WARN too many PGs per OSD (284 > max 250)
```

## Root Causes

1. **Too many pools** - Each pool has its own PGs
2. **PG counts too high** - Pools with excessive PGs for their data size
3. **Orphaned pools** - Old object store pools that are no longer in use
4. **Autoscaler overshooting** - PG autoscaler creating too many PGs

## Solution Applied (June 11, 2025)

### 1. Reduced PGs for Large Pools

```bash
# Reduced erasure-coded pool from 256 to 64 PGs
kubectl -n storage exec deploy/rook-ceph-tools -- \
  ceph osd pool set ceph-objectstore.rgw.buckets.data pg_num 64

kubectl -n storage exec deploy/rook-ceph-tools -- \
  ceph osd pool set ceph-objectstore.rgw.buckets.data pgp_num 64
```

### 2. Set PG Limits to Prevent Autoscaler Issues

```bash
# Set max PGs for pools to prevent autoscaler from increasing
for pool in ceph-objectstore.rgw.buckets.data replicapool \
            ceph-filesystem-data0 storage.rgw.buckets.data; do
  kubectl -n storage exec deploy/rook-ceph-tools -- \
    ceph osd pool set $pool pg_num_max 64
done
```

### 3. Reduced PGs for Unused Pools

```bash
# Reduced default.rgw pools from 32 to 8 PGs each
for pool in default.rgw.log default.rgw.control default.rgw.meta; do
  kubectl -n storage exec deploy/rook-ceph-tools -- \
    ceph osd pool set $pool pg_num 8
  kubectl -n storage exec deploy/rook-ceph-tools -- \
    ceph osd pool set $pool pgp_num 8
done
```

### 4. Temporary Mon Configuration

```bash
# Temporarily increased PG per OSD limit to allow operations
kubectl -n storage exec deploy/rook-ceph-tools -- \
  ceph tell 'mon.*' injectargs --mon_max_pg_per_osd=260
```

## Results

- Reduced total PGs from 569 to 427
- PGs per OSD reduced from 284 to ~213 (under 250 limit)
- Cluster health restored to HEALTH_OK

## Monitoring PG Distribution

### Check Current PG Status
```bash
kubectl -n storage exec deploy/rook-ceph-tools -- ceph pg stat
```

### View PG Distribution by Pool
```bash
kubectl -n storage exec deploy/rook-ceph-tools -- \
  ceph osd pool autoscale-status
```

### Check PGs per OSD
```bash
kubectl -n storage exec deploy/rook-ceph-tools -- \
  ceph osd df tree | grep -E "osd\.[0-9]+" | awk '{print $1, $10}'
```

## Best Practices

1. **Set pg_num_max** - Always set a reasonable pg_num_max for pools to prevent autoscaler issues
2. **Monitor pool usage** - Regularly check for unused or underutilized pools
3. **Clean up orphaned pools** - Remove pools from old object stores or deployments
4. **Right-size PGs** - Use Ceph's PG calculator based on:
   - Number of OSDs
   - Expected data size
   - Replication factor

## PG Calculation Formula

```
Total PGs = (Target PGs per OSD × Number of OSDs × Data Percentage) / Pool Size
```

For our 6-OSD cluster:
- Target: 100-200 PGs per OSD
- Safe total: 600-1200 PGs across all pools
- Current: 427 PGs (well within safe range)

## Future Considerations

1. **Pool Cleanup** - Consider removing orphaned object store pools:
   - `ceph-objectstore.rgw.*` pools (if not in use)
   - `default.rgw.*` pools (if not in use)

2. **PG Autoscaler Tuning** - Configure autoscaler with appropriate bias:
   ```bash
   ceph osd pool set <pool> pg_autoscale_bias <value>
   ```

3. **Mon Configuration** - Make PG per OSD limit permanent in Rook config:
   ```yaml
   configOverride: |
     [mon]
     mon_max_pg_per_osd = 300
   ```