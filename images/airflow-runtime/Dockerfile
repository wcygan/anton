# syntax=docker/dockerfile:1.7

ARG AIRFLOW_BASE_IMAGE=apache/airflow:3.2.2-python3.12@sha256:bbe58e3204d550ab98dbf738a42c0e6663c455357ecd0e2d1440ef9cb6a75f00

FROM ${AIRFLOW_BASE_IMAGE} AS runtime

ARG AIRFLOW_VERSION=3.2.2
ARG PYTHON_VERSION=3.12
ARG KUBERNETES_PROVIDER_VERSION=10.21.0
ARG OFFICIAL_PROVIDER_VERSION=10.17.1
ARG AIRFLOW_CONSTRAINTS_SHA256=dd09ca7bc7da06f209dbc57005c38beccad9464e8d33e55598519d904e798c85

ENV AIRFLOW_VERSION=${AIRFLOW_VERSION} \
    PYTHON_VERSION=${PYTHON_VERSION} \
    KUBERNETES_PROVIDER_VERSION=${KUBERNETES_PROVIDER_VERSION} \
    OFFICIAL_PROVIDER_VERSION=${OFFICIAL_PROVIDER_VERSION} \
    AIRFLOW_CONSTRAINTS_SHA256=${AIRFLOW_CONSTRAINTS_SHA256}

USER airflow

# Start from Airflow's release constraints. Replace only the Kubernetes
# provider pin required by ADR 0033. Keep every other official pin unchanged.
RUN python - <<'PY'
import hashlib
import os
from pathlib import Path
from urllib.request import urlopen

airflow_version = os.environ.get("AIRFLOW_VERSION", "3.2.2")
python_version = os.environ.get("PYTHON_VERSION", "3.12")
expected_hash = os.environ.get(
    "AIRFLOW_CONSTRAINTS_SHA256",
    "dd09ca7bc7da06f209dbc57005c38beccad9464e8d33e55598519d904e798c85",
)
official_provider = os.environ.get("OFFICIAL_PROVIDER_VERSION", "10.17.1")
selected_provider = os.environ.get("KUBERNETES_PROVIDER_VERSION", "10.21.0")
url = (
    "https://raw.githubusercontent.com/apache/airflow/"
    f"constraints-{airflow_version}/constraints-{python_version}.txt"
)
payload = urlopen(url, timeout=30).read()
actual_hash = hashlib.sha256(payload).hexdigest()
if actual_hash != expected_hash:
    raise SystemExit(f"Airflow constraints checksum mismatch: {actual_hash}")

source = payload.decode("utf-8")
old = f"apache-airflow-providers-cncf-kubernetes=={official_provider}"
new = f"apache-airflow-providers-cncf-kubernetes=={selected_provider}"
if source.count(old) != 1:
    raise SystemExit("Airflow constraints Kubernetes provider pin changed")
Path("/tmp/constraints.txt").write_text(source.replace(old, new), encoding="utf-8")
PY

RUN pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      "apache-airflow-providers-cncf-kubernetes==${KUBERNETES_PROVIDER_VERSION}" \
      --constraint /tmp/constraints.txt \
    && pip check \
    && rm /tmp/constraints.txt

ENV PYTHONPATH=/opt/airflow/lib

COPY --chown=airflow:0 images/airflow-runtime/src/ /opt/airflow/lib/
COPY --chown=airflow:0 images/airflow-runtime/dags/ /opt/airflow/dags/

RUN python - <<'PY'
import sys
from importlib.metadata import version

import airflow
import anton_airflow.spark

assert airflow.__version__ == "3.2.2"
assert sys.version_info[:2] == (3, 12)
assert version("apache-airflow-providers-cncf-kubernetes") == "10.21.0"
assert anton_airflow.spark.PACKAGE_VERSION == "0.2.0"
PY

FROM runtime AS test

COPY --chown=airflow:0 images/airflow-runtime/tests/ /tmp/airflow-runtime-tests/

RUN python -m unittest discover -s /tmp/airflow-runtime-tests -p 'test_*.py' \
    && printf '%s\n' 'Airflow runtime tests: PASS' >/tmp/airflow-runtime-tests.pass

FROM runtime AS final

COPY --from=test /tmp/airflow-runtime-tests.pass /opt/airflow/runtime-contract/tests.pass
