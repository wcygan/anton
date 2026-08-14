# 02 — Run the shadow fixture through SparkApplication

**What to build:** Run the deterministic fixture through Apache Spark Operator into isolated shadow Iceberg tables, then validate them through read-only Trino.

**Blocked by:** 01 — Qualify the immutable Spark runtime.

**Status:** resolved

- [x] Flux owns separate Spark operator, lakehouse workload, and Trino namespaces.
- [x] Spark Operator uses chart 1.8.0, operator 1.0.0, and the `spark.apache.org/v1` API.
- [x] Operator and workload permissions are namespace-scoped and do not grant cluster administration.
- [x] One `SparkApplication` creates a bounded driver and one executor with restart policy `Never`.
- [x] Spark heap, overhead, and native headroom remain below each 1536Mi pod limit.
- [x] The fixture writes Iceberg format version 2 tables only to the shadow warehouse.
- [x] The authoritative warehouse and its table formats remain unchanged.
- [x] The normalized table keeps its current idempotent `MERGE` behavior.
- [x] The hourly table keeps its current delete-and-insert behavior.
- [x] Trino 480 validates schema, `5 / 5 / 5` counts, partitions, snapshots, locations, and time travel.
- [x] Trino rejects writes through connector policy and read-only storage credentials.
- [x] Repository contract validation and one approved live shadow run retain complete evidence.

## Comments
