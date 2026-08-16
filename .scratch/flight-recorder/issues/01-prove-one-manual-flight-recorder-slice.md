# 01 — Prove one manual Flight Recorder slice

**What to build:** Run one manual five-minute Workflow Run from bounded workflow logs through one Spark Attempt into isolated Flight Recorder tables.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] The Workflow Run captures one explicit five-minute workflow-log window.
- [x] The raw object and source manifest retain the query, window, count, byte size, key, and checksum.
- [x] One Spark Attempt uses the authoritative writer Lease and changes only the dedicated Flight Recorder namespace.
- [x] Event rows retain allowlisted identity, a redacted preview, a stable fingerprint, and source-window identity.
- [x] Unsafe records retain safe metadata and a rejection count without a message preview.
- [x] Spark writes events, the affected hourly summary, and the run receipt in that order.
- [x] The run receipt is the completion marker for the non-atomic table writes.
- [x] Read-only Trino checks confirm schemas, counts, partitions, locations, and snapshots.
- [x] An exact replay reuses the raw checksum and does not increase final event counts.
- [x] Focused tests and repository contracts pass.

## Comments

- 2026-08-15: The accepted run retained 312 events, zero rejections, five hourly rows, and one receipt.
- 2026-08-15: The exact replay changed no event count, receipt count, or Iceberg snapshot.
- 2026-08-15: Both Spark Attempts reached `Succeeded`, then `ResourceReleased`, with no active writer Lease.
- 2026-08-15: Repository contracts passed with 264 tests after the evidence command was added.
- 2026-08-15: Evidence checks now require the exact source receipt, table contracts, namespace isolation, and `ResourceReleased`; 266 contract tests passed.
