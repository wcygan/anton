# SeaweedFS 4.48 migration abort and recovery — 2026-10-20

> Outcome record for the live migration authorized alongside [PR #519](https://github.com/wcygan/anton/pull/519).

## Outcome

The migration began at 01:50:17.096374 UTC and stopped during the first per-volume replication-configuration attempt. No volume was configured or copied, and no node drain occurred. The original twenty volumes remained `000`. New volume 52 has two verified copies, but `001` is not guaranteed for every new allocation: autogrowth from an existing `000` layout can still create `000`.

All twenty original `000` volumes were marked read-only before the volume processes were replaced serially through normal PDB-respecting evictions. Their PVCs were retained. The first `configure` attempt targeted VID 9 from 02:02:52 to 02:03:13 UTC and ended in a gRPC timeout against a stale address. The native status stayed `000` and read-only, and the persisted `.vif` hash was unchanged. No `configure` or `copy` operation completed.

## Recovery evidence

VIDs 9 and 10 restored through stable DNS. VID 11's explicit-node request through stable DNS failed while dialing its retired Pod IP; retrying with the current IP succeeded. The remaining volumes were restored to their exact current Pod identities and addresses. All twenty original volumes' native placement and persisted `.vif` state were verified by 02:15 UTC; vacuum was re-enabled. Both filers were Ready by 02:14:59 UTC. Both S3 gateways and read probes were Ready by 02:15:30 UTC (first Ready at 02:15:19); root observed this at 02:16:05. Readiness returned 25m12.904s after outage start. All seven owner fields were restored at 02:17:45 UTC, including operator replicas=1, the bucket CronJob unsuspended, and the original absent suspension fields on the HelmRelease and Kustomizations restored as absent.

## Supported cause and limits

The observations support a stale volume-address path. All three masters showed identical topology DNS, and master 0 now resolves to the current address; the historical source is unknown. VID 9's configure timeout left native placement and its persisted `.vif` hash unchanged.

The 02:20:49 UTC native audit found 24 writable single-copy `000` volumes (the original twenty plus 53, 54, 56, and 57) and three `001` volumes (50, 51, and 52), with no read-only volumes or unmapped owners. Only VID 53 has an empty collection; 54/56/57 belong to Harbor/Loki/S3 read probe and each has an eight-byte zero file. Existing `000` data gained no maintenance availability; there was no node-drain acceptance. Inventory review remains future work.

At 02:21 UTC all three nodes were Ready and schedulable. SeaweedFS generation 29 was current: 3/3 masters, 3/3 volume servers, 2/2 filers, and 2/2 S3 gateways Ready, with zero restarts. All 86 Flux reconcilers and 72 Deployments/StatefulSets were Ready; all 18 Longhorn volumes were healthy with 36 running replicas. Harbor's seven components were healthy. Loki queue was zero at 02:18:46 and 02:21:04, failure counter remained 210 with a five-minute increase of zero, WAL disk-full was zero, and PVC free space exceeded 20.9 GB. Three seeded cold GETs passed exact SHA checks; write-default GET passed both fresh S3 gateway UIDs; recovery PUT/GET passed SHA.

Related context: [the prior SeaweedFS maintenance-availability record](2026-10-19-seaweedfs-maintenance-availability.md) describes the baseline and the separate cold-read availability gates.

## Recording choices

- **Fix Root Causes** leaves the historical stale-address source unresolved.
- **Explain the Number** separates the 25m12.904s readiness interval from the later 02:21 health snapshot.
- **Sequence Work into Verifiable Units** records unchanged native state after timeout and per-VID restore checks.
- **Prove It Works** distinguishes three `001` from 24 `000` volumes and records exact SHA checks without node-drain claims.

## Cleanup and retained data

Cleanup completed at 02:26:36 UTC. All five temporary S3 keys returned `DELETE 204` and `HEAD 404`. Fifteen Jobs, the client ConfigMap, and two NetworkPolicies (18 UID-owned objects) are absent; all fifteen completed Pods are also absent, and the combined Job/Pod/ConfigMap/NetworkPolicy selector returns zero. The seven original owner fields were reverified. Normal Secrets, PVCs, SeaweedFS source files, and backups were retained; no node drain occurred.

The cleanup runbook must specify background propagation for owned Job deletion and verify dependent Pods and all temporary objects absent before closing. Deleting the Jobs left fifteen succeeded Pods behind; cleanup required joining run labels with the original controller UIDs and template, then deleting those exact Pod UIDs with resource-version preconditions. The final absence checks caught the dependent-object residue.
