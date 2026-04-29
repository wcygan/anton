# Stage 3.5 Long-Duration Stress Test — k8s-2 PASS

**Date:** 2026-04-29
**Node:** k8s-2 (192.168.1.99)
**Job:** `playground/k8s-2-stress-stage35-long`
**Result:** PASS — 4-hour stress-ng completed cleanly, zero reboots

## Test Parameters

| Parameter | Value |
|-----------|-------|
| Image | alpine:3.21 + stress-ng 0.18.07 |
| CPU stressors | 4 (matrixprod method) |
| VM stressors | 2 x 2 GiB (all methods) |
| Context-switch stressors | 4 |
| mmap stressors | 2 x 512 MiB |
| Duration | 4 hours (`--timeout 4h`) |
| activeDeadlineSeconds | 15600 (4h 20m hard cap) |
| backoffLimit | 0 |
| cpufreq governor | powersave (not overridden) |

## Timeline

| Event | Timestamp (UTC) |
|-------|-----------------|
| Job created | 2026-04-29T17:28:34Z |
| Pod started | 2026-04-29T17:28:34Z |
| Container started | 2026-04-29T17:28:35Z |
| stress-ng dispatched | 2026-04-29T17:28:35Z |
| stress-ng completed | 2026-04-29T21:28:36Z |
| Job succeeded | 2026-04-29T21:28:40Z |

## Stress-ng Results

```
stressor       bogo ops real time  usr time  sys time   bogo ops/s     bogo ops/s
                          (secs)    (secs)    (secs)   (real time) (usr+sys time)
cpu           103662166  14400.00  57455.57    102.17      7198.76        1801.01
vm            122041888  14400.03  28386.99    395.55      8475.11        4240.14
switch        23565415154  14400.00  17140.32  52597.70   1636487.15      337913.46
mmap             216891  14400.01   5375.14  22696.97        15.06           7.73

passed: 12: cpu (4) vm (2) switch (4) mmap (2)
failed: 0
metrics untrustworthy: 0
skipped: 0
successful run completed in 4 hours
```

## Stability Surveillance

- **Monitoring cadence:** every 5 minutes, 45 checks over ~3h 45m
- **Boot ID:** `3b6e1929-bad4-4333-9f42-3a5b88e73f5a` — unchanged on every check (matches baseline boot epoch `1777412482`)
- **Node condition:** `Ready=True` on every check
- **Container restarts:** 0 throughout
- **Node pressure conditions:** MemoryPressure=False, DiskPressure=False, PIDPressure=False on every check

## Interpretation

Stage 3.5 extends Stage 3 (90-min, 20 cpu + 8 vm stressors) with a different workload profile held for 4x longer duration:

- **Stage 3** (90 min): saturated all 20 logical cores + 8 GiB memory cycling — pure throughput stress
- **Stage 3.5** (4 hours): moderate multi-dimensional stress (CPU + VM + context-switch + mmap) sustained over 4 hours — targets cumulative/thermal effects

Both passed. Together they close the "sustained in-OS load pressure triggers the silent reboot" hypothesis for workloads up to 4 hours under `powersave` governor. The unfalsified subspace narrows further to:

1. **Firmware/POST DIMM training faults** — only reachable via boot-time memtest86+ or physical DIMM swap (Phase 5)
2. **`performance`-governor max-power thermal envelope** — diagnostically marginal; Stage 3 already pushed 20 cores for 90 min under `powersave`
3. **Multi-day cumulative-moderate-load triggers** — the regime where Stage A's 6 reboots happened over ~63h with ~10.5h mean inter-reboot interval; not reproducible via bounded stress tests
4. **Physical-layer faults requiring cold-boot stimulus** — DIMM swap, BIOS reflash

## Relationship to Other Stages

| Stage | Duration | Workload | Result |
|-------|----------|----------|--------|
| 1 | ~23 min | memtester 8 GiB | PASS |
| 2 | ~92 min | memtester 32 GiB (mlock'd) | PASS |
| 3 | ~90 min | stress-ng 20 cpu + 8 vm (1G each) | PASS |
| **3.5** | **4 hours** | **stress-ng 4 cpu + 2 vm (2G) + 4 switch + 2 mmap (512M)** | **PASS** |
