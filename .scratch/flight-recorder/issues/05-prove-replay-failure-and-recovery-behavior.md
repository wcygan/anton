# 05 — Prove replay, failure, and recovery behavior

**What to build:** Prove that complete-hour replay and all bounded failure paths preserve one writer, complete data, and visible gaps.

**Blocked by:** 03 — Enforce raw retention and storage admission; 04 — Maintain Flight Recorder Iceberg tables.

**Status:** ready-for-agent

- [ ] Exact-hour replay reproduces every raw key and checksum without increasing final event counts.
- [ ] A source query that reaches an entry or byte fence prevents Spark submission.
- [ ] A malformed record retains safe rejection metadata and no unsafe preview.
- [ ] A failure after an event or summary commit can retry safely because the receipt is written last.
- [ ] An active or ambiguous prior Spark Attempt prevents Lease takeover and duplicate writes.
- [ ] Missing accounting, stale accounting, stale maintenance, and every storage limit stop ingestion.
- [ ] A missed hour older than Loki retention remains a visible permanent gap.
- [ ] Read-only Trino results agree with the accepted source and Spark receipts.
- [ ] Airflow, SparkApplication, Runtime Logs, and Application History retain one identity chain.
- [ ] Focused recovery tests and repository contracts pass.
