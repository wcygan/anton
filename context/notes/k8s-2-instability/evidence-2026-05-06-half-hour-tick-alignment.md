# Evidence: silent-reboot timestamps cluster after `*/30 * * * *` cron-tick boundaries

**Date:** 2026-05-06 (loop iteration #1, opus 4.7)
**Context:** Plan 0013 Phase 2 is open-ended for retrospective angles. This is a clock-time-correlation pass that does not appear in the prior investigation record; surfacing as a candidate worth disproving rather than a claimed cause.

## Observation

Of 11 silent-reboot timestamps recorded across plan 0007, 0009, and 0013 (R0–R8 on k8s-2, plus 2026-05-05 19:07Z on k8s-3 and 2026-05-05 ~19:33Z on k8s-1), **7 fall within +7 minutes after a `*/30 * * * *` tick boundary** (i.e., within :00:00–:07:00 or :30:00–:37:00 of any hour).

| Event | Timestamp UTC | Δ from nearest :00/:30 tick |
|---|---|---|
| R7  | 2026-04-21 20:34Z | **+4 min** |
| R0  | 2026-04-23 20:47Z | +17 min |
| R1  | 2026-04-25 19:32Z | **+2 min** |
| R2  | 2026-04-25 21:04Z | **+4 min** |
| R3  | 2026-04-27 04:56Z | -4 min |
| R4  | 2026-04-27 21:42Z | +12 min |
| R5  | 2026-04-28 04:39Z | +9 min |
| R6  | 2026-04-28 10:37Z | +7 min |
| R8  | 2026-04-30 02:32Z | **+2 min** |
| k8s-3 | 2026-05-05 19:07Z | **+7 min** (after 19:00 tick) |
| k8s-1 | 2026-05-05 ~19:33Z | **+3 min** (after 19:30 tick) |

**The 2026-05-05 cross-node pair is the most striking part of the signal.** Both reboots land in the post-tick window of *consecutive* `*/30` boundaries — k8s-3 at +7 min after 19:00, k8s-1 at +3 min after 19:30. Under the "cascade triggered by k8s-3's failure" framing in plan 0013 Phase 2, the gap is the cascade propagation time. Under this alignment-based framing, the gap is one cron period and each event is independently triggered by the same recurring tick affecting a different node.

## Statistical strength

Weak in isolation. Under uniform distribution, the probability of any single timestamp landing in a `+0..+7` window of a `*/30` tick is `14/30 ≈ 47%`. Binomial probability of ≥7 hits out of 11 is **~18%** — not significant. The signal is the 2026-05-05 *pair* of consecutive-tick alignments, not the aggregate count.

This is the kind of pattern that is worth testing cheaply (move the trigger, see if the alignment moves with it) but not worth building a fix around without confirmation.

## What runs at `*/30` cluster-wide

The discoverable in-cluster CronJob that exactly hits this schedule is `kube-system/pod-gc`:

```
NAMESPACE     NAME     SCHEDULE       LAST SCHEDULE
kube-system   pod-gc   */30 * * * *   12m
```

Manifest at `kubernetes/apps/kube-system/pod-gc/app/cronjob.yaml`. Workload is a single `kubectl delete pod --all-namespaces --field-selector=status.phase=Failed --ignore-not-found=true`. Created via ADR 0014, deployed ~2026-04-18 (`AGE 18d` at observation time). All 11 reboots in the table above are in the post-deploy era.

**This is not the only thing that fires at `*/30` boundaries.** Anything else with `*/30` cadence (Prometheus rule eval at 30s/1m default with phase-aligned start, Longhorn replica health checks, kube-controller-manager periodic loops, etcd auto-compaction every 5 min on a phase-aligned start, kubelet image GC) lands on minute boundaries that include `:00` and `:30`. Pod-gc is a *marker* for the alignment, not necessarily the cause.

## Hypothesis

A recurring tick at `:00`/`:30` UTC stresses some subsystem within ~7 min, occasionally pushing one node over the silent-reboot threshold. Candidate stressors:

- `pod-gc` apiserver LIST `pods` cluster-wide. Plan 0009 found kube-apiserver memory grew +456 MiB WSS in the 16 min before the 2026-04-23 reboot; a recurring LIST is one mechanism that produces step changes in apiserver memory.
- `etcd` auto-compaction. If aligned to `*/30`, would produce a brief I/O spike on whichever node holds the leader. k8s-2 was leader on 2026-05-05 and *held* — but the compaction load propagates to followers via raft.
- Prometheus rule evaluation aligned to `*/30` — heavy `for: 30m` rule windows tick at `:00`/`:30`.
- Longhorn engine periodic checks — needs verification (no RecurringJobs were configured at observation time per `kubectl get recurringjob.longhorn.io -A` returning `No resources found`).

## Discriminating test (cheap, software-only, reversible)

**Move `pod-gc` off `*/30` to an arbitrary unaligned schedule (e.g. `13,43 * * * *` or `7,37 * * * *`) and watch whether the next silent-reboot still lands in the +0..+7 post-`*/30` window.**

- If the next reboot lands within +0..+7 of a `*/30` tick *but not* near `:13`/`:43`: pod-gc is *not* the trigger; some other `*/30`-aligned subsystem is. Look at Prometheus, etcd, controller-manager.
- If the next reboot lands near `:13`/`:43` (the new pod-gc tick): pod-gc *is* the trigger. Targeted fix is to lower its blast radius (paginate the LIST, scope to specific phases, or replace with a controller pattern).
- If the next reboot has no clock-time alignment: this hypothesis is dead. The 2026-05-05 pair was coincidence.

Edit point is a single line in `kubernetes/apps/kube-system/pod-gc/app/cronjob.yaml` (`schedule: '*/30 * * * *'` → `schedule: '13,43 * * * *'`). Reversible. Low risk — pod-gc is a janitor, not a critical-path workload. ADR 0014 should not need updating; it captures the *existence* of the CronJob, not its schedule.

## What this does not claim

- Not claiming `pod-gc` is the silent-reboot cause. The signal is alignment, not causation.
- Not claiming this displaces the cascade hypothesis from plan 0013 Phase 2. Both can be true (the cascade *is* a `*/30`-aligned trigger that propagates) or one can be true. The discriminating test above distinguishes.
- Not claiming the historical k8s-2-only reboots (R0–R8) are all on this mechanism. The clock-time signal is dominated by the 2026-05-05 pair; the R-series shows weak alignment that may be background noise.

## Cross-references

- Plan 0013 Phase 2 (open): cluster-wide silent-reboot localization — this evidence note is a candidate Phase 2 retrospective angle
- Plan 0013 Phase 3 cascade-trigger reproduction test — the test proposed here is **cheaper and complementary**: instead of triggering a controlled k8s-3 reboot, just move a known recurring tick and watch
- ADR 0014 — `pod-gc` deployment decision; relevant if this hypothesis survives its first test
- `evidence-2026-05-05-dual-silent-reboot.md` — the cross-node event that motivated this look
- `kubernetes/apps/kube-system/pod-gc/app/cronjob.yaml` — the file to edit if running the test
