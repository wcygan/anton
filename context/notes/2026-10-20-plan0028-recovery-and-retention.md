# Plan 0028 recovery, retention and cutover preparation — 2026-10-20

The remaining offline checks support the stock-software route. Retention, a
historical SeaweedFS archive restore and draft cutover configuration checks pass.
A fresh coordinated Harbor database plus S3 recovery point remains a production
gate; this preparation does not claim it exists. No production resource was
created, restarted, reconciled, scaled, modified or deleted.

## Current read-only evidence

The expected Tailscale operator context was verified without publishing its
literal tailnet name. Relevant Flux Kustomizations report source
`886fbd6a30efff5a8ac75befb25d1e40c8fef45b`, with normal unsuspended ownership.
SeaweedFS has 3 ready masters, 3 volumes, 2 filers and 2 S3 replicas. Harbor's
components and CNPG cluster are healthy; Loki is ready. These are bounded
readiness checks, not a new whole-cluster availability or data-integrity audit.

The live `harbor-postgres` Cluster has no `spec.backup` or backup plugin. No
CNPG Backup or ScheduledBackup resources were returned in `registries`.
Longhorn's default backup-target URL is empty; the only RecurringJob returned is
filesystem trim. In-cluster CSI snapshots exist and are Ready/Retain, but neither
that status nor healthy replicas establishes an independent database backup.
[Plan 0008](../plans/0008-harbor-postgres-backup-strategy.md) already tracks this
unimplemented database recovery requirement.

## Backup and restore verification

- Rehashed all eight retained encrypted archives: every byte still matches the
  previously verified archive identities, including all three master exports.
- Decrypted and restored the three volume and two filer archives into a private
  directory, checking every file against the captured manifests: **271 files,
  31,140,434,016 bytes**, all hashes matched.
- Started stock SeaweedFS 4.48 with those three restored volume directories,
  both restored filer stores, and a fresh isolated master. This tests topology
  reconstruction from preserved volume IDs; it does not test restoring the old
  Raft peer identities or production's full three-master operator lifecycle.
- The lab network was Docker `--internal`, with no published ports, production
  credentials, Kubernetes access or production endpoints. Its synthetic S3
  credential had Read/List permissions only. A disposable client verified the
  `harbor`, `loki` and `s3-read-probe` buckets and the exact 65,536-byte seeded
  probe object (SHA256 `de2f256064a0af797747c2b97505dc0b9f3df0de4f489eac731c23ae9ca9cc31`).

This is a successful restore from retained production storage archives, not just
an archive-format check. It remains an older checkpoint, not a fresh backup of
current writes; it contains no Harbor database dump and cannot prove full Harbor
project/user/auth or database/blob consistency. The current primary's name was
observed for preparing a future dump, but no database exec/dump was performed.
No full Harbor recovery-time objective is inferred from the local restore timing.

The existing key was consumed locally by age and never printed. Plaintext restore
files are retained under the private directory with a mode-0700 parent; none are
committed. All restored-service containers and its isolated network were removed.

## Stock Loki retention

Ran stock Loki 3.7.8 linux/amd64 against stock SeaweedFS 4.48 using the actual
policy selectors/priorities: default 24h, warning 336h, error/fatal 720h. Eleven
synthetic records represent fresh, 2-day, 15-day and 31-day ages across
info/unknown/debug/trace/warn/error/fatal and missing severity. Before enabling
retention, all eleven were readable through a cold Loki instance from S3.

After compaction and the delete sweep:

- **Seven expired records disappeared and their seven S3 chunk objects were deleted.**
- **Four expected survivors remained:** fresh info, 2-day warn, 15-day error and
  15-day fatal. Exact returned values matched the expected set.
- The S3 chunk-object count went from eleven to four, so the result does not rely
  solely on filtering records out of query results.

The test preserves retention periods and changes compactor scheduling to 5s and
the deletion delay to 5s. For synthetic history injection it disables rejection of
old samples and permits a 45-day query range. Production retains its 168h sample
rejection, 10-minute compactor schedule and 2-hour deletion delay. This proves
policy/deletion behavior on pre-aged data, not thirty days of wall-clock aging,
exact-boundary timing or the seven-day production observation gate.

Two setup attempts are retained: YAML parsed the schema date as a Python date
until explicitly serialized, and the initial 40-day query exceeded Loki's default
30d1h query-length limit. Neither is counted as a runtime regression. The final
run passed with the test-only query limit increased; production limits are unchanged.

## Loki rollback verification

Extended the retained local transition harness to test patched → stock → patched,
using a clean flush/exit and a new WAL directory at each image boundary. All
**512 final records** were readable after the rollback and another clean restart.
Hashes of both previous WAL trees remained unchanged. This uses synthetic data
and filesystem object storage to isolate image/WAL compatibility; the prior S3
rehearsal and this retention lab separately cover stock Loki with SeaweedFS.
The test does not authorize replaying patched counter history in stock or erase
the accepted stock crash-loss limitation. Its owned containers/network were removed.

## Prepared source changes and procedure

The [cutover/rollback runbook](../../docs/docs/runbooks/seaweedfs-stock-cutover.md)
keeps the existing service layout and uses the previously exercised controller-freeze procedure:

1. Stock SeaweedFS with temporary `OnDelete` updates on its three StatefulSets
   and S3 held at zero until stateful replacements pass. Replace one volume,
   filer and master at a time, followers before the current master leader.
2. Return to ordinary rolling updates and two S3 gateways after checks.
3. Stock Loki in a separate window, clean flush/exit and a fresh WAL directory;
   retain the old WAL. Rollback also uses a fresh directory after flushing.

The CRD exposes `statefulSetUpdateStrategy`, but exact upstream operator 1.0.39
source hardcodes RollingUpdate for master, volume and filer. The final procedure
therefore does not rely on that CR field: it freezes the existing operator owner,
uses temporary Kubernetes StatefulSet OnDelete holds and source-matching template
images, then restores captured strategies and normal reconciliation. The initial
CR-field-based draft was corrected before any publication or live use.
Sources: [master renderer](https://github.com/seaweedfs/seaweedfs-operator/blob/1.0.39/internal/controller/controller_master_statefulset.go),
[volume renderer](https://github.com/seaweedfs/seaweedfs-operator/blob/1.0.39/internal/controller/controller_volume_statefulset.go),
[filer renderer](https://github.com/seaweedfs/seaweedfs-operator/blob/1.0.39/internal/controller/controller_filer_statefulset.go).
Draft source patches apply cleanly to the observed revision. Both SeaweedFS
variants render locally through Kustomize to 16 objects and preserve the three
master/three volume/two filer replicas and PVC settings. The Loki draft renders through the cached exact chart 18.13.5 and verifies the
stock digest, new WAL directory, S3, flush-on-shutdown and existing retention/deletion
delay. All drafts need revalidation on the eventual execution revision. None of the drafts was applied to the checkout's deployment
files or published. An ADR 0044/status-only ADR 0043 supersession patch is prepared
for the already agreed downtime policy; refresh the next ADR number before publishing.

The backup capture inventory contains six snapshots, six sequential clone/read
pairs and two namespace isolation policies. **Do not apply its combined inventory
as a bundle.** The six PVCs total 508Gi nominal capacity; create one clone/reader at
a time after current capacity checks. Only clone readers mount data, read-only,
with no API token, no network, a pinned image and a deadline. Exact source PVC UIDs
and proposed object names are retained for the future approval packet.

## Remaining decisions and authority

- App upload default selected by operator delegation: assume uploads can be
  unique, require independent encrypted backup and verified restore before relying
  on the cluster as the only copy, and target daily backups with a usable recovery
  point no older than 24 hours. Restore may lose uploads since that point. This
  is an objective, not a durability guarantee; restore time still needs measurement.
  Until coverage is running and monitored, retain another independent copy or gate
  unique uploads. Per-app overrides can be recorded later; the default is settled.
- Backup destination: the simplest interim is the existing age-encrypted export
  method to an operator-controlled machine outside the cluster. The retained
  exports demonstrate that path; a second independent copy and a recurring cadence
  still need an owner and explicit coverage. Do not claim full-site recovery from
  an in-cluster snapshot or a single local disk.
- Live backup-only window: approve the exact write fences, clean stops, six new
  snapshots, one clone/reader at a time, master export and PostgreSQL 17 logical
  dump/roles/credential recovery scope. Proposed reservation is 60 minutes with
  a hard stop for new cutover work at minute 40; no measured production RTO or
  current approval is implied. Source image deployment is a later approval after
  that recovery point restores through actual Harbor core/registry checks.

There is no newly demonstrated stock-software defect blocking the selected route.
The blocking recovery condition is the missing fresh coordinated Harbor/S3 backup
and full Harbor restore proof. A production cutover, node-maintenance exercise and
seven-day observation remain unperformed. The draft runbook and patches make the
next actions reviewable without crossing those boundaries.

Private evidence: `.private/plan0028-remaining-gates-20261020/` contains the current
read-only captures, `archive-integrity.json`, `historical-restore-result.json`,
`historical-files-result.json`, `historical-restore-cleanup.json`,
`retention-result.json`, `loki-rollback/result.json`, fixture scripts and logs, `draft-validation.json`, `maintenance-holds-and-templates.json`, draft
source patches, `capture-targets.json` and split snapshot/isolation/reader manifests.

**Prove It Works** required actual restored-service reads and physical chunk
object deletion. **Laziness Protocol** kept the current topology and uses existing
encrypted exports and the prior controller-freeze procedure rather than adding a
backup platform or changing controllers.
