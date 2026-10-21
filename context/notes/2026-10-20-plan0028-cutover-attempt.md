# Plan 0028 cutover attempt and corrected execution boundary

The approved stock cutover began at **2026-10-21 02:38 UTC**. All four exact stock
and rollback images executed successfully on all three storage nodes. Fresh
baseline checks passed: 18 healthy Longhorn volumes, original bound PVCs,
32 native volumes / 64 writable copies, Harbor admin health and an existing
manifest with seven blob hashes (68,298,243 bytes), and 100 historical Loki canary
records read from stored chunks.

Execution stopped before image changes or Git promotion: the live Seaweed CRD
rejects `spec.s3.replicas: 0` (`minimum: 1`, required, default 1). The operator's
renderer accepts zero internally, but this cannot establish a production fence.
The earlier renderer test was insufficient; API-server admission must also pass.
The prior execution packet's zero-replica CR procedure is withdrawn.

The first Harbor stop also exposed stock registry exit code 2 on SIGTERM. This
was reproduced with the same unmodified `goharbor/registry-photon:v2.15.2` image
in an isolated filesystem-only container. It is recorded separately from the
zero-exit requirement for SeaweedFS and Loki. Harbor was restored before retrying
the fence. No runtime fork change is needed for that behavior.

## Corrected, bounded maintenance procedure

Keep the same reviewed source candidate and recovery point. Add only these
explicit temporary operations to the previously approved 60-minute scope:

1. Hold `storage/seaweedfs` Kustomization and
   `storage/seaweedfs-operator` HelmRelease; journal their original suspend fields.
   Set `storage/seaweedfs-operator` Deployment replicas from one to zero. Wait for
   its original Pod to terminate before changing any operator-owned object.
2. With Harbor and Loki stopped and both storage CronJobs held, scale the
   operator-owned `storage/seaweedfs-s3` Deployment from two to zero directly.
   Watch both original gateway Pods to zero-exit deletion. Leave the Seaweed CR
   at its valid two-gateway desired state.
3. Promote the reviewed runtime commit with all affected owners held. Apply the
   valid final stock image, filer config and disabled Iceberg listener to the
   Seaweed CR. Set `storage/seaweedfs-filer` ConfigMap `data.filer.toml` to that
   same source config. Change only the main-container image of StatefulSets
   `storage/seaweedfs-master`, `seaweedfs-volume` and `seaweedfs-filer` to the exact
   stock digest. Preserve their existing RollingUpdate strategy and all claims.
   No OnDelete override, Pod eviction or custom controller/binary is introduced.
4. Kubernetes rolls the three StatefulSets normally while the operator and S3
   are stopped. Retain Pod watches and require zero exits, quorum, all eight
   backend Pods at the stock digest, original PVC identities and the complete
   writable native corpus before proceeding. Stop new image steps at minute 40.
5. Resume `storage/seaweedfs-config` against the reviewed source revision while
   the operator is still stopped. Restore the operator's original one replica;
   it converges all rendered resources and starts two stock S3 gateways from the
   valid CR. Verify no extra template delta, seeded authenticated reads, native
   policies and historical bytes. Restore the operator HelmRelease/Kustomization
   suspend fields exactly. Continue the already approved Harbor and Loki checks.
6. On failure, keep writers/S3 fenced and restore the original CR, filer ConfigMap
   and three main images with the same normal StatefulSet rollout. Restore the
   operator, gateways, clients and every captured owner only after recovery checks.
   A blocked Pod requiring eviction remains a new exact-target recovery decision.

This temporarily holds the reconciliation owner instead of changing the stock
CRD or introducing a permanent traffic-control mechanism. Every imperative
backend field must equal the final Git/operator rendering before ownership is
returned. It adds no steady-state runtime patch. Independent encrypted backups,
old WAL trees and all original PVCs/snapshots remain untouched.

Private evidence: `.private/plan0028-stock-cutover-20261020/` in the canonical
checkout, including UID/resource-version journals, image-cache results, Pod
watch records, the local Harbor signal test and API-server dry-run results.
Recovery completed at **02:45:03 UTC**. The conservative interruption bound from
first writer stop to final restoration is **5m41s**, including the intervening
Harbor recovery; it overcounts actual downtime. S3 never stopped because its
rejected patch changed nothing. Original runtime images, templates, replicas,
PVC identities and suspend-field presence/values are verified. All 18 Longhorn
volumes remain healthy; the native corpus remains 32 / 64. Harbor health/admin,
the same historical manifest/seven blobs, new robot push/pull, all 100 baseline
stored Loki records and ten fresh canary records pass. Only the newly recorded
scratch project/repository/robot were removed. Both cache objects and all three
cache Pods are gone; loopback forwards and the local signal-test container are
closed. Original snapshots/backups/WALs are retained.

Remote main and Flux source remain `886fbd6a`; **no stock image or release commit
was deployed**. The corrected final CR, filer ConfigMap and all three backend
main-image changes passed API-server dry runs. The revised live authority request
remains pending. Contract validation passes 507 tests (one skipped); Docusaurus
build passes. These documentation corrections are local commits until publication.

**Prove It Works** adds API admission to the renderer gate after the real rejection.
**Laziness Protocol** keeps ordinary RollingUpdate and a brief owner hold rather
than patching the CRD/operator or adding a permanent traffic-fencing component.

## Admission dependency found during the corrected execution

The corrected operator hold was approved. Image caching and writer/operator/S3
stops passed. Runtime revision `069da499` reached main and the Flux source while
all affected owners remained held. No backend image had changed when the CR
patch was rejected: the operator Deployment also hosts both fail-closed admission
webhooks. A server dry run with the operator running did not prove that the same
patch would be admitted after stopping it.

The smallest additional temporary boundary is an exception for **only
`Seaweed storage/seaweedfs`** in the cluster-scoped
`seaweedfs-operator-mutating-webhook-configuration` and
`seaweedfs-operator-validating-webhook-configuration`. Add this `matchConditions`
entry to their sole `mseaweed.kb.io` / `vseaweed.kb.io` webhook:

```yaml
name: plan0028-maintenance
expression: "request.namespace != 'storage' || request.name != 'seaweedfs'"
```

All other objects still invoke their original fail-closed webhooks. CRD schema
validation remains active, including the two-gateway valid desired state. The
final CR has already passed the real webhook while available, with no mutation
of credentials, storage claims or topology. The two configuration edits passed
API-server dry runs and must be UID/resource-version guarded. No exception has
been applied during preparation.

After this additional approval, apply the two conditions, finish the already
approved CR/config/image transition, resume config against the reviewed source,
and restore the operator. Once its webhook endpoint is ready, remove both added
conditions and verify the entire webhook lists equal their captured originals
before returning Helm ownership. On rollback, restore the original CR while
fenced, then start the operator and restore the two webhook lists. A webhook
exception must never be left behind at handoff. Keep the same 60-minute limit
and minute-40 stop; recover original serving state if this decision does not fit.

## Final resolution

The operator approved the exact-object webhook exception. Both configurations
were changed with UID/version tests, the stock CR and backend rollout passed,
and both complete webhook lists were restored after operator startup. Flux's
operator-before-config dependency and the original CronJob suspension fields
were verified explicitly. Stock SeaweedFS/Loki and the tooling deletion are now
published; see the [completed execution record](2026-10-20-plan0028-stock-cutover.md).
The earlier pending-approval/recovery paragraphs describe their dated checkpoints,
not the final live state.
