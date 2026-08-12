# 03 — Preserve Spark logs and Application History

**What to build:** Preserve complete Runtime Logs and Application History after short-lived Spark containers and failed Spark resources exit.

**Blocked by:** 02 — Run the shadow fixture through SparkApplication.

**Status:** ready-for-agent

- [ ] A targeted log receiver reads new Airflow and Spark container files from their beginning.
- [ ] Persistent checkpoints prevent lost log prefixes after receiver restart.
- [ ] Targeted file selection does not duplicate records from the general cluster receiver.
- [ ] Complete driver and executor markers remain queryable in Loki after container exit.
- [ ] Spark writes compressed rolling event logs through Hadoop S3A to the event-log bucket.
- [ ] A one-replica History Server reads the event logs with read-only credentials.
- [ ] History Server has no Kubernetes API token and cannot delete event data.
- [ ] History Server shows applications, jobs, stages, executors, and Spark SQL data.
- [ ] Failed driver and executor pods remain available for at least 24 hours.
- [ ] Spark application records remain available for seven days.
- [ ] Event logs remain available for 30 days and expire through a storage-owned policy.
- [ ] Successful resources disappear promptly, and retained resources disappear after their bounds.
- [ ] The global failed-pod collector preserves Spark resources marked for retention.

## Comments
