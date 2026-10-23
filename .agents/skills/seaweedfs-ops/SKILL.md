---
name: seaweedfs-ops
description: Operate Anton's SeaweedFS storage service. Use for S3 capacity or topology diagnosis, volume-pod address changes, service health, and approved recovery or maintenance. Does not cover Iceberg, Spark, Trino, or Airflow workflows.
---

# SeaweedFS operations

Own read-only diagnosis and operator-reviewed maintenance of the SeaweedFS storage service in `storage`. For cluster-wide symptoms, begin with `anton-cluster-health`; use this skill when evidence points to SeaweedFS.

## Authority and preflight

Inspect before proposing a change. Use the expected Kubernetes context and `mise exec --` for cluster commands. Confirm cluster, namespace, exact object, current Flux owner, symptom window, active S3 writers, and the recovery owner. Do not create diagnostic pods, jobs, port-forwards, or synthetic writes without explicit approval. Do not read Secret data or expose credentials.

A restart, scale change, PVC change, bucket mutation, or deletion is a separate live mutation. Before an approved mutation, state the exact target, expected transition, stop condition, rollback trigger, and acceptance checks. Stop active writers before any approved S3 gateway restart.

## Read-only diagnosis

Compare committed source with live state before relying on a historical note:

- `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml` owns the `Seaweed` custom resource.
- `kubernetes/apps/storage/seaweedfs/app/helmrelease.yaml` owns the operator chart.
- `kubernetes/apps/storage/seaweedfs/app/rbac-supplement.yaml` owns supplemental operator permissions.
- `seaweedfs-config` depends on the operator Kustomization; inspect Flux readiness before interpreting a missing or stale resource.

For a bounded first pass, inspect the Flux Kustomizations and HelmRelease, the Seaweed CR conditions, SeaweedFS pods and PVCs, recent namespace events, and bounded logs from the implicated component. Preserve timestamps and condition messages. Avoid broad logs and secret payloads.

Use [diagnostic gotchas](references/diagnostics.md) for capacity limits, volume topology and address-cache symptoms, and the chart constraints. The reference is diagnostic guidance; confirm current manifests and live state before recommending action.

For planned work, use the [node-maintenance procedure](references/node-maintenance.md) (planned S3 downtime, writer fencing, recovery checks) and the [integrity alert reference](references/health-alerts.md). The [stock cutover record](references/stock-cutover.md) documents the completed one-time image transition and its rollback; it is not a routine procedure.

When `SeaweedFSReadOnlyVolumes` fires because one copy of a two-copy volume failed the startup check and its peer is writable, start with the read-only `mise exec -- python3 scripts/seaweedfs-readonly-repair.py plan <id>` and follow [Repair one read-only copy from its healthy peer](references/health-alerts.md#repair-one-read-only-copy-from-its-healthy-peer). Its `apply` subcommand is a live mutation: it needs a passing rehearsal and explicit operator approval.

## Recovery sequence

1. Establish whether failure is in Flux/operator readiness, master topology, volume allocation, filer metadata, S3 gateway health, or an external client path.
2. Check logical volume slots separately from Longhorn PVC bytes. A full logical slot count can block allocations while PVCs still have free bytes.
3. If a volume pod address changed, compare master topology with bounded S3 logs and the current pod IP arguments. Do not infer stale S3 cache from timestamps alone.
4. If evidence supports a gateway cache fault, identify writers and obtain explicit approval before stopping them or restarting a gateway. Restart only the affected S3 Deployment after confirming master topology is correct.
5. Verify the predicted recovery with read-only status and, only if authorized, the approved S3 smoke test plus one relevant consumer check (for example, Harbor when it is the affected consumer). Confirm no writer or diagnostic resource was left behind.

Bucket lifecycle is owned by `kubernetes/apps/storage/seaweedfs-config/app/buckets-cronjob.yaml`; make bucket provisioning changes at that source of truth and follow the storage subsystem contract.

## Limits

This skill does not operate Iceberg tables, Spark Attempts, Trino queries, or Airflow Workflow Runs. Those learning-platform procedures are retired and retained only in the private documentation-reset archive. Do not revive them from archive without a fresh intake decision.

## Bucket provisioner evidence

The storage-owned CronJob provisions buckets before consumers are reconciled. Inspect it and its Jobs without printing their mounted credentials:

```sh
mise exec -- kubectl -n storage get cronjob seaweedfs-buckets-ensure
mise exec -- kubectl -n storage get jobs -l batch.kubernetes.io/cronjob-name=seaweedfs-buckets-ensure
```

Preserve job completion conditions and bounded, redacted error evidence. Creating a one-off provisioning Job or changing a bucket remains a separately approved mutation. Run `mise exec -- python3 scripts/validate-storage-contract.py` after changing the provisioner or this workflow.
