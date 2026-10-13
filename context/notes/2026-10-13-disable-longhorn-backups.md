# Disable the abandoned Longhorn backup target

The operator accepts loss of Anton's disposable persistent data and does not
want backup infrastructure, external storage, paid services, or Betty involvement.
Longhorn volume replication remains useful and unchanged.

## Cause and repair

The default target retained `s3://longhorn-backups@us-east-1/` and the missing
`longhorn-backup-credentials` reference after commit `415eed92` removed the
SeaweedFS-backed backup configuration in August. Omitting chart values preserved
the old live target; cached availability misleadingly remained true.

Commit `a692d4a6` explicitly sets these HelmRelease values for Longhorn 1.12.1:

```yaml
defaultBackupStore:
  backupTarget: ""
  backupTargetCredentialSecret: ""
  pollInterval: 0
```

The chart renders only a change to `ConfigMap/storage/longhorn-default-resource`.
Longhorn watches that ConfigMap and updates `BackupTarget/storage/default`.
Empty strings clear the endpoint and credential reference; zero stops polling.
Deleting the default target is unnecessary because Longhorn manages its creation.
No Secret, bucket, volume, replica, snapshot, or backup deletion was performed.

## Verification

- All 357 contract tests passed; the rendered workload templates are unchanged.
- Flux applied `a692d4a6`; HelmRelease generation 15 completed release v15.
- At 15:41:01 UTC the live target cleared both strings and set `pollInterval: 0s`.
  `Unavailable=True`, message `backup target URL is empty`, is expected for the
  deliberately disabled target and is not a volume-health failure.
- All 16 volume and 32 replica identities and complete specs match the baseline.
  All 45 storage pod identities, container identities, and restart counts match.
- All three nodes Ready, Cilium 3/3, CoreDNS 2/2, Prometheus targets 72/72 up;
  Harbor components, Loki, Kubernetes API, and Talos/etcd health checks passed.
- The only RecurringJob remains `observability-weekly-trim` (filesystem-trim),
  not a backup job.

Future reviews should treat absent backups as intentional. This record resolves
the backup-credential follow-up in
[the memory/parser rollout](2026-10-13-longhorn-flux-memory-and-target-parser.md).
