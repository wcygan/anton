# 02 — Run the shadow fixture through SparkApplication

**What to build:** Run the deterministic fixture through Apache Spark Operator into isolated shadow Iceberg tables, then validate them through read-only Trino.

**Blocked by:** 01 — Qualify the immutable Spark runtime.

**Status:** ready-for-agent

- [ ] Flux owns separate Spark operator, lakehouse workload, and Trino namespaces.
- [ ] Spark Operator uses chart 1.8.0, operator 1.0.0, and the `spark.apache.org/v1` API.
- [ ] Operator and workload permissions are namespace-scoped and do not grant cluster administration.
- [ ] One `SparkApplication` creates a bounded driver and one executor with restart policy `Never`.
- [ ] Spark heap, overhead, and native headroom remain below each 1536Mi pod limit.
- [ ] The fixture writes Iceberg format version 2 tables only to the shadow warehouse.
- [ ] The authoritative warehouse and its table formats remain unchanged.
- [ ] The normalized table keeps its current idempotent `MERGE` behavior.
- [ ] The hourly table keeps its current delete-and-insert behavior.
- [ ] Trino 480 validates schema, `5 / 5 / 5` counts, partitions, snapshots, locations, and time travel.
- [ ] Trino rejects writes through connector policy and read-only storage credentials.
- [ ] Repository contract validation and one approved live shadow run retain complete evidence.

## Comments
