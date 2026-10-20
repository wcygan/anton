# Plan 0028 backup-only maintenance — 2026-10-20

The operator approved a backup-only maintenance window of at most 60 minutes,
including coordinated snapshots, encrypted PostgreSQL/roles/credential capture,
sequential clone exports and an isolated full Harbor restore. Stock-software
cutover remains a separate decision. Preparation was committed as `b572c38b`.

## Production capture and recovery

The expected Kubernetes context and cluster UID were checked, and mutations were
bound to captured object UIDs and resource versions. Relevant Flux sources were
at `886fbd6a30efff5a8ac75befb25d1e40c8fef45b`. Existing automation was held while
Harbor writers and Loki were stopped; PostgreSQL stayed running. The registry
custom-format PostgreSQL 17 dump, global roles and required recovery credentials
and configuration were encrypted directly, without printing their contents.
SeaweedFS vacuum was disabled under its native lock, then S3, filers and volumes
were stopped serially. The eight Loki/S3/filer/volume processes exited with code
zero. Three master state exports were captured while masters remained running.

All six stopped-state CSI snapshots became Ready:

- `storage/p28-preflight-20261020-v0`, `-v1`, `-v2`
- `storage/p28-preflight-20261020-f0`, `-f1`
- `observability/p28-preflight-20261020-loki`

The original patched services and ownership were restored at **23:14:09 UTC**.
Original replica counts, template contents, suspension-field presence/value and
six source PVC UIDs matched the capture. All 18 original Longhorn volumes were
healthy. Harbor reported healthy; admin authentication and the original set of
three projects passed. Loki returned Ready. No image pin or production PVC was
replaced. These checks establish recovery of the checked service path, not an
exhaustive audit of every object or completeness of diagnostic logs.

There were three conservative interruption intervals, measured from the Harbor
front-door fence through restoration of all original owners:

| Attempt | Duration | Result |
| --- | --- | --- |
| First | 189 seconds | Watch invocation unsupported; automatic service recovery, no snapshots. |
| Second | 104 seconds | Historical Pod resource version expired from watch cache; automatic recovery, no snapshots. |
| Third | 511 seconds | Eight clean exits, coordinated capture and recovery passed. |

Total conservative interruption: **804 seconds (13 minutes 24 seconds)**. These
intervals overlap neither each other nor the later online export. The observer
was corrected to use `resourceVersion=0` and verify an initial ADDED event with
the expected Pod UID before stopping a workload. This corrects evidence capture;
it does not weaken the clean-exit requirement. The first two failures are harness
failures, not evidence of SeaweedFS or Loki corruption. Collector queues may have
lost logs during interruptions; no zero-log-loss claim is made.

The first Loki export reader failed its manifest read because root with all
capabilities dropped could not read UID-10001 files. The corrected reader runs as
Loki's UID/GID 10001 with the same read-only mount, deny-all networking and dropped
capabilities. No file was omitted and no source permissions were changed.

## Independent export and cleanup

All six archives passed decryption, every captured regular-file hash/size and
independent gzip CRC/end-of-stream validation: **414 files, 62,211,982,066 bytes**
uncompressed, **47,033,695,559 bytes** encrypted. The five SeaweedFS restore
archives contain 387 files and 62,179,536,985 bytes. Ciphertext SHA256 identities
and per-file manifests are retained privately. The master archives also passed
local decryption/archive checks. No original PVC was mounted by an export reader.

Final production checks and cleanup completed at **minute 53.42** of the approved
60-minute reservation. All temporary Jobs, Pods, clone PVCs and isolation policies
were absent; six Ready snapshots were retained intentionally. All 18 original
Longhorn volumes were healthy, source PVC UIDs and owner/template state matched,
Harbor health/admin/project checks passed again, and Loki was Ready. Offline lab
work can continue after this completed production window without further cluster
mutations.

## Harbor restore and discovered data gap

The first isolated restore used pinned stock SeaweedFS 4.48 and production-matched
Harbor 2.15.2 images in a Docker internal network with no published ports or
production route. All five data/metadata archives were freshly decrypted and
checked against every file hash. The seeded 65,536-byte S3 object matched exactly.
PostgreSQL database and roles restored without error; project, artifact, user and
robot table counts matched the coordinated dump. Harbor health, admin login,
portal and the three-project identity set passed.

The historical manifest selected first returned 404 / manifest unknown. A bounded
read-only check of current production found three such missing manifests before
finding a fourth with an exact matching digest. These are missing in current
production too, rather than solely in the restore lab. **Their status was not
baselined before maintenance, so the time/cause of loss is not established.** None
of those three digest strings appears in current `origin/main` Kubernetes or image
source files; this does not establish that no external consumer needs them. The
search stops at the first working manifest and is not a complete artifact audit.

The first lab jobservice also exited when started before core was listening;
Kubernetes normally restarts such a process, while this Docker fixture did not.
A local restart recovered it; the repeat fixture explicitly waits for core before
starting jobservice. This is a lab startup ordering correction, not a production
change. The second full restore from newly decrypted archives **passed** against pinned
stock SeaweedFS 4.48. It verified the live-readable historical artifact also exists
in the restored Harbor catalogue, its manifest/index digests and all **seven blobs
(68,298,243 bytes)**. A new private lab project and robot authorized a successful
blob/config/manifest push, exact readback and catalogue lookup. The original
project set, admin authentication, portal, healthy components and database counts
also passed. Raw table counts were project 6, artifact 34, harbor_user 2 and robot
3 before adding lab-only data; the API-visible project set contained three.

The repeat lab took **122.4 seconds** from fresh decryption through Harbor checks,
using cached images and the local machine; this is not a production RTO. Results
were available around minute 58.3 from the original window start. The first
failed historical pull remains failed; it is not relabeled as passing. This is
an application-stack restore with an exact known-image pull and new write proof,
not an exhaustive digest audit of every existing artifact. All lab containers and
the internal network were removed after checks; plaintext copies remain private.

## Limits and follow-up

A one-time encrypted copy on an operator machine is independent of the cluster,
but does not implement daily backups, monitored freshness or a second off-site
copy. Keep unique-upload onboarding gated or retain independent originals until
those protections operate. Restore can discard writes after the recovery point.
Historical job logs and transient Redis cache are not restored; the lab starts
fresh cache/job-log storage. Jobservice health passed, but replication, scanning,
retention/GC jobs and recovery of an in-flight background job were not exercised.
The lab reconstructs a fresh single master from preserved volume IDs; it does not
exercise a full three-master Raft identity restore, operator rollout or site loss.
A successful lab restore does not establish a full-site or production RTO.
Before cutover, explicitly record the disposition of the three currently missing
manifests (retain/rebuild if needed, or accept existing holes if obsolete). Their
absence is not a newly demonstrated stock-only regression and should not trigger
a new runtime fork. Refresh the checkpoint at the next image-change window and
account for later writes. Stock cutover, real node-maintenance exercise, recurring
backup implementation and seven-day observation are still unperformed.

**Prove It Works** requires actual Harbor login, database/catalog agreement and
old/new registry digest checks, beyond Ready snapshots. **Attack the Premise**
changed the watch from a historical object version to a verified current stream.
**Laziness Protocol** retains the existing topology and encrypted export method
without introducing another storage or backup controller.

Private evidence and fixtures remain under
`.private/plan0028-backup-20261020/`; sensitive data and decrypted restore files
are excluded from Git and protected by a mode-0700 parent.
