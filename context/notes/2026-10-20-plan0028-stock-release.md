# Plan 0028 stock release and execution boundary — 2026-10-20

The source candidate on `codex/stock-storage-simplification` is based on deployed
`886fbd6a30efff5a8ac75befb25d1e40c8fef45b`. It keeps shared S3 for apps, Harbor and
Loki, existing claims/endpoints/credentials and native two-copy placement. This
record prepares the next live action; it does not claim production is stock.

## Concrete source changes

- Pin stock SeaweedFS 4.48 in the Seaweed CR and native-policy tool init container.
  Remove patch-only LevelDB `sync`; preserve its store/path and both filer PVCs.
  Explicitly disable the retired Iceberg listener with `-port.iceberg=0` because
  4.48 defaults it to 8181. No storage Service exposes that port and no active
  public/private repository consumer was found; old buckets/identities remain.
- Pin stock Loki 3.7.8, with a fresh `/var/loki/wal-stock-0028` directory. Keep WAL,
  shutdown flush, S3 schema/bucket, singleton PVC, limits and retention unchanged.
- ADR 0044 supersedes only ADR 0043's continuity contract. Completed native copy
  placement remains; the unperformed continuity drill is not called passed.
- Keep the small native fsync/001 prefix policy owner and real S3 read probe.
  These use supported upstream interfaces and do not need runtime forks.
- Replace manual OnDelete/template/eviction cutover work with the installed
  operator's normal RollingUpdate path while clients and S3 are fenced.
- Prepare removal of 37 build/fork-test/retired-migration files, including every
  one of the five tracked runtime `.patch` files. Promote this cleanup only after
  live stock verification. Retain exact rollback OCI archives and old WAL trees
  through observation; source rebuild tools are not needed for image rollback.
- Update the node runbook and legacy-named Seaweed skill to route current shared
  S3 operations correctly instead of requiring the retired lakehouse.

## Verification and limits

The initial unchanged-tooling contract suite passed 511 tests (one skipped).
The final candidate passes **507 tests, one skipped** after removing the four
build-only tests with their deleted builder. Skill validation and the Docusaurus
build pass. Exact logs are retained in `contracts-final.log` and `docs-build.log`. Kustomize and the
exact Loki chart 18.13.5 are rendered, not just YAML-parsed. The source diff keeps
all claims, replicas, affinity and endpoint settings except the named changes.

Operator tag 1.0.39, commit `8ba00153c593258784e7cf7294e8ba6bdc1a055d`, was tested
with the admitted live CR plus desired stock fields. The resulting three
StatefulSets preserve all fields except their main image; they use RollingUpdate
at partition zero. The S3 renderer honors replicas zero. This is a renderer test,
not an API-server or production rollout. The retired manual strategy override is
unnecessary when downtime and concurrent component rollouts are acceptable.

A proposed master readiness override failed this renderer check: the installed
CRD and implementation expose timing fields only, never the HTTP handler. That
candidate was removed; the three small Python Raft guards remain. A separate
isolated stock three-master runtime test returns HTTP 200 with all three and
with one follower absent, then 503 after quorum is lost. Its containers/network
were removed. This preserves quorum gating without patching the operator.

The earlier coordinated backup and full Harbor restore on stock SeaweedFS remain
valid evidence; see [the exact coverage and failures](2026-10-20-plan0028-backup-window.md).
Three selected catalogue manifests return 404 in current production and in the
lab; no pre-maintenance baseline dates their loss. Keep them recorded and
unmodified as a separate repair question. The rollout must preserve every
artifact readable at its fresh baseline; it does not repair existing data holes.

## Proposed exact live scope — approval required

One **60-minute reservation**, with no new image step after minute 40 and 20
minutes reserved for recovery. Verify stock SeaweedFS before the separate Loki
phase. If the budget cannot cover Loki, recover the original serving state and
schedule its own approved window; do not leave its owner suspended indefinitely.

| Exact owner/target | Temporary action and expected effect |
| --- | --- |
| `storage/plan0028-runtime-cache` DaemonSet + NetworkPolicy | Cache both exact stock and both rollback digests on k8s-1/2/3; no token, host/storage mounts or Pod network access. Verify every init exits zero and all three nodes are ready before any outage. Remove the two owned objects after checks. |
| `registries/harbor` Kustomization + HelmRelease | Suspend source/Helm ownership while Harbor replicas are held; restore original field presence/value. |
| `registries/harbor-nginx`, `harbor-jobservice`, `harbor-core`, `harbor-registry` Deployments | Drain/stop in that order; restore original replicas 2, 1, 2, 2 in reverse dependency order, nginx last. Preserve CNPG/cache/PVCs. |
| `observability/loki` Kustomization + HelmRelease + StatefulSet | Hold owners, flush and verify stored data, stop cleanly, then start stock with the new WAL path; preserve original PVC and both old/new WAL trees. Restore one replica and original owner settings. |
| `storage/seaweedfs-config` Kustomization | Hold source reconciliation while the CR has temporary S3-zero state. Resume against the exact reviewed release revision to restore final two-gateway source state. |
| `storage/seaweedfs-buckets-ensure`, `seaweedfs-durability-ensure` CronJobs | Suspend and wait for existing work to finish; restore original settings through source. |
| `Seaweed storage/seaweedfs` | UID/resource-version guarded S3 replicas zero, then the committed stock image/filer config/disabled Iceberg listener while still fenced. Operator rolls 3 masters, 3 volumes and 2 filers normally; preserve every claim. Restore S3 replicas two through Git. |
| Existing Harbor API and Loki/canary path | Loopback-only authenticated reads, one newly created scratch project/robot/image push/pull and cleanup limited to those recorded new IDs; query old stored chunks and fresh existing canary records. No existing artifact deletion. |
| Git `origin/main` | Promote only the reviewed runtime/decision commit after owner holds; verify its Flux source revision. Promote build-source removal only after live stock checks. Fail closed if main advanced; never force-push. |

The operator Deployment, HelmRelease and `storage/seaweedfs` Kustomization remain
running. No ordinary Pod deletion, StatefulSet strategy edits, namespace/bucket
removal, original PVC/snapshot/WAL deletion, credential rotation, Talos change,
node drain or destructive data restore is in this scope. A failed rollout keeps
writers fenced and uses the original image/configuration via the same owner.
A diagnosed controller rollback that needs a blocked Pod evicted requires a
fresh exact-target recovery decision rather than an unguarded delete loop.

The independent recovery fence is **2026-10-20 23:08:03 UTC**, with all six exports
and Harbor restore verified. It was approximately 3.3 hours old during this
preparation. Use it only while it remains within the delegated 24-hour freshness
contract and no active app requires a stricter point. Writes since that fence may
be lost if disaster recovery becomes necessary; ordinary image rollback retains
current PVC contents instead. Capture a fresh coordinated point first if this
one expires or a consumer requires it. Monitored daily backups are not running;
keep independent originals or unique-upload onboarding gated. Logs remain best
effort, including possible collector queue loss during the planned interruption.

## Current preflight and acceptance

The expected context hash and kube-system UID matched. Source revision remains
`886fbd6a`; 3 masters, 3 volumes, 2 filers and 2 gateways were Ready. All 18 original
Longhorn volumes were healthy. Native APIs reported 32 unique volumes, each with
two writable copies, 64 occupied slots and eight free slots. No active storage
Jobs were returned. Refresh identities, jobs, resource health and baseline bytes
immediately before mutation; these observations are not transferable approval.

Exact stock and rollback digests are in the
[runbook](../../docs/docs/runbooks/seaweedfs-stock-cutover.md). The Loki rollback
OCI manifest and every layer were verified offline against its production digest.
The Seaweed rollback Docker archive was recreated locally and its computed
manifest digest matches production. Live image-cache success on all three nodes
is still an execution gate, not inferred from a laptop cache.

Stop on changed PVC identity, lost quorum, degraded original storage, unclean
exit, failed pull, unexpected allocation, missing baseline bytes or a deadline.
Accept only source/applied image agreement, healthy topology and original PVCs,
Harbor health/login/old+new image verification, Loki stored/fresh reads, original
owner/replica settings, and cleanup of all owned temporary resources. Seven-day
stock observation and the real planned node exercise remain open after cutover.

Private evidence is in `.private/plan0028-simplification-20261020/` in the canonical
checkout: source/live captures, renders, operator fixture/log, native probe test,
rollback identities, retired file inventory and proposed cache manifest. Nothing
in that packet has been applied to the cluster during this preparation.

**Laziness Protocol** removes manual controller choreography and fork tooling.
**Prove It Works** caught the unsupported handler override and verified actual
quorum failure, renderer behavior and prior Harbor reads/writes.
**Outcome-Oriented Execution** keeps rollback binaries instead of carrying a
parallel source-build interface through the observation period.
