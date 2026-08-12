# 07 — Pass the five-run shadow gate

**What to build:** Demonstrate repeated, compatible, read-only validated operation on Anton before any authoritative writer transfer.

**Blocked by:** 06 — Prove failure and recovery paths.

**Status:** ready-for-agent

- [ ] Five consecutive scheduled or equivalent Workflow Runs pass against the shadow target.
- [ ] Every run uses the expected Spark image digest and Apache `SparkApplication` control plane.
- [ ] Every run passes Trino schema, count, partition, snapshot, location, and time-travel checks.
- [ ] Trino write-denial tests pass for both authoritative and shadow catalogs.
- [ ] Authoritative table metadata and data remain unchanged during all shadow runs.
- [ ] Kubernetes 1.36 acceptance covers Airflow task pods, custom-resource observation, and Spark workloads.
- [ ] Runtime identity, classpath, S3FileIO, S3A, Loki, and History Server evidence remains complete.
- [ ] Any unexplained failure resets the consecutive-run count.
- [ ] A Spark 4.1.3 blocker follows the documented repair and compatibility ladder before fallback.
- [ ] No fallback changes the Apache `SparkApplication` architecture.
- [ ] Cutover remains blocked unless every mandatory criterion has retained evidence.

## Comments
