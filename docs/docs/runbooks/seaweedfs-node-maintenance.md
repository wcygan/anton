---
title: SeaweedFS node maintenance
---

# SeaweedFS node maintenance

Use planned S3 downtime for node work. Shared SeaweedFS serves apps, Harbor and
Loki; native two-copy placement and Longhorn replicas remain, but uninterrupted
service during a node outage is not promised. ADR 0044 replaces that acceptance
requirement. Plan 0028 tracks the stock image transition and its still-unperformed
planned node exercise. This page does not authorize a drain or Talos change.

## Before the window

Verify current cluster identity, source revision, Pod/PVC ownership, Raft quorum,
Longhorn health, physical free bytes and logical slot capacity. Use the existing
placement audit with the identities captured in the operator's preflight:

```sh
mise exec -- python3 scripts/verify-seaweedfs-maintenance.py \
  --expected-kube-system-uid "$ANTON_KUBE_SYSTEM_UID" \
  --expected-seaweed-uid "$ANTON_SEAWEED_UID"
```

The audit is read-only. Matching copy counts/sizes do not prove matching bytes,
S3 cache freshness or authority to drain. Historical migration and failed
continuity exercises remain in `context/plans/0027-improve-cluster-operational-outcomes.md`.
Do not rerun the retired one-off migration fixtures for routine maintenance.

Require a tested independent recovery point within each consumer's freshness
contract. Unique uploads are not disposable; daily backup/freshness automation
is still a separate requirement. Retain independent originals until it operates.
Record baseline authenticated S3 bytes and a readable Harbor image digest before
fencing writers, so existing missing artifacts are not attributed to this window.

## Planned interruption

Use the writer-fence and ownership journal in the
[stock cutover runbook](./seaweedfs-stock-cutover.md): pause Harbor jobs/front door,
flush and cleanly stop Loki, hold other app writers and stop S3 through its CR.
Stop provisioning/policy jobs during the window. Preserve CNPG, cache, all PVCs,
WAL directories and the current source of truth.

Maintain one named node using the matching Talos/node skill and its separately
approved commands. Preserve quorum and Longhorn preconditions; accepting S3
downtime does not waive node safety. Wait for the node and original storage
workloads to recover before touching another node. No automatic orphan deletion,
compaction, replica migration or storage-controller replacement is part of it.

Restore two fresh S3 gateways after topology and all stateful roles are healthy.
Check seeded object bytes/ranges, the prior readable Harbor image and a scratch
push/pull, then resume Loki and verify stored chunks/new logs and queue recovery.
Record any log gap without claiming a maximum loss bound. Restore every captured
owner field and replica count exactly and remove only owned temporary resources.

Stop if previously readable data is missing, quorum is lost, a source PVC changes
identity or original storage degrades. Keep writers fenced and use the approved
recovery procedure. Image rollback preserves current data; restoring an older
backup needs a separate decision about writes that would be lost.
