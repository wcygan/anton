---
title: SeaweedFS integrity alerts and durability
---

The SeaweedFS alerts detect integrity errors and read-only logical volumes.
They do not automatically repair files or restore writability. Longhorn volume
health is a separate layer: healthy block replicas can contain identical corrupt
application files.

## Alert behavior

| Alert | Trigger | Evaluation |
| --- | --- | --- |
| `SeaweedFSReadOnlyVolumes` | Native `SeaweedFS_volumeServer_read_only_volumes{type="IsReadOnly"}` is positive | Prometheus, after 5 minutes |
| `SeaweedFSVolumeMetricsUnavailable` | Healthy volume scrape targets exporting the read-only gauge are fewer than desired StatefulSet replicas, including a missing gauge or absent scrape pool | Prometheus, after 10 minutes |
| `SeaweedFSVolumeIntegrityFailure` | Startup integrity failure, index beyond data boundary, or invalid needle CRC in volume logs | Embedded Loki ruler, every 30 seconds, looking back 15 minutes |

All three use `severity: critical` and the existing Alertmanager-to-ntfy route.
Normal Alertmanager grouping and delivery delays still apply. Read-only metrics
are per server and collection, not per logical volume ID. Inspect `/status` to
identify affected IDs. `IsReadOnly` is the total; adding its cause series would
double-count volumes. Deliberate maintenance that leaves volumes read-only can
also trigger this alert. The gauge does not cover every quarantined/EIO state;
retain Longhorn, pod readiness, and log monitoring.

The operator owns the `seaweedfs-volume` ServiceMonitor and per-pod metrics
Services when `spec.volume.metricsPort: 9327` is enabled. The Flux dependency on
kube-prometheus-stack ensures monitoring CRDs exist before configuring Seaweed.
No second hand-authored ServiceMonitor is needed.

Integrity failures can be INFO messages. The Loki rule matches failure text
without a severity selector, retaining the existing severity policy. Volume logs
have a dedicated OTel reader that starts at the beginning and persists offsets
under `/var/lib/otelcol`. The general reader excludes these paths to prevent
duplicates. On first discovery, records older than one hour are dropped after
CRI timestamp parsing; this prevents replaying old incidents and Loki age-limit
rejections. The alert itself only considers the most recent 15 minutes.

Loki evaluates a ConfigMap rule file mounted below the unauthenticated tenant
directory `fake/`. `loki.structuredConfig.ruler` is intentional: chart 18.13.5
omits `rulerConfig` from its generated config when `ruler.enabled` is false.
The existing monolithic `target=all` process evaluates the rules; there is no
additional ruler workload. Rule files are local, but integrity log ingestion and
queries still depend on Loki and SeaweedFS S3. The native Prometheus read-only
alert remains independent of that path. This is detection, not an integrity scan
of every stored object or a guarantee that an unavailable logging pipeline will
retain a failure. A prolonged log collection outage can exceed the alert window.

## Respond safely

1. Confirm Kubernetes context, namespace `storage`, pod identity, node, PVC, and
   logical volume ID. Record `/status`, master topology, pod restarts/events,
   bounded volume logs, and Longhorn conditions before intervening.
2. Distinguish capacity/slot exhaustion and deliberate read-only maintenance from
   data/index corruption. Read-only does not itself prove corruption.
3. For integrity failures, preserve original data, index, volume metadata, and
   hashes outside the affected storage system. Check live filer references and
   chunk manifests, retained backups, and the whole valid data/index prefix.
4. Rehearse a proposed repair against independent disposable copies with the
   same SeaweedFS version. Obtain approval for the exact live operation and
   rollback. Never copy volume 9's byte offsets to another incident or force
   writability to silence an alert.
5. After an approved repair, verify payload reads, master topology, writability,
   Longhorn health, dependent applications, and stable restarts. A 15-minute
   integrity alert can remain firing until the original message ages out.

## Durability review — 2026-10-19

Reviewed the deployed SeaweedFS 4.40 source at revision `875cd1f67` and current
generated volume StatefulSet and Longhorn StorageClass. This patch changes
monitoring only; it does not change write durability or replication.

| Layer | Current setting or behavior | Consequence |
| --- | --- | --- |
| Seaweed replication | Master `defaultReplication: "000"` | One Seaweed copy of each logical volume; three volume-server pods are not three copies of its data. |
| Longhorn | Default StorageClass: two replicas, ext4, data engine v1 | Replicates block writes received by Longhorn; cannot persist bytes still buffered above it or independently validate application CRC/index consistency. |
| Ordinary writes | No explicit filer `fsync` policy in the Seaweed CR; default write path does not sync each request | Acknowledged writes can remain buffered; abrupt failures can lose recent appends. |
| Explicit `fsync=true` writes | Async batch path calls `DataBackend.Sync()` before completing requests | Improves data-file persistence, but this path does not explicitly sync the separate index file. |
| Index | Volume index defaults to `memory` with an on-disk `.idx` append log; appends use `WriteAt`, with a separate `Sync()` operation | A data-file flush alone does not establish an atomic durable data/index pair. Close/sync paths must also complete. Switching index cache mode alone does not establish this guarantee. |
| Internal filer metadata log | `assignAndUpload` constructs its volume upload URL without forwarding the resolved rule's `Fsync` setting | A bucket/path fsync rule cannot be assumed to cover this internal log, which was the collection containing volume 9. |
| Shutdown | Generated volume pod has 30-second grace; volume pre-stop default is 10 seconds; shell launches `weed` without an explicit `exec` | Verify signal delivery and actual flush completion in a disposable test before assuming graceful drain behavior. A timeout, forced kill, or node power loss can bypass it. |

Source references: [data write and fsync path](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67/weed/storage/volume_write.go),
[index append and sync](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67/weed/storage/needle_map.go),
and [internal metadata-log upload](https://github.com/seaweedfs/seaweedfs/blob/875cd1f67/weed/filer/filer_notify_append.go).

Volume 9 had a valid checksummed prefix followed by 616 zero data bytes and one
zero 16-byte index entry. An interrupted append or lost buffered write is the
leading explanation. The initiating event remains unproven because incident-time
telemetry is unavailable. Current healthy disks cannot exclude a past power or
storage interruption. The targeted repair corrected the files, not this failure
class.

Recommended next work is a disposable fault-injection test of ordinary writes,
explicit fsync writes, internal filer log writes, SIGTERM, forced process exit,
and simulated host/storage interruption. Measure acknowledged payload survival,
data/index consistency, restart integrity checks, and latency. Verify signal
forwarding and shutdown completion, then choose an upstream fix or supported
durability configuration from that evidence. Review UPS/power protection and
independent, restore-tested backups alongside it. Do not describe a global
`fsync` toggle or extra Longhorn replica as a complete fix for paired-file
durability. No production power-cycle or durability flag change is part of
this monitoring change.

## Validate and roll out

Local checks (Docker and repository tools required; no cluster access):

```sh
mise exec -- python3 scripts/verify-seaweedfs-alerts.py
mise exec -- task contracts:validate
mise exec -- kustomize build kubernetes/apps/storage/seaweedfs-config/app
mise exec -- kustomize build kubernetes/apps/observability/loki/app
mise exec -- bun run --cwd docs build
```

The behavior check runs promtool against the actual rules, verifies healthy,
read-only, recovery, cause-series, one/all-target-down, missing-gauge and missing-monitor
scenarios, exercises the real Loki query and ruler with fresh/stale/foreign INFO
logs, and runs the pinned OTel binary against fresh/old CRI records. The local
Loki read API is enabled only for test assertions, and notification delivery is
pointed at an unused local address. Containers and temporary files are removed.

Publishing and reconciliation need explicit operator authorization. In particular,
adding `metricsPort` changes the generated volume StatefulSet and rolls its three
pods. OTel and Loki also roll their workloads. Schedule a storage maintenance
window, pause active writers through their owning workflows, and verify backup
and recovery state before publishing. Do not force a reconcile or delete pods
as a diagnostic step.

After the approved GitOps rollout:

1. Verify intended Git/Flux revision and the Seaweed CR generation, then observe
   each volume pod returning Ready with unchanged PVC identity and no integrity
   errors. Stop at any unexpected volume failure; do not roll more pods manually.
2. Confirm the operator-created ServiceMonitor, three `volume-metrics` targets
   `up == 1`, and native `IsReadOnly` gauge series (normally zero). Confirm both
   Prometheus rules are loaded with no evaluation error.
3. Verify OTel checkpointed capture, Loki's mounted rule and ruler evaluation
   metrics, and the Alertmanager route. An actual ntfy test requires separately
   approved synthetic traffic; local validation does not prove live delivery.
4. Compare master addresses with S3 requests after pod changes. If gateways retain
   stale addresses, confirm active writers are paused and restart only
   `storage/deployment/seaweedfs-s3` under the approved maintenance scope, then
   verify readiness and an S3 write/read/delete smoke test. Check Harbor and Loki
   requests afterward. The Airflow/Spark learning stack was retired on
   2026-10-12; do not recreate it or run its historical workflow for acceptance.
5. Observe for at least 20 minutes: all targets healthy, zero read-only counts,
   no rule errors, and no new storage errors or restart loops.

If monitoring causes regressions, revert only this change through Git and
observe reconciliation; removing the metrics port rolls volume pods again, so
retain the maintenance precautions. Preserve unrelated changes. No volume data,
index files, or credentials need alteration for this rollback.
