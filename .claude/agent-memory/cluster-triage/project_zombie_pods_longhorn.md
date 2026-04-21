---
name: Zombie pods on k8s-2 after reboot
description: Longhorn, SeaweedFS, KPS pods stick in Unknown phase on k8s-2 for hours after a node reboot
type: project
---

After every k8s-2 reboot (observed 2026-04-20), many pods on k8s-2 stay in `Unknown` phase long after the node rejoins Ready. Observed survivors after k8s-2 came back ~50 min ago:

- `kube-system/spegel-8z2tb` (36h old, pre-dates the most recent reboot — so the zombie persisted across at least one boot)
- `storage/longhorn-csi-plugin-*`, `storage/longhorn-manager-*`, `storage/engine-image-ei-*`
- `storage/seaweedfs-{master,filer,volume,s3,operator}-*`
- `observability/alertmanager-*`, `observability/kube-prometheus-stack-grafana-*`, `observability/prometheus-*`

**Why:** dirty shutdown leaves pod objects the kubelet never got to terminate. Controllers replace them, but the old Pod objects aren't garbage-collected while the previous boot id still appears to have them. Node event log explicitly shows `Node k8s-2 is down: manager pod longhorn-manager-d64dk is not running` — Longhorn's node controller sees the stale Unknown pod and marks the node down, which is why `storage/longhorn-2` disk goes `Ready=False` / `Schedulable=False` after every reboot.

**How to apply:**
- When triaging after a k8s-2 reboot, expect a pile of Unknown-phase pods; check whether they're hanging for longer than ~15 min, because at that point Longhorn's disk health degrades and PVC attachments for Grafana/Prometheus fail.
- Grafana/Prometheus/Alertmanager on k8s-2 will stay Unknown until the Longhorn side recovers. This is a symptom, not a separate cause.
- Watch for `pod-gc-*` CronJob pods stuck in ContainerCreating on k8s-2 — can indicate the garbage collector itself is blocked.
