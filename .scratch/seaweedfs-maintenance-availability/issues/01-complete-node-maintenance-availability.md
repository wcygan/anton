# Complete SeaweedFS availability during node maintenance

Status: ready-for-agent
Created: 2026-10-19 (America/Chicago)
Priority: high
Blocked by: none for initial read-only investigation

## Outcome

Existing cold S3 objects remain readable with exact bytes, and fresh PUT/GET
operations succeed, while one verified owning node is unavailable during planned
maintenance. A passing local fixture or a Ready gateway alone is insufficient.

## Last verified state

The prior window is closed and cleaned up; these observations must be refreshed
when work resumes:

- SeaweedFS 4.48 was homogeneous and Ready. Native default `001` and growth
  `COPY_2=1` are enabled; they do not rewrite existing layouts.
- The audit found 27 volumes: 24 single-copy `000` volumes (original IDs 9–15,
  20–31 and 49, plus 53, 54, 56 and 57) and three two-copy `001` volumes
  (50, 51 and 52). No read-only volumes or missing writable layouts remained.
- The existing-data attempt stopped on its first configuration RPC to a retired
  Pod address. Its source VIF hash and native replication were unchanged. No
  successful replication configuration, migration copy or node drain occurred.
- Restoration verified all original volumes writable with PVC identities
  retained. Filers/S3 recovered within 25m13s; all seven owner overrides were
  restored. Exact S3 reads and a fresh write/read passed. All 86 reconcilers,
  72 workloads and 18 Longhorn volumes/36 replicas passed final health checks;
  Loki's flush queue cleared.
- Five exact test keys, 18 temporary objects and 15 completed test Pods were
  removed. Normal credentials, PVCs, source files and backups were retained.

## What remains unresolved

1. **Native command address selection after replacement.** Configuration of VID
   9 dialed a retired address. Later, explicit-node mark-writable for VID 11
   used stable peer DNS but still dialed its retired Pod IP; this path bypasses
   topology collection. Restoration through a current UID-bound Pod IP passed.
   Subsequent topology and caller DNS checks agreed with current endpoints.
   The historical cache/source is unknown; do not declare DNS or master metadata
   the proven root cause or assume a restart fixes it.
2. **Legacy-layout background growth.** Quiescing S3, filers, the operator and
   bucket provisioning did not stop master growth from `000` layouts. It created
   four empty single-copy volumes despite default `001`. Copying a frozen list
   of the original 20 would therefore leave a gap. Retain those new IDs.

## Proposed verifiable increments

Sequence Work into Verifiable Units: finish and check each increment before
advancing. Deliver rerunnable checks and a rollback for each actual change.

1. **Reproduce and qualify the native address path.** Start read-only: compare
   all-master native topology, the exact caller's resolver answers, Ready
   EndpointSlices and Pod/PVC identities. Reproduce replacement/address changes
   in an isolated pinned fixture. Capture the actual configuration/copy targets,
   not just advertised names. Test fail-closed behavior for retired addresses,
   UID/IP changes, partial results and timeouts. Qualify any direct-IP approach
   for configuration and copying separately from the successful writable-mark
   recovery. Do not reuse prior captured identities or blindly retry commands.
2. **Qualify growth control and refresh inventory.** Demonstrate why old layouts
   allocate `000`, then select the smallest enforceable growth fence or bounded,
   explicitly approved inventory strategy. The previously examined
   `master.volume_growth.disable` setting is read at startup; do not treat it as
   a hot toggle. Any master rollout needs separate quorum-safe review/approval,
   plus proof that allocation recovers afterward. Check physical bytes, logical
   slots and two-surviving-node headroom; stop on an unapproved new VID.
3. **Prepare a revised exact live plan.** Refresh the full corpus, ownership,
   version/digests, backups/recovery evidence, current writers, Loki buffer margin
   and source revision. Preserve existing data and observability. Include the
   proved address/growth controls, reversible controller/vacuum fencing, exact
   resource identities, temporary clients/policies, cleanup and time budgets.
   The prior plan used a 30-minute outage and stopped new copies at 20 minutes;
   remeasure preparation, copy/hash and recovery costs before proposing reuse.
4. **Run a largest-volume pilot, then migrate checked increments.** Only in the
   newly approved window, fence/drain admitted writes safely and measure the
   largest current volume first. Compare source/destination `.dat`, `.idx` and
   `.vif` hashes while quiesced, preserve object FIDs, and verify native `001`
   copies on distinct Ready node UIDs. Continue only if the remaining work and
   restoration fit the approved budget. Reconcile inventory after each unit.
5. **Prove real maintenance availability and recovery.** After the entire agreed
   corpus passes placement checks, prepare filer maps and fresh S3 processes as
   specified by the runbook. Join each never-read fixture's locations to the
   approved node UID. During the approved bounded node hold, prove that owner is
   actually unavailable, verify cold exact-byte reads through every surviving
   S3 backend and fresh PUT/GET with two surviving owners. Preserve PDBs; no
   forced eviction. Uncordon, verify recovery and remove only exact owned test
   resources/keys. Record the outcome and close only after acceptance passes.

## Acceptance and rollback

- [ ] A rerunnable check rejects stale command targets and unapproved growth;
  the selected fix passes the isolated failure/recovery scenario.
- [ ] Every in-scope existing volume has two verified serving copies on distinct
  nodes, with source/PVC identities, byte integrity and capacity recorded.
- [ ] Cold existing-object reads and fresh writes pass during actual owner
  absence, with exact bytes/digests and backend/node identities retained.
- [ ] Stable full recovery, original owner settings and zero temporary residue
  are verified; Git, Flux and applied runtime intent agree.

Stop new work on an identity mismatch, unexpected writer/VID, missing copy,
ambiguous result, hash mismatch or budget limit. Retain all files and PVCs.
Restore untouched singleton volumes to their original metadata/writability only
after proving no destination exists. Retain verified two-copy pairs; do not
downgrade registered pairs or delete a copy to simulate rollback. Keep ambiguous
volumes read-only and report them explicitly. Restore approved service owners
and uncordon on drill failure. Reverting the default does not undo copied data.

Delete test Jobs with explicit background propagation and exact UID/resource
version preconditions; verify their Pods are absent too. Verify exact S3 key
absence with HEAD. Keep the client ConfigMap and policies until test Pods are gone.

## Authority and pickup

This ticket authorizes no live action. Initial repository work and read-only
diagnosis can be planned independently; live exec/probes, replacements, fencing,
copying, Jobs, reconciles and drains require the newly reviewed exact operator
approval specified by Anton's operational contract. The earlier window is over.

Use current main containing PRs 517–521 in an isolated worktree; preserve the
canonical checkout's unrelated dirty work. Root owns shared integration and all
live mutations; GPT-6 Luna high-effort workers use separate worktrees if
delegation is useful. No work is running or scheduled for this ticket.

## Evidence and references

- [Recovered abort and limits, PR 521](https://github.com/wcygan/anton/pull/521).
- [Pinned outcome record](https://github.com/wcygan/anton/blob/d162ef88439305f8c1c98502ad240235a496338e/context/notes/2026-10-20-seaweedfs-migration-abort.md).
- [Revised maintenance runbook](https://github.com/wcygan/anton/blob/d162ef88439305f8c1c98502ad240235a496338e/docs/docs/runbooks/seaweedfs-node-maintenance.md).
- [Parent plan 0027](https://github.com/wcygan/anton/blob/d162ef88439305f8c1c98502ad240235a496338e/context/plans/0027-improve-cluster-operational-outcomes.md).
- [Audit, PR 517](https://github.com/wcygan/anton/pull/517), [isolated proof, PR 518](https://github.com/wcygan/anton/pull/518), [policy/ADR 0043, PR 519](https://github.com/wcygan/anton/pull/519), [wire decoder correction, PR 520](https://github.com/wcygan/anton/pull/520).
- Raw execution evidence remains in the operator's private checkpoint. If it is unavailable when work resumes, diagnose from fresh evidence; never copy old approval bindings into a new window.

## Comments

- 2026-10-19: Backlog requested after the recovered maintenance attempt. Scope
  is future availability work; capture only today, with no new rollout or drill.
