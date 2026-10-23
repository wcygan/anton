# SeaweedFS diagnostic gotchas

Use this reference for read-only triage. The current `Seaweed` source is `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`; first compare it with the live CR and operator conditions before relying on historical notes.

## Capacity has two limits

PVC free bytes and SeaweedFS logical volume slots are separate. A volume server can run out of `maxVolumeCounts` while its PVC still has space. Read `volume.maxVolumeCounts`, `volume.requests.storage` and `master.volumeSizeLimitMB` from the current CR, compare them with the live `-max` and `-volumeSizeLimitMB` arguments, and count slots with `volume.list` from a master pod (it needs no lock) before attributing write failures to Longhorn capacity. Do not copy sizes from an older note.

Where slots go with `001` placement on three servers:

- Every volume sits on one of three server pairs. While a server is down, the master's background growth loop (about every five minutes in 4.48) creates one volume on the surviving pair for each collection without a writable, non-crowded volume there, even with no writes. Collections therefore settle at one or more volumes per pair, six slots or more. A new bucket starts with one volume and gains the others during the next node roll. Empty volumes made this way are the bucket's maintenance write targets, not waste.
- `WEED_MASTER_VOLUME_GROWTH_COPY_1/2=1` makes each growth one volume; collections created before that setting keep their earlier batches.
- A copy repair onto a third server needs a free slot on that exact server.

Keep `maxVolumeCounts` × `volumeSizeLimitMB` under the volume filesystem size minus the 1% `minFreeSpace` and one volume of compaction space, so bytes cannot run out before slots. Changing `maxVolumeCounts` rewrites only the volume StatefulSet's `-max` argument (operator 1.0.40); the three volume pods roll one at a time. `SeaweedFSVolumeSlotsLow` and `SeaweedFSVolumeSlotsExhausted` read the volume servers' `SeaweedFS_volumeServer_max_volumes` and `SeaweedFS_volumeServer_volumes{type="volume"}`; master metrics are not scraped.

Reclaiming slots is an emergency measure, and each step is a separately approved mutation. `volume.deleteEmpty -quietFor=24h` (under `lock`) only lists empty volumes; adding `-apply` deletes them after the volume server re-checks emptiness, and the next node roll recreates them. Do not make room with `fs.mergeVolumes` (it rewrites live filer entries), `volume.fsck -reallyDeleteFromVolume` (it deletes needles and frees no slot), or a lower `volumeSizeLimitMB` (more volumes per byte). `master.volume_growth.disable` also blocks the first write to a new bucket.

## Topology and stale addresses

After a volume pod address changes, compare master topology with the failing S3 request's logs and conditions. The current CR pins volume pod IP via `-ip=$(POD_IP)` because headless Service DNS can retain an old address after a restart. Verify both manifest and live pod arguments before treating this historical failure mode as current.

## S3 restart boundary

A restart of SeaweedFS S3 gateways affects active object-store clients. Do not initiate one as diagnosis. If the operator has authorized a recovery, stop active writers first, restart only the affected S3 gateways after confirming master topology is correct, then verify the S3 smoke test and one authoritative consumer workflow. See the current storage subsystem guidance and workload-specific recovery procedure.

## Current operator chart constraints

The committed `rbac-supplement.yaml` addresses missing `apps/deployments` and ServiceMonitor permissions in the shipped chart; the Seaweed CR uses pod anti-affinity because the chart CRD did not expose topology spread constraints when these manifests were authored. Treat both as current only while the committed chart and rendered CRD still exhibit those constraints. Before removing the supplement or changing scheduling fields, inspect the exact chart version and CRD schema. Do not apply workarounds from the archived baseline without that comparison.
