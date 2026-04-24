---
name: SeaweedFS S3 gateway stale volume cache on volume-server relocation
description: After a volume pod moves nodes (e.g. drain), seaweedfs-s3 keeps a stale "volume N not found" cache — rollout restart the deployment to resolve
type: project
---

SeaweedFS `seaweedfs-s3` gateway pods hold an in-process volume cache that does not refresh when a volume-server pod relocates to a new node/address.

**Why:** Observed 2026-04-23 during the plan 0006 controlled-reboot acceptance test. When `seaweedfs-volume-1` (Longhorn PVC, data intact) rescheduled from k8s-3 to k8s-2 during drain and re-registered with a fresh UUID, the master topology correctly resolved volume 21 to its new location (confirmed via `/dir/lookup?volumeId=21`), but `seaweedfs-s3` pods kept returning `volume id 21 not found` / `s3aws: unexpected EOF` for 5+ minutes. This manifested as Harbor anonymous-pull returning HTTP 500 from `/v2/library/.../manifests/...`.

**How to apply:** After any node reboot / drain / Longhorn relocation that moves a `seaweedfs-volume-N` pod to a different address, run `kubectl -n storage rollout restart deployment/seaweedfs-s3` before declaring S3-backed services healthy. Alternatively: probe `http://192.168.1.106/v2/library/busybox/manifests/smoke` (with a bearer token from `/service/token?service=harbor-registry&scope=repository:library/busybox:pull`) — if it returns 500 with DriverName=s3aws, restart seaweedfs-s3 first.

Diagnostic: check `kubectl -n storage logs -l app.kubernetes.io/component=s3 --tail=20 | grep 'volume.*not found'`. If the master topology (`/dir/status` or `/dir/lookup?volumeId=<N>`) disagrees with the S3 gateway's errors, it's the gateway's cache, not a real missing volume.

Not yet filed upstream. Consider adding a post-reboot hook that restarts seaweedfs-s3 whenever a seaweedfs-volume pod has changed nodes, or file a SeaweedFS issue for the gateway to re-resolve on lookup failure.
