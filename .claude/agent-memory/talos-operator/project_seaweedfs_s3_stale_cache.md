---
name: SeaweedFS S3 gateway stale volume cache on volume-server relocation
description: Historical stale-cache incident; use the current planned-downtime runbook and approved gateway recovery
type: project
---

Historical observation, not a version-independent diagnosis: SeaweedFS
`seaweedfs-s3` gateways retained stale volume locations after relocation.
Stock 4.48, stable peer DNS and native two-copy placement are now deployed.
Use `docs/docs/runbooks/seaweedfs-node-maintenance.md` and Plan 0028 for current
ownership, writer fencing and recovery. This memory does not authorize a restart.

**Why:** Observed 2026-04-23 during the plan 0006 controlled-reboot acceptance test. When `seaweedfs-volume-1` (Longhorn PVC, data intact) rescheduled from k8s-3 to k8s-2 during drain and re-registered with a fresh UUID, the master topology correctly resolved volume 21 to its new location (confirmed via `/dir/lookup?volumeId=21`), but `seaweedfs-s3` pods kept returning `volume id 21 not found` / `s3aws: unexpected EOF` for 5+ minutes. This manifested as Harbor anonymous-pull returning HTTP 500 from `/v2/library/.../manifests/...`.

**How to apply:** Compare current topology, gateway logs and authenticated reads
of a previously readable object. A 500 alone does not identify cache staleness.
If an approved maintenance fence stops S3, restore fresh gateways after backend
recovery using the current runbook. Any separate gateway restart needs exact-target
approval and consumer checks; do not restart first as a diagnostic shortcut.

Diagnostic: compare bounded gateway logs with master topology and the affected
volume server's inventory. A disagreement supports a stale-location hypothesis;
verify actual bytes before ruling out missing data.

Do not add an automatic post-reboot restart hook from this historical incident.
Preserve its evidence if investigating an upstream cache fault.
