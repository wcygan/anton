# Harbor maintenance exercise — 2026-10-19

## Outcome

The one-node exercise did not pass its maintenance acceptance check. The
`k8s-2` drain exited with a proxy transport error, and the fresh authenticated
pull started during eviction exceeded its 120-second deadline. A fresh pull
after recovery succeeded. Two nginx endpoints were observed before and after
the target pod's eviction; this did not establish continuity of the blob path.

The operator approved a temporary private fixture, project-scoped pull-only
robot and Secret, three bounded pull Jobs on `k8s-3`, the drain with temporary
`emptyDir` deletion, recovery and exact cleanup. All test resources were
removed, and the original source image was retained.

## Identity and method

- Public applied revision: `7236e480e102667a19fa84767269d1e6533cfec5`.
- Harbor 2.15.2, chart 1.19.2; nginx Deployment generation 5, two replicas,
  chart-owned PDB `minAvailable: 1` with one allowed disruption at preflight.
- Three Ready and schedulable nodes; Talos/etcd preflight passed at 20:43 UTC.
  All 18 Longhorn volumes were healthy, with 36 running replicas.
- Source fixture: `library/storage-vxlan` at
  `sha256:4963bcf50365220415a02eece7a32c42466b7ead21e36e47028bf02cc7cbcd81`,
  9,200,696 bytes. Both existing Harbor projects were public, so a temporary
  private copy was required for a meaningful authentication check.
- The helper image was Crane pinned at
  `sha256:dfb14543fc9d2b6231e50af38bb6631f60b21e5f93489c18b1f92f1f23e712b1`.
  Each Job had a fresh `emptyDir`, OCI destination and layer cache; credentials
  were mounted read-only as `config.json`. Anonymous access had to fail with
  an authentication denial before the authenticated pull could run. Each
  successful pull verified the requested manifest and all four OCI blob hashes.
  The helper image's kubelet cache was independent of the image-data cache.
- Jobs had no retries, a 120-second deadline, no API token, a non-root user,
  read-only root filesystem and bounded resources. Admin credentials remained
  outside the cluster; the robot had repository-pull permission only in the
  temporary project, with a one-day expiry and explicit deletion after use.

## UTC evidence

| Check or transition | Observed result |
| --- | --- |
| Baseline Job created 20:43:49 | Anonymous denied; two compressed layers absent from cache and fetched; four blob hashes verified at 20:43:54; Job Complete at 20:43:56. |
| Cordon 20:44:30; drain started 20:44:33 | `k8s-2` Ready but unschedulable. PDBs enforced; no bypass or force. |
| Nginx eviction | Original `k8s-2` pod removed; replacement Ready on `k8s-3`, alongside the Ready `k8s-1` pod by 20:44:58. |
| During Job created 20:45:03 | Anonymous denied at 20:45:05; authenticated cold layer fetch stalled; `DeadlineExceeded` at 20:47:03. |
| Drain exit | Exit 1 after a connection reset through the Kubernetes operator proxy during eviction of one remaining proxy pod. The drain did not complete; no retry was issued. |
| Uncordon 20:45:28 | Drain process had exited before scheduling was restored. No node reboot was performed. |
| Dependency recovery by 20:47:09 | CNPG 3/3 Ready, SeaweedFS masters 3/3, filers 2/2 and volumes 3/3 Ready; 18 healthy attached Longhorn volumes and 36 running replicas. A second observer read at 20:47:45 confirmed this state. |
| Post-recovery Job created 20:47:22 | Anonymous denied; both layers absent from fresh cache and fetched; four blob hashes verified at 20:47:49; Job Complete at 20:47:51. |
| Initial Harbor/Flux recovery snapshot 20:47:52 | Two Ready nginx endpoints on distinct nodes, healthy storage and all Flux objects Ready. One privately managed workload remained below desired replicas due to admission; see additional recovery. |
| Complete recovery snapshot 21:21:18 | All three nodes Ready/schedulable; 72/72 Deployments and StatefulSets at desired readiness, 86/86 reconcilers Ready, 18 healthy Longhorn volumes and 36 running replicas. Both application HTTP/TLS checks passed again. |

The maintenance command, executed from the canonical checkout, was:

```sh
mise exec -- kubectl drain k8s-2 --ignore-daemonsets --delete-emptydir-data --timeout=10m
```

`emptyDir` contents were explicitly disposable for this exercise; PVCs were
retained. Longhorn's instance-manager PDB initially blocked eviction and then
allowed it as engines moved. This was an effective dynamic guard, not a reason
to bypass the PDB. Detached volumes, replica rebuilding and anti-affinity
constraints occurred during recovery and were observed until they cleared.

## Supported failure path

The old SeaweedFS volume-server address was removed at 20:44:40. The replacement
registered at 20:45:46 with a different Pod IP. S3 continued attempting reads
from the removed address, with repeated TCP timeouts after the replacement
was registered and healthy. At 20:47:48 S3 logged cache invalidation and a retry
with one new location; the post-recovery cold pull completed immediately after.
This connects the stalled blob reads to a stale volume-address cache. Harbor's
health API reported all seven components healthy while the cold pull was
stalled, so that API alone is insufficient for image-pull acceptance.

No S3 restart was needed: cache invalidation and data-path recovery occurred
naturally. The run does not establish a latency SLO, general node-loss survival,
or continuity for all stored data. It contains one fixed-image observation per
phase; the during-maintenance observation failed. The proxy connection reset
is the supported reason for the drain exit; its deeper cause remains unproven.

Version-matched SeaweedFS 4.40 source review identified retry waits inside an
HTTP read path whose individual attempts can stall. The wait budget does not
bound the complete read; cache invalidation follows the failed read. No
applicable S3/chart setting was identified to impose an end-to-end bound.
A contained upstream read-deadline and prompt-location-refresh change is a
candidate for a separate verification unit. Adding SeaweedFS replicas would
increase storage and I/O and would not itself establish a latency bound or
retrofit existing `000` volumes. See the [read/refresh path](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa/weed/filer/stream.go),
[HTTP client](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa/weed/util/http/client/http_client.go)
and [retry implementation](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa/weed/util/retry.go).

## Cleanup and additional recovery

Foreground deletion removed the three exact Jobs and their owned Pods before
the exact Secret was removed. The captured robot ID was revoked; the copied
artifact, repository and temporary private project were deleted after checking
their identities and complete contents. Follow-up reads confirmed absence of
test Jobs, Pods, Secret, robot and project, and presence of the original source
artifact. No garbage collection, global blob deletion or temporary listener
was used. Credential values were handled in memory and excluded from evidence.

One existing privately managed application's replacement was rejected by its
enforcing image-verification policy because its registry Docker `auth` field
could not be decoded as Base64. Its remaining replica stayed Ready.
The policy/source contract predates this exercise, and its last recorded ESO
sync was hours before the drain; the exact onset of the malformed value is
unknown. The operator separately approved source repair and ESO sync. After
resolving local 1Password CLI authentication, the malformed mirror's existing
username/password failed a registry preflight. The original application pull
Secret authenticated and read the exact expected manifest, and its Docker
configuration was restored into the 1Password mirror (item version 2 to 3).
The original Secret and credential permissions were preserved. Credential data
was handled only in memory during this approved repair and excluded from output
and evidence. ESO refreshed at 21:08:36 UTC and updated the verifier Secret.
The normal ReplicaSet retry subsequently admitted the replacement and restored
two Ready replicas with zero restarts by 21:21 UTC. The image-verification rule
remained enforcing, and metadata checks confirmed that the original application
pull Secret was unchanged. No workload restart, spec change or policy relaxation
was used. Private identities and repair evidence remain outside public Git.

Initial Python HTTP probes received an edge rejection. The private repository's
documented curl monitor contract subsequently passed both public URLs with HTTP
200, valid TLS and its existing response-time budget. The earlier client-method
failure is not attributed to the application or maintenance exercise.

## Next verification units

1. Resolve or bound the stale-address retry behavior before claiming image-pull
   continuity. Preserve the failed observation when evaluating any repair.
2. Investigate the proxy transport failure, then obtain a new maintenance
   window before repeating the drain. Do not infer a successful drain from the
   nginx replacement or successful post-recovery pull.
3. Retain a credential-source semantic preflight and exact-image access check
   before future verifier-source updates. ESO delivery readiness did not detect
   the original malformed registry configuration.

Raw sanitized per-phase evidence and the one-off execution harness are retained
in the maintenance worktree's ignored `.private/harbor-maintenance-20261019/`.
`drain-result.json` records the observed command disposition;
`master-address-transition.log` and `s3-address-cache.log` retain the bounded
service-log excerpts. The `cleanup-verified` ledger event records explicit
post-delete reads. The 20:54 UTC snapshot retained the private admission blocker;
`recovery-complete.json` records all workloads and reconcilers Ready at 21:21 UTC
after the approved repair. Private repair and HTTP artifacts retain the separate
source/delivery/workload/outcome checks without credential values.
This note is the durable public disposition; private application details are
not duplicated here.
