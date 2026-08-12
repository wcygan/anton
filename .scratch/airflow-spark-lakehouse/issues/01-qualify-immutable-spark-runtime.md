# 01 — Qualify the immutable Spark runtime

**What to build:** Produce one digest-pinned Spark runtime that proves its complete dependency identity and can use both required SeaweedFS object-storage paths.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The primary runtime uses Spark 4.1.3, Scala 2.13, Java 21, Python 3.12, Iceberg 1.11.0, and Hadoop 3.4.2.
- [ ] The final image is pinned by digest and performs no runtime dependency downloads.
- [ ] The build records its resolved dependency tree, JAR inventory, SHA-256 hashes, Hadoop version, and AWS SDK version.
- [ ] One AWS SDK v2 family serves Iceberg S3FileIO and Hadoop S3A without incompatible duplicate classes.
- [ ] Driver and executor checks report the required Spark, Scala, Java, and Python versions from inside the image.
- [ ] Iceberg S3FileIO can write and read through SeaweedFS from the final image.
- [ ] Hadoop S3A can write and read through SeaweedFS from the final image.
- [ ] The runtime contract has repeatable repository validation and retained evidence.

## Comments
