-- Operator-run Trino CLI acceptance checks for the Spark-written Iceberg tables.
-- Run after the fixture workload has completed, for example:
--   trino --server http://trino.iceberg-demo.svc.cluster.local:8080 < validation.sql

-- Expected result: normalized_count=5, hourly_count=5, hourly_event_count_sum=5.
SELECT
    (SELECT count(*) FROM iceberg.logs.normalized) AS normalized_count,
    (SELECT count(*) FROM iceberg.logs.hourly) AS hourly_count,
    (SELECT coalesce(sum(event_count), 0) FROM iceberg.logs.hourly) AS hourly_event_count_sum;

-- Deterministic hourly result (ordered by event time, then dimensions).
-- Expected rows:
--   2026-08-06 10:00:00.000 UTC | api    | INFO  | 1
--   2026-08-06 10:00:00.000 UTC | api    | WARN  | 1
--   2026-08-06 11:00:00.000 UTC | worker | ERROR | 1
--   2026-08-06 11:00:00.000 UTC | worker | INFO  | 1
--   2026-08-06 12:00:00.000 UTC | api    | INFO  | 1
SELECT hour, service, level, event_count
FROM iceberg.logs.hourly
ORDER BY hour ASC, service ASC, level ASC;
