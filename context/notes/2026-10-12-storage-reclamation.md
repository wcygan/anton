# Storage reclamation and retention rollout

Executed October 12 evening CDT / October 13 UTC, 2026. User authorized deletion
of verified orphan data, filesystem trim, GitOps retention/automation changes,
and subsequently the narrow Talos image-cache rollout.

## Result

Allocated-block measurements across all six Longhorn disks fell from
**614.878 GiB to 169.890 GiB: 444.987 GiB reclaimed**. Measurements used `du -sk`
through the existing manager pods, not sparse-file apparent sizes.

- Removed 43 verified orphan directories, totaling 272.197 GiB. Each deletion
  rechecked its node/disk/path, cleanable/error conditions, absence of a current
  replica reference, and live-volume health. Each exact Orphan CR deletion was
  followed by confirmation that its corresponding directory was absent.
- Trimmed Talos then Prometheus via the supported Longhorn `trimFilesystem` API.
  Both had two RW replicas and no rebuilding. Snapshot removal stayed disabled.
- Prometheus compacted more blocks after the retention change. A second trim
  after compactions completed reclaimed those newly freed blocks. Net trim
  savings plus intervening writes were approximately 172.790 GiB.
- Zero orphan CRs remain; all 16 volumes are healthy. No PVCs, current replicas,
  or application data files were manually removed.

The original 272.5 GiB accounting gap was abandoned replicas: measured orphans
272.197 GiB, active replicas 342.681 GiB, and roughly 0.328 GiB filesystem
metadata/timing difference. Most orphan bytes were old Prometheus and Talos
replicas dating from September 27.

## Active policies

| System | Policy |
|---|---|
| Prometheus | 30 days, 35GB retention-size ceiling on the existing 50Gi claim |
| Talos informational/debug/trace logs | One completed UTC calendar day plus today |
| Talos warnings | 14 completed days plus today |
| Talos errors/fatal/panic/critical | 30 completed days plus today |
| Kernel, missing or unrecognized severity | 14 completed days plus today |
| Existing mixed Talos files | 30-day migration retention, preserving historical error evidence |
| Talos rotation | Daily at 03:17 UTC; filename dates; never delete today's open file |
| Longhorn trim | Sunday 04:30 UTC, concurrency one, only the two observability volumes |
| Longhorn orphan data | Native automatic replica-data cleanup after 604800 seconds (seven days) |
| Harbor artifacts | Daily 01:30 UTC; newest two pushed artifacts per repository, plus protected deployed digests and explicit rollback tag |
| Harbor garbage collection | Sunday 05:30 UTC, one worker, no untagged-artifact deletion |
| Node image cache | Kubelet imageMaximumGCAge=168h on all three nodes |

Talos uses `talos-level`, not `level`. Kernel events remain diagnostic even when
informational. The 33,000-record pre-change sample was 99.3% informational;
`machined` and `auditd` accounted for 92.7% of sampled bytes. These are bounded
samples, not an assertion that no historical error logs exist.

Longhorn maintenance owns only metadata on the two current volume identities,
with SSA Merge and pruning disabled. Their specs/lifecycle remain controller
owned. A replacement PVC requires updating the explicit selection.

Harbor's reconciler reads running pods and desired Deployments, StatefulSets,
DaemonSets, Jobs, and CronJobs, including scaled-to-zero workloads. It resolves
referenced Harbor digests, adds `in-use-<digest>` tags, and removes obsolete tags
from its own prefix. Failed inventory retrieval aborts before changing policies
or removing protections. The recognized registry host is explicitly configured;
new registry aliases must be added to the policy implementation before use.

Kubelet settings were patched one node at a time with `--mode=no-reboot`, applying
only machine.kubelet.extraConfig.imageMaximumGCAge. Each live configz reports
168h0m0s. Talos source and generated configs match. No node reboot was required.
Unused-image age starts again after a kubelet restart; cache savings are not
included in the current reclaimed-space total.

## Verification

- All 54 Flux Kustomizations and 27 HelmReleases Ready after rollout.
- All three Kubernetes nodes Ready; standard Talos health wrapper passed etcd,
  membership, apid, kubelet, boot sequence, and control-plane checks.
- All 16 Longhorn volumes healthy; weekly CronJob exists and selects exactly
  Prometheus and Talos. Orphan setting reports replica-data / 604800 seconds;
  remove-snapshots-during-filesystem-trim remains false.
- Prometheus API reports 30d / 35GiB, retains about 15.1 days of existing history,
  and ingests approximately 9,180 samples/sec. Longer history accumulates over
  time; expect disk use to grow toward the new retention target.
- Talos receiver Ready and writing routine, warning, and diagnostic files.
  Rotation job completed successfully. Error routing was verified with fixtures.
- Harbor health API reports every component healthy; Loki reports ready.
- Harbor API confirms both project retention policies and weekly GC schedule.
  GC dry-run execution 673 succeeded, estimating 8,742,758,336 bytes (8.14 GiB)
  of unreferenced blobs. No real Harbor GC ran in this session; its estimated
  saving is not included in the reclaimed-space figure.
- Contracts passed, including 352 Python tests. Targeted tests cover date
  boundaries, current-file protection, legacy-file preservation, newest-two
  policy, deployed digest protection, stale-tag cleanup, and failed inventory.
  Vector validated the Helm-rendered configuration and passed eight routing
  fixtures (info, warning, error, missing, kernel-info, UDP, empty, unrecognized).
- Temporary verification Jobs and the temporary Vector fixture file are gone.

## Issues encountered and remaining

The first Vector Helm upgrade failed before replacing the receiver because Helm
interpreted Vector's field template. Escaping the template fixed it; rendered
Helm output and Vector validation passed before the corrected rollout.

The API-server proxy could not reach one Longhorn manager endpoint. Trim was
completed using the manager's local pod address from its existing container.
Three Longhorn metrics targets remain down: historical Prometheus samples show
all three were down for the two-hour interval ending one hour before the final
health audit, before this cleanup. There are 71/74 healthy scrape targets.

A server-side Talos health check initiated through k8s-2 timed out reaching
another node's internal address. The rollout paused; the standard health wrapper
through the working endpoint then passed all cluster/etcd checks. Direct node
config checks and Longhorn health also passed before the third node was changed.
The internal reachability issue is unresolved and warrants a separate network
investigation; no network configuration was changed here.

## Recovery and ongoing operation

Deleted orphan data cannot be restored without an independent copy. Trim only
discarded filesystem-free blocks. Reverting Git policies stops future retention
changes but cannot restore expired logs or collected image blobs. Disable
orphan-resource-auto-deletion during an investigation if abandoned replicas need
to be preserved beyond seven days. Native cleanup does not provide a global
"pause whenever any volume is degraded" guard.

Retain two replicas and existing claim sizes. Do not interpret provisioned PVC
capacity as disk occupation or enable global snapshot removal to chase remaining
bytes. Initial cleanup is complete; ordinary writes and retained history will
change the measurements over time.
