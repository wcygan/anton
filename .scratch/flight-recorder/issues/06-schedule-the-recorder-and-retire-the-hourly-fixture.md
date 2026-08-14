# 06 — Schedule the recorder and retire the hourly fixture

**What to build:** Run the accepted Flight Recorder each hour and keep the five-row fixture available only for manual tests.

**Blocked by:** 05 — Prove replay, failure, and recovery behavior.

**Status:** ready-for-agent

- [ ] Flight Recorder ingestion runs at minute 07 each hour in UTC.
- [ ] The schedule uses no automatic catchup and allows one active Workflow Run.
- [ ] Daily Iceberg maintenance runs at 02:27 UTC under the same writer Lease.
- [ ] The first scheduled source hour completes without partial input or concurrent writers.
- [ ] The first scheduled result passes read-only Trino validation.
- [ ] Runtime Logs and Application History retain the scheduled Workflow Run identity.
- [ ] The existing five-row fixture loses its hourly schedule but remains available manually.
- [ ] Manual exact-hour replay remains available for visible gaps within Loki retention.
- [ ] No dashboard, alert, new warehouse, or public endpoint is introduced.
- [ ] Flux, workload readiness, table results, and repository contracts pass after approved rollout.
