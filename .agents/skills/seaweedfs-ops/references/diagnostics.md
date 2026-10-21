# SeaweedFS diagnostic gotchas

Use this reference for read-only triage. The current `Seaweed` source is `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`; first compare it with the live CR and operator conditions before relying on historical notes.

## Capacity has two limits

PVC free bytes and SeaweedFS logical volume slots are separate. A volume server can run out of `maxVolumeCounts` while its PVC still has space. Inspect the current CR's `volume.maxVolumeCounts`, each volume pod's conditions/events, PVC capacity, and master topology before attributing write failures to Longhorn capacity. The current source sets `maxVolumeCounts: 20`, `requests.storage: 120Gi`, and `master.volumeSizeLimitMB: 5000`; these are current source values, not a promise about live state.

## Topology and stale addresses

After a volume pod address changes, compare master topology with the failing S3 request's logs and conditions. The current CR pins volume pod IP via `-ip=$(POD_IP)` because headless Service DNS can retain an old address after a restart. Verify both manifest and live pod arguments before treating this historical failure mode as current.

## S3 restart boundary

A restart of SeaweedFS S3 gateways affects active object-store clients. Do not initiate one as diagnosis. If the operator has authorized a recovery, stop active writers first, restart only the affected S3 gateways after confirming master topology is correct, then verify the S3 smoke test and one authoritative consumer workflow. See the current storage subsystem guidance and workload-specific recovery procedure.

## Current operator chart constraints

The committed `rbac-supplement.yaml` addresses missing `apps/deployments` and ServiceMonitor permissions in the shipped chart; the Seaweed CR uses pod anti-affinity because the chart CRD did not expose topology spread constraints when these manifests were authored. Treat both as current only while the committed chart and rendered CRD still exhibit those constraints. Before removing the supplement or changing scheduling fields, inspect the exact chart version and CRD schema. Do not apply workarounds from the archived baseline without that comparison.
