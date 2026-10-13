# Longhorn/Flux memory reservations and exec target parsing

Approved scope: memory requests for Longhorn and Flux, repair of the safety
parser's container-command flag handling, staged rollout, and health checks.
Limits, replica counts, CPU requests, and Longhorn CPU reservation settings
remain unchanged.

## Requests and ownership

| Component | Memory request per pod | Owner |
|---|---:|---|
| Longhorn manager, 3 pods | 3Gi | Longhorn HelmRelease |
| Longhorn v1 instance manager, 3 pods | 1536Mi | Native admission policy in longhorn-config |
| Flux operator | 512Mi | Flux operator HelmRelease |
| Source and kustomize controllers | 512Mi each | FluxInstance patches |
| Helm controller | 256Mi | FluxInstance patches |
| Image automation, image reflector, notification controllers | 128Mi each | FluxInstance patches |

Seven-day peaks were 1014Mi for instance managers and up to 2217Mi working set
for Longhorn managers after filesystem scans. Flux peaks were 376Mi operator,
345Mi source, 378Mi kustomize, 187Mi helm, and 94–107Mi for the smaller
controllers. Requests include headroom; existing limits and CPU remain intact.
Total regular-container requests changed from **13.391 cores / 32.609375Gi**
to **13.391 cores / 47.796875Gi**. This improves scheduling accounting and
is not a claim that workloads consume an additional 15.1875Gi of RAM.

Longhorn 1.12.1's chart supports `longhornManager.resources`, but its v1
instance-manager controller only assigns CPU reservations and exposes no
memory-request setting or CR field. The built-in Kubernetes 1.36
MutatingAdmissionPolicy avoids an additional controller and namespace-wide
defaults. It adds only the memory request for single-container pods in storage
with v1 instance-manager labels and a controlling Longhorn InstanceManager
owner. CPU and limits are not patched. It applies on Pod CREATE and pods/resize
UPDATE, so replacements and request resizes retain the Git-defined request.
Ordinary Pod metadata/status updates do not mutate resources. The policy excludes v2 and different pod
shapes; revisit it when upgrading Longhorn's generated pod layout.

Existing instance-manager pods were resized through the Kubernetes resize
subresource, serially on k8s-1, k8s-2, k8s-3. Kubelet running allocations were
verified at each step. All three retained their pod UID, container ID, restart
count, **2280m CPU request**, and existing limits. No instance-manager process
restart or node reboot was required.

## Parser repair

Target option extraction and positional classification now stop at the CLI
`--` delimiter. The full original argument list remains available to other
policy checks. `kubectl exec` remains classified as a guarded cluster mutation:
container-command arguments cannot replace the outer Kubernetes context,
kubeconfig, server, or cluster. Wrong outer targets still fail validation, and
another shell command after a separator is classified separately.

The previously rejected targeted `du -sk /vector-data-dir` read now succeeds.
New tests cover child flags, outer target overrides, and a subsequent shell
mutation. Both Claude and Codex use this shared target contract.

## Stages and observed transitions

1. Parser repair `41509aed` — regression suite and real targeted filesystem read.
2. Flux operator `31523060`, then controllers `50c6b1bd` — each stage Ready,
   reconciliation and all targets recovered before continuing.
3. Longhorn manager request `64dc3008` — the chart's existing 100% unavailable
   rollout started managers together. Startup concurrently initialized shared
   settings and hit resource-version conflicts on `default-replica-count`.
   Managers settled after 1–3 retries; volumes and instance managers stayed
   healthy. Restart counts then remained stable.
4. Manager rollout repair `6fc2104c` — Helm post-renderer sets maxUnavailable
   to 1. Applied without changing pod templates or restarting settled managers.
5. Instance-manager policy `9b8042fe` — applied via Flux. Server-side dry runs
   confirmed memory-only mutation for an owned v1 pod and no mutation for
   wrong-component, v2, unowned, and multi-container fixtures. No diagnostic
   pods were created. Existing pods resized individually, with health checks
   between nodes.

## Verification and recovery

- All **357 repository contract tests** pass; Longhorn chart rendered and the
  admission policy/binding passed server-side dry-run validation.
- All seven Flux workloads and three Longhorn managers have intended requests.
  Deployment/DaemonSet replicas, CPU requests, main and init-container limits
  match the captured pre-change baseline. Instance-manager resize checks also
  confirm unchanged running identities, CPU, and limits.
- Final runtime health: **3/3 nodes Ready, 16/16 Longhorn volumes healthy,
  54/54 Kustomizations Ready, 27/27 HelmReleases Ready, 72/72 scrape targets UP**.
  Talos/etcd checks pass, Harbor components report healthy, and Loki is ready.
- Rollback: revert the relevant Flux stage. For instance managers, remove the
  binding/policy through Git first, then restore memory requests through the
  resize subresource serially if needed; an active policy enforces its request.
  Preserve CPU, limits, and health gates. No data deletion occurred.

## Separate existing issue

The default Longhorn BackupTarget has existed since April 16 and references
`storage/longhorn-backup-credentials`, which is missing. Manager logs repeatedly
report backup-client initialization failures even though the BackupTarget's
cached availability condition says available. Confirmed absence using Secret
metadata inspection only; no Secret values were read. This is separate from
healthy volume I/O and the manager startup conflict. Repair the backup target
or its credential delivery through the backup/credential workflow before
relying on external Longhorn backups. No credential changes were made here.
