# Stock storage qualification under the revised contract — 2026-10-20

Plan 0028's revised contract retains SeaweedFS S3 for applications, Harbor and
Loki, accepts planned downtime and occasional log loss, and rejects maintaining
runtime forks as the long-term solution. The plan update was committed as
`fc2e73d2` before these experiments. This is local qualification, not production
rollout approval. No Kubernetes command, production traffic, credential access,
image publication or deployment was performed.

The tested normal-operation and transition paths pass; no new ordinary-operation
software blocker was found. Production readiness is still incomplete for the
explicit gates below. The known crash-loss risks have not been fixed.

## Evidence and method

Private evidence is in `.private/stock-revised-qualification-20261020/`.
The tests reuse `rehearse.py`, `benchmark.py` and the S3 qualification helper from
Anton `886fbd6a30efff5a8ac75befb25d1e40c8fef45b`. Local adaptations reverse the
SeaweedFS sequence to current patched → stock → patched rollback → stock return.
The separate `app_s3_check.py` adds real SDK presigned/scoped-auth/multipart-abort
and stopped-state restore checks, using synthetic credentials and objects only.

Candidates and controls:

- Stock SeaweedFS 4.48 manifest:
  `sha256:aba492e2a4e4c90bff795745e8e660affa1f09e7650f5981bd7bccd1a06cd931`;
  tested linux/amd64 image config:
  `sha256:7b5ca1f11aa4c91593612d2d4a9e253ec9152a4bd13a19e551290a042a4c52f5`.
- Current patched SeaweedFS control, linux/amd64:
  `sha256:4adde7b56ab00d8fbdb35b0c09b49c012d0b02d0bdbdff15102cb805bdd6e1a7`.
- Harbor registry binary:
  `goharbor/registry-photon@sha256:c4ebef61ceb50a3d8bc21d149bc280422db20a1e69df317b64b74098c3615855`.
- S3 application rehearsal uses stock Loki 3.7.8 linux/arm64 image config
  `sha256:fff3104ee2effa83031d1bb75363f346e4af0af5202036e590648da680fdb082`.
- Separate Loki transition uses stock linux/amd64 manifest
  `sha256:81a6802ec4bd1b88c564494f06376889ed022998a188826190d26d2754ac2aae`
  and patched image config
  `sha256:e08b7f504501aada07bd6d4b79c4468f6480393740c483d1c3785cafaf1f2370`.

SeaweedFS/registry tests use a unique Docker network, synthetic credentials,
loopback-only published ports and disposable data volumes. They have no cluster
configuration or production endpoint. These bridge networks are not an enforced
egress sandbox. The Loki transition uses its existing internal-network harness.
All tests are resource-limited; amd64 runs under local emulation. No performance,
capacity or production interruption-duration claim follows from local timings.

## SeaweedFS cutover, rollback and application checks

The rehearsal retains three masters, three volume servers, two filers and two S3
services, with native two-copy placement and persistent Docker volumes. It changes
one component image at a time, verifies Raft quorum and both gateways' exact seed
object bytes after each replacement, and writes new objects between replacements.
This exercises mixed versions as well as the final stock state. It retains the
supported bucket fsync policy; the patched `leveldb2.sync=true` option is ignored
by stock, so no metadata-durability equivalence is inferred.

At each application checkpoint, Harbor's actual registry binary pushes/pulls six
layers totaling 68 MiB and verifies an OCI manifest. Stock Loki ingests 8,000
numbered records, flushes/index-ships to SeaweedFS, and a new Loki container with
empty local state retrieves all 8,000 from S3. These are per-stage record counts,
not unique production log totals. A separate read-only observer verified all six
baseline registry layer digests and the manifest after the final stock replacement,
before its application test uploads, avoiding repair-by-reupload as evidence.

All four application checkpoints passed: baseline, stock cutover, patched
rollback and stock return. Every recorded component transition exit was zero.
The final helper teardown is parallel: both filers reached its 20-second timeout
(exit 137), and the registry exited 2. Those terminal cleanup exits occurred after
the final passing application checkpoint; they do not establish safe simultaneous
shutdown. The production runbook must use ordered, verified shutdown with adequate
grace. All owned containers, networks and named volumes from the three SeaweedFS
lab attempts were confirmed absent; the Loki harness also completed cleanup.
`verified-summary.json` retains the application results, script hashes and cleanup
checks. There was no production repair or state change.

## App-facing stock S3 and restore

`app-s3-results.json` records passing:

- Signed PUT/GET, overwrite, HEAD, Range GET, list and delete; 12 retained seed
  objects totaling 6,594,560 bytes, including a completed multipart object.
- SDK presigned PUT and GET with exact body comparison.
- An app-scoped identity denied cross-bucket GET, PUT and LIST with HTTP 403.
- Multipart upload/part/abort, absence from active uploads and absent final object.
- Ordered complete shutdown, a separate cold filesystem copy, recreation from
  that copy, and exact seed/upload readback. All four pre-backup exits were zero;
  51 backup file hashes remained unchanged through restore verification.

The restore is of a synthetic single-master/volume/filer/gateway lab on the same
host. It does not establish an independent production backup failure domain or
restore production's multi-filer/Harbor database state. A filer received exit 137
in the final parallel teardown after readback, when the helper stopped all
components concurrently with a 20-second deadline. That does not invalidate the
preceding clean backup, but concurrent teardown is not the proposed production
shutdown procedure. Retain ordered shutdown and verify clean exits.

## Loki patched-to-stock transition

`loki-transition/result.json` records zero missing records across the tested
sequence, ending with 448 acknowledged records. The procedure flushed all chunks,
verified reads from stored chunks, stopped the patched process with exit zero,
started stock on the same data with a new WAL directory, then tested new writes
and abrupt/graceful restarts. The old WAL hashes remained unchanged. The report's
`restarts: 3` field counts the pre-transition cycle only; its stage list records
additional stock restart checks.

This test uses the filesystem object store to isolate WAL/data compatibility.
The S3 application rehearsal separately covers stock Loki reads through
SeaweedFS. It is not permission to point stock Loki directly at patched WAL
counter history, and passing this sequence does not fix the known replay defect.

## Remaining production gates

- Verify exact proposed Flux/rendered configurations and pinned images, including
  removing patch-only metadata-sync assumptions and policy helpers. No production
  manifest change has been prepared or applied in this qualification.
- Refresh the actual data/consumer inventory and obtain a consistent independent
  recovery point. Rehearse production-shaped restoration including Harbor's
  database and registry consistency. The registry protocol fixture is not a full
  Harbor UI/auth/database/GC test.
- Finish lifecycle coverage: the S3 Loki test checks ingestion, flush, index
  shipping and cold queries, not the configured 24-hour/14-day/30-day retention
  deletion schedule. The seven-day observation gate remains unperformed.
- Define each upload consumer's recoverability and backup freshness. Best-effort
  logs do not authorize loss of someone's only uploaded file. No browser/Drop
  application flow or production CORS configuration was exercised.
- Review an ordered cutover/rollback procedure and measured interruption budget
  against the actual Longhorn/operator deployment, then obtain live approval.
  Local Docker replacement is not a Talos node-maintenance or Longhorn test.

Stock compaction remains exposed to the previously demonstrated sync/close-error
behavior. Source inspection finds automatic vacuum defaults in 4.48 of 840 seconds
and a 0.3 garbage threshold; the reviewed production master args do not override
those defaults. Removing a discretionary job would not eliminate that path.
Retain disk-error alerts, backup/restore and the explicit upload-risk decision;
no new custom compaction patch is proposed.

The earlier [strict fault qualification](2026-10-20-stock-storage-qualification.md)
remains valid evidence. Its blanket stock-promotion blocker belongs to the former
contract. Under the revised requirements, fault losses are recorded limitations;
ordinary-operation failures or unmet upload requirements remain blockers.

**Prove It Works** separates actual protocol/restore results from deployment
readiness. **Test Behavior, Not Implementation** keeps exact object bytes, scoped
access and log readback as gates, without requiring a custom log field or perfect
crash recovery to preserve a fork.

## Reproduction and retained setup failures

The private scripts and `fixture-hashes.json` retain the exact local adapters.
Run from Anton through `mise exec --`, with Docker available:

```sh
# Never overwrite existing evidence; choose a fresh output path.
python3 .private/stock-revised-qualification-20261020/scripts/fixtures/seaweedfs-durability/rehearse.py \
  --output <fresh-local-directory> \
  --image sha256:4adde7b56ab00d8fbdb35b0c09b49c012d0b02d0bdbdff15102cb805bdd6e1a7
```

`app_s3_check.py` uses `uv run --with boto3`; its fixed evidence paths intentionally
refuse reuse. The Loki transition uses the previously retained stock-compatible
`verify-stock-loki-checkpoint-restarts.py`, `--cycles 1`, the two exact Loki image
identities above and `--downgrade-image` for the stock artifact. Its single
log-assertion adaptation is documented in the earlier strict report.

The first multi-component attempt used an internal Docker network, on which the
local runtime did not expose the expected published master port. It stopped
before application behavior was tested and cleaned its resources. The second
attempt used the fixture's loopback-published bridge network. Neither that setup
failure nor the optional SDK's initial absence is counted as a software defect.
