# 03 — Enforce raw retention and storage admission

**What to build:** Keep raw Flight Recorder inputs short-lived and stop new ingestion before the workload exceeds its accepted storage limits.

**Blocked by:** 02 — Capture one complete lakehouse platform hour.

**Status:** ready-for-agent

- [ ] Storage owns a 48-hour lifecycle for only the Flight Recorder raw-object prefix.
- [ ] The lifecycle cannot delete unrelated raw objects or any Iceberg warehouse file.
- [ ] Admission measures current raw-object bytes and referenced Flight Recorder Iceberg file bytes.
- [ ] Missing or stale storage measurements reject the source hour before table writes.
- [ ] One source hour cannot exceed 25 MiB or 25,000 events.
- [ ] One UTC day cannot accept more than 600 MiB of raw input.
- [ ] Flight Recorder storage cannot exceed 10 GiB of logical data.
- [ ] Ingestion stops when shared SeaweedFS free space falls below 20 percent.
- [ ] Limit rejection records a visible gap and never accepts partial Iceberg data.
- [ ] Validation detects over-age raw objects without claiming unobserved lifecycle deletion.
- [ ] Focused tests, storage contracts, and repository contracts pass.
