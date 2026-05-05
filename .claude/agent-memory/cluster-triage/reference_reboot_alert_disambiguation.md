---
name: NodeUnexpectedReboot vs actual reboot disambiguation
description: How to tell if a NodeUnexpectedReboot alert is a real reboot or a node-exporter time-series reset
type: reference
---

`NodeUnexpectedReboot` alert (PrometheusRule `observability/cluster-node-reboot`, added 2026-05-05 in commit `40bb66a6`) fires on `changes(node_boot_time_seconds{job="node-exporter"}[6h]) > 0`. This trips on **two distinct events**, and they look identical from the alert payload:

1. A real node reboot (kernel restart, new boot epoch).
2. A node-exporter time-series reset — e.g., the StatefulSet/DaemonSet hosting node-exporter being recreated, or scrape labels changing. From Prometheus's perspective, that's a fresh series with a "new" boot time.

Authoritative ground truth for "did this node actually reboot": `talosctl --talosconfig ./talos/clusterconfig/talosconfig -e <node> -n <node> read /proc/uptime`. Compare uptime to the alert fire time:
- uptime > (now - alert_fire_time) → node was already up before the alert; not a fresh reboot
- uptime ≈ (now - alert_fire_time) → genuine reboot at alert time

Also useful: `talosctl ... read /proc/sys/kernel/random/boot_id` to compare against any baseline boot_id the bastion-side watch loop has recorded.

**First instance of this confusion:** 2026-05-05T23:24Z alert for k8s-3 — fired because the Vector StatefulSet (which exposes a node-exporter sidecar) was recreated by commit `35533bdb` at 23:23Z. k8s-3 had actually only rebooted once that day (the 19:07Z silent reboot in the dual-reboot postmortem), and was at 4h 22m uptime when the alert fired.

**Side note:** the dual-silent-reboot postmortem records k8s-3's boot time as 19:33:54Z, but `/proc/uptime` says 19:07:13Z — the postmortem timestamp is from a later dmesg-replay anchor, not actual kernel start. When timeline-correlating reboots, prefer `/proc/uptime` over postmortem timeline cells.

**Resolved 2026-05-05 (same evening):** the rule expression was changed from `changes(node_boot_time_seconds[6h]) > 0` to `time() - node_boot_time_seconds < 1800` with `for: 1m` so series resets can no longer trigger it (a fresh node-exporter series reports the host's true boot epoch, not the container start time). The disambiguation steps above are kept for historical context — if the symptom recurs, look for a different root cause rather than re-checking node-exporter restart timing.
