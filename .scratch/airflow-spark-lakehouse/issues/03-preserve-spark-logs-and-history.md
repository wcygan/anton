# 03 — Preserve Spark logs and Application History

**What to build:** Preserve complete Runtime Logs and Application History after short-lived Spark containers and failed Spark resources exit.

**Blocked by:** 02 — Run the shadow fixture through SparkApplication.

**Status:** resolved

- [x] A targeted log receiver reads new Airflow and Spark container files from their beginning.
- [x] Persistent checkpoints prevent lost log prefixes after receiver restart.
- [x] Targeted file selection does not duplicate records from the general cluster receiver.
- [x] Complete driver and executor markers remain queryable in Loki after container exit.
- [x] Spark writes compressed rolling event logs through Hadoop S3A to the event-log bucket.
- [x] A one-replica History Server reads the event logs with read-only credentials.
- [x] History Server has no Kubernetes API token and cannot delete event data.
- [x] History Server shows applications, jobs, stages, executors, and Spark SQL data.
- [x] Failed driver and executor pods remain available for at least 24 hours.
- [x] Spark application records remain available for seven days.
- [x] Event logs remain available for 30 days and expire through a storage-owned policy.
- [x] Successful resources disappear promptly, and retained resources disappear after their bounds.
- [x] The global failed-pod collector preserves Spark resources marked for retention.

## Comments

- Resolved on 2026-08-12 at source revision `b7f56657`.
- `mise exec -- task contracts:validate` passed all 178 tests.
- Loki retained driver completion markers and executor lifecycle markers after both containers exited.
- Spark wrote a 255303-byte compressed event log through Hadoop S3A.
- History Server showed one completed application, 19 jobs, 41 stages, two executors, and 10 SQL records.
- The History Server pod had no Kubernetes API token. Its S3 reader received `403 AccessDenied` for a delete probe.
- The storage policy reconciled the `spark-events` bucket and its 30-day lifecycle policy.
- The retention cleaner and global pod collector completed while marked failed Spark pods remained present.
- The 1Password writer fields and both live Kubernetes Secrets matched without exposing their values.
- External Secrets remained rate-limited by 1Password after the match check. The next controller retry will write identical data.
