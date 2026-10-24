# SeaweedFS node maintenance

Use planned S3 downtime for node work. Shared SeaweedFS serves apps, Harbor and
Loki; native two-copy placement and Longhorn replicas remain, but uninterrupted
service during a node outage is not promised. ADR 0044 replaces that acceptance
requirement. The stock image transition is complete; Plan 0028 still tracks the
planned node exercise, seven-day observation and ongoing backup coverage. This
page does not authorize a drain or Talos change.

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
S3 cache freshness or authority to drain. It fails when a volume's copies
report different sizes: run `scripts/seaweedfs-readonly-repair.py plan <id>`
for each such volume. If every plan accepts the divergence, run `verify <id>`
for each, then rerun the audit with `--accept-size-divergence <ids>` (see
[Writable copies that disagree](health-alerts.md#writable-copies-that-disagree)). Historical migration and failed
continuity exercises remain in `https://github.com/wcygan/anton/blob/628e15ba1c9b40b2731240dcfb3a282f013319cc/context/plans/0027-improve-cluster-operational-outcomes.md`.
Do not rerun the retired one-off migration fixtures for routine maintenance.

Follow the [upgrade procedure's recovery-location and transfer-authority rule](../../upgrade-talos-or-k8s/SKILL.md#recovery-location-and-transfer-authority)
before selecting a capture destination. Require a tested independent recovery
point within each consumer's freshness contract, or record the operator's explicit
choice of cluster-only maintenance recovery and the unmet independent-recovery
contract. In-cluster snapshots do not satisfy that contract. Unique uploads are
not disposable; daily backup/freshness automation
is still a separate requirement. Retain independent originals until it operates.
Record baseline authenticated S3 bytes and a readable Harbor image digest before
fencing writers, so existing missing artifacts are not attributed to this window.

## Planned interruption

Use the writer-fence and ownership journal in the
[stock cutover runbook](stock-cutover.md): pause Harbor jobs/front door,
flush and cleanly stop Loki, and hold other app writers. The CRD rejects zero S3
replicas: keep the Seaweed CR at two, hold its operator owner, stop the operator,
then scale the S3 Deployment to zero using separately approved exact targets.
Stop provisioning/policy jobs during the window. Preserve CNPG, cache, all PVCs,
WAL directories and the current source of truth. Ordinary node work does not
require changing CR/backend images or adding admission exceptions; those were
specific to the one-time cutover.

Lessons from the 2026-10-23 storage window (slot raise and priority tiers):

- Stopping Loki pages: `LokiCanaryMissingLogs`, `LokiCanaryDeliveryStalled` and
  `LokiLogMetricsUnavailable` are critical. Create an Alertmanager silence for
  them, scoped to the window, before stopping Loki. Collectors buffered every
  log on disk; Loki showed no gap after it restarted.
- `seaweedfs-config` declares `suspend: false` on both storage CronJobs, so a
  reconcile of that Kustomization undoes an imperative CronJob suspension. When
  the window changes the Seaweed CR through Flux, suspend the CronJobs again
  after the apply, or schedule the window clear of minutes :17 and :23.
- Restarting a SeaweedFS component through the CR rolls masters, volume
  servers, filers and S3 gateways in parallel, one Pod per component at a time;
  it took about five minutes. Old volume Pods still log their last startup
  check, so judge integrity only from Pods created by the roll.

The kubelet's priority tiers stop Loki and Harbor before SeaweedFS, and
SeaweedFS before Longhorn, only on its own graceful shutdown ([Talos shutdown
order](../../../../docs/docs/guides/talos.md#shutdown-order)). The drain in
`talosctl upgrade`, `talosctl reboot --drain` and `talosctl shutdown` evicts
every pod at once, so keep this writer fence for planned work.

Maintain one named node using the matching Talos/node skill and its separately
approved commands. Preserve quorum and Longhorn preconditions; accepting S3
downtime does not waive node safety. Wait for the node and original storage
workloads to recover before touching another node. No automatic orphan deletion,
compaction, replica migration or storage-controller replacement is part of it.

After topology and all stateful roles are healthy, restore the operator and its
owners so it restores two fresh S3 gateways from the unchanged CR. Reconcile the
operator Kustomization before its dependent config Kustomization if needed.
Check seeded object bytes/ranges, the prior readable Harbor image and a scratch
push/pull, then resume Loki and verify stored chunks/new logs and queue recovery.
Record any log gap without claiming a maximum loss bound. Restore every captured
owner field and replica count exactly and remove only owned temporary resources.

Stop if previously readable data is missing, quorum is lost, a source PVC changes
identity or original storage degrades. Keep writers fenced and use the approved
recovery procedure. Image rollback preserves current data; restoring an older
backup needs a separate decision about writes that would be lost.
