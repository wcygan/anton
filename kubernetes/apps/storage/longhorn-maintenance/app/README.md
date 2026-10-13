# Observability volume maintenance

Weekly filesystem trim runs Sunday at 04:30 UTC, concurrency one. Selection
is limited to the existing Prometheus and Talos log-sink volumes. Metadata-only
Volume manifests use SSA Merge and disable pruning; their specifications and
lifecycle remain owned by Longhorn. If a PVC is replaced, update its volume
identity here after verifying the replacement. Do not add this job to the
default group or enable automatic snapshot removal.

Longhorn's chart owns orphan replica-data cleanup with a seven-day grace period.
The initial 43-orphan backlog was explicitly verified and removed before enabling
this policy. Automatic cleanup gives up abandoned recovery copies after that
window. Disabling the setting stops future cleanup; deletion cannot be undone.

Talos log files are split into routine (one complete day plus today), warnings
and diagnostics (14 days plus today), and errors (30 days plus today). Missing
severity and kernel records get diagnostic retention. Legacy mixed files retain
30 days during migration. Prometheus keeps 30 days of metrics, capped at 35GB.

Harbor retains two recently pushed artifacts per repository, plus explicit
`rollback` and reconciler-owned `in-use-*` tags. The reconciler reads current pods
and declared workloads before tagging their digests. It fails closed on inventory
errors and removes obsolete protection tags. The recognized registry host is
configured in HARBOR_IMAGE_HOST. Daily retention follows at 01:30 UTC; weekly GC
runs Sunday 05:30 UTC. Untagged artifacts are excluded from GC deletion.
