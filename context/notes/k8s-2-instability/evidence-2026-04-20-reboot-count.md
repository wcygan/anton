# 2026-04-20 — Reboot count (partial) + Prometheus blocker

Phase 1 step 1 of the synthesis action list. Intent: run `changes(node_boot_time_seconds{instance=~".*k8s.*"}[7d])` to settle the "9 vs 5 reboots" dispute.

**Outcome: partial. The exact-7d tiebreaker is blocked by the thing we are investigating.** Current-point-in-time boot epochs captured directly from node-exporter.

## Point-in-time boot epochs (captured 2026-04-20 18:28:50 UTC)

Pulled by `kubectl -n observability exec <node-exporter-pod> -- wget -qO- http://localhost:9100/metrics | grep '^node_boot_time_seconds'` against each DaemonSet pod.

| Node | Boot epoch | Last boot (UTC) | Uptime at capture |
|---|---|---|---|
| k8s-1 | 1776368971 | Thu 2026-04-16 19:49:31 | **94h 39m** (~3.94 d) |
| **k8s-2** | 1776707538 | **Mon 2026-04-20 17:52:18** | **36m** |
| k8s-3 | 1776361104 | Thu 2026-04-16 17:38:24 | **96h 50m** (~4.03 d) |

## Key findings

1. **k8s-2 rebooted ~36 minutes before this capture** (2026-04-20 ~17:52 UTC). This is a *new* reboot — cluster-triage's synthesis counted "10th observed" at 14:10 UTC earlier today, so this capture documents an **11th**.
2. **k8s-1 and k8s-3 uptimes confirm the problem statement:** both at 94–97 hours continuous since Thu 2026-04-16. The delta between them is 2h 11m — they booted within the same window but not simultaneously (not a cluster-wide event).
3. The **single-node nature of the instability is empirically confirmed** from within the cluster: only k8s-2 has rebooted in the last ~4 days.

## Why the 7d tiebreaker couldn't run

Prometheus's own pod is a zombie on k8s-2:

```
$ kubectl -n observability get pods -o wide
NAME                                                        READY   STATUS    RESTARTS   AGE   NODE
alertmanager-kube-prometheus-stack-alertmanager-0           0/2     Unknown   0          22h   k8s-2
kube-prometheus-stack-grafana-5d89f5c867-tcfk7              0/3     Unknown   0          21h   k8s-2
prometheus-kube-prometheus-stack-prometheus-0               0/2     Unknown   0          22h   k8s-2
```

Port-forward to `svc/kube-prometheus-stack-prometheus` fails with `pod not found`. No other Prometheus replica exists (single replica per StatefulSet).

This finding **independently corroborates cluster-triage's "zombies persist across reboots"** observation from the synthesis. The Prometheus/Alertmanager/Grafana zombies are 21–22 h old, meaning they have already survived at least one reboot of k8s-2 (the 14:10 UTC one and now the 17:52 UTC one). The StatefulSet / Deployment controllers have not created replacement pods because the Node object still reports the old pod as `Unknown` — kubelet on k8s-2 never successfully terminated them, so the controllers wait.

## Secondary data: talosctl boot resources

`talosctl -n 100.87.89.3 get bootedentries` returned an empty result set on k8s-2 — resource is registered but empty. `bootstatuses` is not a registered resource on this Talos version (v1.12.6). The node's boot history via talosctl requires a different path (machined log, `get machinestatus`, dmesg).

## Implications for the plan

- The single-data-point confirmation (k8s-2 just rebooted again) is sufficient to proceed. The "9 vs 5" devils-advocate objection about counting methodology **shifts in priority**: whether the historical count was 9 or 5, k8s-2 rebooted **yet again** during our investigation. The pattern is ongoing.
- **The Prometheus zombie IS the diagnostic signal for Phase 3 structural work** — cluster-triage's recommendations around anti-affinity for kube-prometheus-stack StatefulSets are now directly justified.
- Observability-advisor's `NodeRebootStorm` / `NodeRebootedRecently` alerts **would not have fired** because Prometheus has been non-functional for 22h. Shipping those alerts is still the right move, but deploying them requires Prometheus to be up first.

## Blocker to continuing Phase 1 cleanly

Without Prometheus, the exact 7d count remains open. Paths forward (need user decision):

1. **Force-delete zombie Prometheus pod** (`kubectl -n observability delete pod prometheus-kube-prometheus-stack-prometheus-0 --grace-period=0 --force`). This is a mutation, but narrowly scoped: the StatefulSet will reschedule onto k8s-1 or k8s-3, the TSDB PVC reattaches, and we regain 3–4 days of history (TSDB starts at ~3d20h ago, older data doesn't exist). Reverts on its own if the reschedule fails.
2. **Proceed without the 7d tiebreaker.** The point-in-time data + the fresh 36-minute-uptime reboot is already sufficient confirmation that the pattern is real and ongoing. Move to Phase 1 step 3 (watchdog inspection via talosctl) which is pure read-only.
3. **Alternate source for reboot history** — `talosctl -n k8s-2 logs machined` or dmesg buffer. Limited to current-boot dmesg (only 36 min of data) plus whatever machined retains on disk.

## Next step recommendation

Option 2 → go straight to talosctl watchdog inspection (Phase 1 step 3). The 7d count's value was to discriminate "real reboot" from "kubelet restart" — the 36-minute uptime on k8s-2 while k8s-1 and k8s-3 sit at 95h+ already proves that whatever is happening on k8s-2 is actual reboots, not kubelet flapping. Prometheus recovery can be addressed separately, not in the investigation path.
