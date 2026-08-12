# Build context: repository root. The final image makes no dependency downloads.
FROM ubuntu:22.04@sha256:3b06811b2afd352be909dd088a004166d665dc76d38b13eada33522a9d915c6f AS python
ARG PYTHON_VERSION=3.12.11
ARG PYTHON_SHA256=7b8d59af8216044d2313de8120bfc2cc00a9bd2e542f15795e1d616c51faf3d6
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
      build-essential ca-certificates curl libbz2-dev libffi-dev libgdbm-dev \
      liblzma-dev libncursesw5-dev libreadline-dev libsqlite3-dev libssl-dev zlib1g-dev \
 && curl --fail --location --silent --show-error \
      "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" \
      --output /tmp/python.tgz \
 && echo "${PYTHON_SHA256}  /tmp/python.tgz" | sha256sum --check \
 && tar --extract --file /tmp/python.tgz --directory /tmp \
 && cd "/tmp/Python-${PYTHON_VERSION}" \
 && ./configure --prefix=/opt/python --enable-shared --without-ensurepip \
 && make -j2 \
 && make install

FROM maven:3.9.12-eclipse-temurin-21@sha256:c3c9d3ac4ce8431a3995c0318b8d390f448e693dd4fabc16e9b68d2e1f3d7b46 AS dependencies
WORKDIR /build
COPY images/spark-runtime/pom.xml ./pom.xml
RUN mvn --batch-mode --no-transfer-progress dependency:tree -DoutputFile=/build/dependency-tree.txt \
 && mvn --batch-mode --no-transfer-progress dependency:copy-dependencies \
      -DincludeScope=runtime -DoutputDirectory=/build/jars

FROM apache/spark:4.1.3-scala2.13-java21-python3-ubuntu@sha256:bf9d035a7c32a8ca46aa58d6348182ffd7d2dff6409206ecfbb3915ff1fef211
USER root
COPY --from=python /opt/python /opt/python
COPY --from=dependencies /build/jars/ /opt/spark/jars/
COPY --from=dependencies /build/dependency-tree.txt /opt/spark/runtime-contract/dependency-tree.txt
COPY images/spark-runtime/verify-runtime.py /opt/spark/runtime-contract/verify-runtime.py
COPY images/iceberg-log-spark/transform.py /opt/spark/work-dir/transform.py
COPY images/iceberg-log-spark/fixture.jsonl /opt/spark/work-dir/fixture.jsonl
ENV PATH=/opt/python/bin:${PATH} \
    LD_LIBRARY_PATH=/opt/python/lib \
    PYSPARK_PYTHON=/opt/python/bin/python3.12 \
    PYTHONPATH=/opt/spark/python/lib/pyspark.zip:/opt/spark/python/lib/py4j-0.10.9.9-src.zip
RUN python3 --version | grep -E '^Python 3[.]12[.]' \
 && python3 /opt/spark/runtime-contract/verify-runtime.py --build \
 && chown -R 185:185 /opt/spark/jars /opt/spark/runtime-contract /opt/spark/work-dir
USER 185
