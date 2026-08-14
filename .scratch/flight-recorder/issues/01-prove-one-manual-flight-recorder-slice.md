# 01 — Prove one manual Flight Recorder slice

**What to build:** Run one manual five-minute Workflow Run from bounded workflow logs through one Spark Attempt into isolated Flight Recorder tables.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The Workflow Run captures one explicit five-minute workflow-log window.
- [ ] The raw object and source manifest retain the query, window, count, byte size, key, and checksum.
- [ ] One Spark Attempt uses the authoritative writer Lease and changes only the dedicated Flight Recorder namespace.
- [ ] Event rows retain allowlisted identity, a redacted preview, a stable fingerprint, and source-window identity.
- [ ] Unsafe records retain safe metadata and a rejection count without a message preview.
- [ ] Spark writes events, the affected hourly summary, and the run receipt in that order.
- [ ] The run receipt is the completion marker for the non-atomic table writes.
- [ ] Read-only Trino checks confirm schemas, counts, partitions, locations, and snapshots.
- [ ] An exact replay reuses the raw checksum and does not increase final event counts.
- [ ] Focused tests and repository contracts pass.
