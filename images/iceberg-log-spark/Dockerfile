# Build context: repository root. Every dependency is version-pinned; record
# the resulting image digest in spark-fixture/app/job.yaml before rollout.
# Digest observed during the offline build; keep the Harbor release input
# reproducible instead of resolving the mutable upstream tag at rollout time.
FROM apache/spark:4.2.0-python3@sha256:fc64959c04bd87b0ac686be9aaa9008b69cdb1afc695400528279c8b01f43d89

USER root
ARG ICEBERG_VERSION=1.5.2
ADD https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/${ICEBERG_VERSION}/iceberg-spark-runtime-3.5_2.12-${ICEBERG_VERSION}.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/${ICEBERG_VERSION}/iceberg-aws-bundle-${ICEBERG_VERSION}.jar /opt/spark/jars/
COPY images/iceberg-log-spark/transform.py /opt/spark/work-dir/transform.py
COPY images/iceberg-log-spark/fixture.jsonl /opt/spark/work-dir/fixture.jsonl
RUN chown -R 185:185 /opt/spark/jars /opt/spark/work-dir
USER 185
