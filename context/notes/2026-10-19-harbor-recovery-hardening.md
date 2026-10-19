# Harbor recovery hardening — 2026-10-19

## Changes and verification boundaries

The earlier [maintenance exercise](2026-10-19-harbor-maintenance.md) failed:
the during-maintenance cold pull exceeded its deadline and the node drain
exited on a proxy reset. The operator authorized fixing both findings using
GPT-6 Luna high-effort agents in separate worktrees. Root retained ownership
of integration, live changes, cleanup and this record.

Two independently reviewed increments were merged:

| Increment | Benefit | Verification | Rollback |
| --- | --- | --- | --- |
| [PR 513](https://github.com/wcygan/anton/pull/513), `c040a67c` | Stable per-volume DNS replaces a Pod IP that becomes invalid after replacement. Explicit wildcard bind preserves startup without DNS dependence. | Pinned SeaweedFS 4.40 stream comparison, exact operator 1.0.39 generator/CRD checks, real master addresses and PVC identities. | Revert the CR change through GitOps; this can roll volume servers again and does not restore prior caches. Verify readiness and reads. |
| [PR 514](https://github.com/wcygan/anton/pull/514), `20842500` | The maintenance command restores and revalidates its proxy path before the bulk drain. | Seventeen command-boundary tests and the successful proxy-host drain below. | Revert the helper/Task/runbook commit. Stopping a partial drain leaves its target cordoned for inspection and the approved recovery/uncordon plan. |

The reproduction calls the actual `PrepareStreamContentWithThrottler` path at
SeaweedFS revision `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa`. Both in-flight
reads fail when the old listener is withdrawn. A subsequent request to the
departed literal address fails, while the unchanged hostname reconnects to the
replacement and returns exact bytes. Its injected resolver and sub-second
local timing do not establish CoreDNS behavior or a cluster latency SLO.

The installed operator is 1.0.39, chart 0.1.42. Its stable advertised name is
`$(POD_NAME).seaweedfs-volume-peer.storage`; `ipBind: 0.0.0.0` separately
controls binding. The removed CR extra argument had overridden that identity
with `$(POD_IP)`. That workaround originally avoided startup DNS failures;
explicit wildcard bind preserves the safeguard without changing the address
on every replacement. PVCs, volume IDs and replication remain unchanged.

The drain helper uses a single UID-preconditioned Eviction submission through
kubectl's raw API path. Tagged kubectl 1.35/client-go 0.35 source confirms its
opaque stdin request body is not replayed after a transport error or 429.
An ambiguous response triggers read-only observation. The helper requires a
Ready same-Deployment replacement off the cordoned target, rechecks active
context and cluster/node/owner UIDs, then invokes one normal drain within the
remaining overall deadline. PDB refusal and identity mismatch stop it.

Source-increment verification passed all 466 tests (one skipped), the public privacy
and other contract gates, the upstream address comparison and the production
documentation build. Remote checks passed for both PRs; Flux rendering was
appropriately skipped for the script/documentation-only second increment.
Concurrent main's Loki rollout record was preserved during integration.
After incorporating concurrent S3 observability changes through `1bf42c06`,
the combined suite passed 477 tests (one skipped) and the production docs
build passed again.

## Configuration rollout and migration

Normal Flux reconciliation applied the CR change after PR 513 merged at
21:42:47 UTC. Seaweed generation 17 and volume StatefulSet generation 5 became
fully current and Ready by 21:48:11. Each ordinal rolled in order; all three
PVC UIDs and volume-ID sets stayed the same, with zero container restarts.
The master HTTP status, read through the Kubernetes Service proxy, advertised
only stable ordinal DNS names. Both original S3 Pod UIDs remained unchanged.

The sparse 90-second readiness-probe period made readiness lag startup and
master registration. A terminating old pod's HTTP 503 event was matched by
UID and was not attributed to its replacement.

The first private-fixture copy exposed migration of already-cached addresses:
the request began at 21:49:01, the client timed out after 40 seconds, and the
nginx access log recorded 499. Harbor core recorded the synchronous copy's
terminal S3-backed 500 at 21:51:01; exact artifact reads remained 404.
S3 still dialed pre-change literal addresses even though master topology was
correct. It naturally invalidated the affected Harbor location at 21:51:44
and a Loki location at 21:52:00. The failed attempt is retained; it is not a
successful cold-pull observation. A reconciled copy attempt followed the
terminal result and observed partial cache refresh. It also exceeded the
client timeout; core recorded its terminal S3-backed 500 at 21:57:24.
Exact destination artifact reads remained 404. A bounded, per-pod census
then showed stale reads for several distinct volume IDs in both gateway
processes. At 21:55, both processes had observed stale locations for volume
IDs 26, 28 and 30; one also observed Harbor IDs 20 and 22. Only IDs 20 and 28
had recorded natural invalidation then. Counts describe the bounded log
window, not all cached entries. One refreshed location is insufficient to
complete the migration.
Version-matched source confirms there is no age-based location-cache TTL;
natural invalidation happens independently per gateway and volume. The operator
approved serial gateway replacement with Loki active, retaining a Ready S3
endpoint, plus the exact volume replacement and `k8s-3` drain with emptyDir
deletion. This explicitly approved the active-writer exception to the storage
maintenance guidance; retries/WAL are not an integrity guarantee.

Before the first guarded gateway Eviction could be submitted, concurrent
GitOps changes had already replaced both exact target UIDs. The identity
guard stopped before submitting a request. Root did not evict either S3 Pod.
Concurrent main added metrics/IAM configuration (`8197fe06`) and read-probe
sidecars (`7e1d0c09`), rolling both processes. The replacement pair was Ready
by 22:04:43 UTC; a later probe startup/configuration correction (`1bf42c06`)
finished another rollout at 22:10:58. These are separate changes, preserved
in integration and not credited to this maintenance operation.

Both failed copy attempts reached terminal backend errors before their exact
temporary project and staged repository were removed. Absence and retained
source artifact metadata were verified. That failed fixture had no robot,
Secret or pull Job. A new private fixture copied successfully at 22:04:04,
after the original gateway UIDs had disappeared but before the additional
probe-sidecar rollout completed. Its pull-only robot, Secret and Jobs have
a separate cleanup ledger. No garbage collection or source-image deletion
was used.

## Operational acceptance

Each pull uses a fresh Pod and emptyDir OCI destination, a project-scoped
pull-only robot and a digest-pinned helper image. Anonymous access must be
denied. An authenticated pull must fetch both uncached layers and verify
all four OCI blob SHA-256 values, the requested manifest digest and exactly
9,200,696 blob bytes. The extra warm-up request establishes the gateway
baseline after the concurrent rollout; it does not reuse a client cache.

| Request | Container execution (UTC) | Result |
| --- | --- | --- |
| Initial private-fixture pull | 22:04:39–22:04:41 | Passed anonymous denial, uncached layers, digest and byte checks. |
| Gateway baseline warm-up | 22:07:08–22:07:09 | Passed the same checks with a fresh client. |
| Fresh request after volume replacement | 22:09:48–22:09:49 | Passed the same checks; Job completed at 22:09:52 within its 30-second deadline. |
| Post-drain recovery pull | 22:16:35–22:16:37 | Passed the same checks; Job completed at 22:16:40 within its 30-second deadline. |

The approved UID-preconditioned Eviction of `storage/seaweedfs-volume-1`
was accepted at 22:07:32 UTC. Its Pod IP changed from `10.42.2.180` to
`10.42.2.241`; the replacement became Ready at 22:09:01. PVC UID
`44f30e6f-5840-459d-b697-35d13f3a60a7` and master-advertised address
`seaweedfs-volume-1.seaweedfs-volume-peer.storage:8444` remained unchanged.
The fresh pull began about 48 seconds after readiness; its short execution
does not measure time from volume readiness to successful recovery.
Read-only filer metadata maps the two pulled layer digests, `eaf99133768c…`
and `1e810a3886cb…`, to volume IDs 23 and 22 respectively. Master lookup
returns exactly one location for each: the stable volume-1 address above,
matching the topology census. The fixture therefore exercises data held by
the replaced server, rather than only data on an unaffected ordinal.

The final concurrent S3 ReplicaSet was created at 22:09:46, before this pull,
but its first Pod became Ready only at 22:10:02. The original two gateway
processes remained Ready until after Job completion; the first old-Pod
deletion was 22:10:32. Therefore only the unchanged gateway pair was service
eligible during the controlled replacement's verification request, inferred
from Pod readiness/rollout timestamps and the Service's exclusion of unready
addresses. An EndpointSlice snapshot at the request instant was not retained.
The result supports subsequent-request recovery without resetting those
gateways. It does not demonstrate completion of an interrupted request.

The approved `k8s-3` drill passed preflight with all 18 Longhorn volumes
healthy and all 36 replicas running. The node was cordoned at 22:13:07 UTC.
The helper submitted one exact proxy Eviction: old UID
`02446871-1298-4bf8-ab9e-41fda7a7d282` on `k8s-3` was replaced by UID
`22d4c3ed-fd49-4f80-b633-cc1a45ddf8e2` on `k8s-2`. The replacement's
Pod-to-ReplicaSet-to-Deployment owner chain passed checks against the expected
Deployment UID. Fresh context, cluster, node and owner checks
passed before the single bulk-drain invocation. That command respected
Kyverno and Longhorn PDB refusals and retried the refused pod evictions using
kubectl's normal behavior. There was no PDB bypass, force flag, management
context fallback or repeated bulk drain.

The helper exited zero at 22:14:19; a separate read confirmed zero active
evictable Pods on the target. Cluster/node identity was reverified and
uncordon confirmed at 22:14:21. The helper duration was about 72 seconds,
within its 600-second overall budget. Talos health subsequently confirmed
healthy, consistent etcd and Ready, schedulable nodes. Longhorn temporarily
degraded and Seaweed master/volume replicas awaited readiness during the
drain/recovery; drain exit alone is not full workload recovery.

At 22:16:38, every Deployment/StatefulSet had its desired Ready replicas,
all 18 Longhorn volumes were healthy, all 36 replicas were running and all
nodes were Ready/schedulable. All volume PVC UIDs were retained and the
master still advertised stable DNS. Harbor API reported all seven components
healthy. Loki retained its Pod UID and zero restarts; `/ready` succeeded,
its flush queue was zero, and its WAL disk-full counter stayed zero. Bounded
current-Pod logs since the drain had no warning/error lines. These checks
do not prove historical log completeness or data integrity.

Flux conditions are a separate recovery check: 15 Kustomizations still
reported the 22:14 admission failure/dependency chain through 22:17:51.
Separate read-only condition reads reported no endpoints for the ESO
validation webhook while it was rescheduling; that endpoint and webhook
were subsequently Ready. The affected source had not changed since the
failed reconciliation. The root Kustomization has no explicit retry interval
and a one-hour interval. Later reads showed seven Kustomizations still
NotReady at 22:20:54. Concurrent reconcile-request annotations were recorded
on `observability/kube-prometheus-stack` at 22:20:32 and
`storage/seaweedfs-config` at 22:21:19. Root did not submit those requests;
the partial recovery cannot all be attributed to ordinary retries. The
remaining conditions still require source/retry reconciliation readback.

At 22:17:15, all four exact test Jobs and their owned Pods plus the test
Secret were removed. The project-scoped robot was revoked and the exact
fixture artifact, repository and private project removed at 22:17:45.
Follow-up reads at 22:17:51 verified zero test Jobs/Pods, absent Secret,
robot and project, and the original source artifact's digest and size still
present. No garbage collection, PVC deletion, source-image deletion,
port-forward or unmanaged debug workload was used.

The engineering principles changed concrete choices: Fix Root Causes selected
stable advertised identity with a separate wildcard bind; Separate Before
Serializing Shared State gave each Luna worker its own branch/worktree;
Sequence Work into Verifiable Units split source fixes, rollout, replacement,
drain and cleanup into checked gates. Attack the Premise stopped repeated
fixture-copy retries in favor of a per-client/per-volume cache census.
Make Operations Idempotent selected identity-guarded ownership ledgers and
exact cleanup; Prove It Works required real cold-pull bytes and live owner,
PVC and readiness evidence instead of treating repository tests as runtime
acceptance.

Seaweed replication `000` still provides one copy per volume server. Access
to that server's data can be interrupted while it is absent. Stable identity
does not guarantee completion of an already interrupted read, zero downtime,
or survival of persistent data loss. The fresh-pull 30-second Job
deadline is a bounded acceptance budget for this fixture, not a general
service SLO.
