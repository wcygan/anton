"""Local integration tests for the manual Flight Recorder workflow."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

IMAGE_ROOT = Path("/opt/airflow")
if (IMAGE_ROOT / "lib" / "anton_airflow").is_dir():
    SOURCE, DAGS = IMAGE_ROOT / "lib", IMAGE_ROOT / "dags"
else:
    RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "images" / "airflow-runtime"
    SOURCE, DAGS = RUNTIME_ROOT / "src", RUNTIME_ROOT / "dags"
PACKAGE = "flight_recorder_workflow_test"
sys.path.insert(0, str(SOURCE))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = ModuleType(PACKAGE)
spark_package = ModuleType(f"{PACKAGE}.spark")
package.__path__, spark_package.__path__ = [], []
sys.modules.update({PACKAGE: package, f"{PACKAGE}.spark": spark_package})
LOKI = load_module(f"{PACKAGE}.loki", SOURCE / "anton_airflow" / "loki.py")
IDENTITY = load_module(f"{PACKAGE}.spark.identity", SOURCE / "anton_airflow" / "spark" / "identity.py")


class StubLog:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, template: str, payload: str) -> None:
        self.messages.append(template.replace("%s", payload))

class StubSparkOperator:
    template_fields = ("application_spec", "target")
    active_dag = None

    def __init__(self, *, application_spec, target="shadow", namespace="lakehouse", **kwargs):
        self.application_spec = dict(application_spec)
        self.target = target
        self.namespace = namespace
        self.log = StubLog()
        self.submitted_spec = None
        for name, value in kwargs.items():
            setattr(self, name, value)
        if self.active_dag is not None:
            self.active_dag.tasks[self.task_id] = self

    def execute(self, _context):
        self.submitted_spec = deepcopy(self.application_spec)
        return {"application_spec": self.submitted_spec}


operator_module = ModuleType(f"{PACKAGE}.spark.operator")
operator_module.ApacheSparkApplicationOperator = StubSparkOperator
exceptions_module = ModuleType("airflow.exceptions")


class AirflowException(Exception):
    pass


exceptions_module.AirflowException = AirflowException
with patch.dict(sys.modules, {
    "airflow": ModuleType("airflow"),
    "airflow.exceptions": exceptions_module,
    f"{PACKAGE}.spark.operator": operator_module,
}):
    WORKFLOW = load_module(f"{PACKAGE}.flight_recorder", SOURCE / "anton_airflow" / "flight_recorder.py")
LAKEHOUSE = load_module(f"{PACKAGE}.lakehouse", SOURCE / "anton_airflow" / "lakehouse.py")


class FlightRecorderWorkflowTests(unittest.TestCase):
    end = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    secret = "test-secret-must-not-appear"

    def operator(self):
        hour = LOKI.LokiHour.ending_at(self.end)
        sources = []
        for component, query in LOKI.COMPONENT_QUERIES:
            for chunk_index, window in enumerate(hour.chunks):
                identity = f"{component}-{chunk_index}".encode()
                raw_sha256 = hashlib.sha256(b"raw-" + identity).hexdigest()
                sources.append(LOKI.CompleteHourSource(
                    component=component,
                    chunk_index=chunk_index,
                    entry_limit=LOKI.COMPLETE_HOUR_QUERY_LIMITS.entry_limit,
                    max_response_bytes=LOKI.COMPLETE_HOUR_QUERY_LIMITS.max_response_bytes,
                    timeout_seconds=LOKI.COMPLETE_HOUR_QUERY_LIMITS.timeout_seconds,
                    manifest_key=LOKI.component_manifest_key(
                        component=component,
                        query=query,
                        window=window,
                        limits=LOKI.COMPLETE_HOUR_QUERY_LIMITS,
                    ),
                    manifest_sha256=hashlib.sha256(b"manifest-" + identity).hexdigest(),
                    query=query,
                    window_start=window.start.isoformat().replace("+00:00", "Z"),
                    window_end=window.end.isoformat().replace("+00:00", "Z"),
                    entry_count=7 if len(sources) < 24 else 6,
                    raw_bytes=875,
                    raw_key=LOKI.raw_key(window=window, checksum=raw_sha256),
                    raw_sha256=raw_sha256,
                ))
        manifest = LOKI.CompleteHourManifest(
            schema_version=LOKI.COMPLETE_HOUR_SCHEMA_VERSION,
            kind="flight_recorder_complete_hour",
            status="complete",
            hour_start=hour.start.isoformat().replace("+00:00", "Z"),
            hour_end=hour.end.isoformat().replace("+00:00", "Z"),
            source_hour_id=f"{hour.start_ns}-{hour.end_ns}",
            catalog_sha256=LOKI.complete_hour_contract.component_catalog_sha256(),
            component_count=len(LOKI.COMPONENT_QUERIES),
            chunk_count=len(sources),
            source_count=sum(source.entry_count for source in sources),
            raw_bytes=sum(source.raw_bytes for source in sources),
            sources=tuple(sources),
        )

        class Extractor:
            def __init__(self) -> None:
                self.calls = []

            def capture_hour(self, *, hour):
                self.calls.append(hour)
                return manifest

        extractor = Extractor()
        factory = lambda: (extractor, "iceberg-raw") if self.secret else None
        operator = WORKFLOW.FlightRecorderSparkOperator(
            task_id="run_flight_recorder_spark_attempt",
            application_spec=LAKEHOUSE.FLIGHT_RECORDER_APPLICATION_SPEC,
            extractor_factory=factory,
            target="authoritative",
            namespace="lakehouse",
        )
        return operator, extractor, manifest, hour

    def context(self, source_end: str | None = "2026-08-14T12:00:00Z"):
        conf = {} if source_end is None else {"source_window_end": source_end}
        return {
            "dag_run": SimpleNamespace(conf=conf, run_id="manual__flight-recorder"),
            "dag_id": "airflow_flight_recorder",
            "run_id": "manual__flight-recorder",
            "task_id": "run_flight_recorder_spark_attempt",
            "map_index": -1,
            "try_number": 1,
        }

    def test_complete_hour_manifest_is_the_only_injected_source(self) -> None:
        operator, extractor, manifest, hour = self.operator()
        result = operator.execute(self.context())
        self.assertEqual(extractor.calls, [hour])
        manifest_key = LOKI.hour_manifest_key(hour=hour, checksum=manifest.manifest_sha256)
        values = {
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_URI": f"s3a://iceberg-raw/{manifest_key}",
            "FLIGHT_RECORDER_COMPLETE_MANIFEST_SHA256": manifest.manifest_sha256,
            "FLIGHT_RECORDER_SOURCE_HOUR_ID": manifest.source_hour_id,
        }
        application = result["application_spec"]
        for role in ("driver", "executor"):
            container = application["spec"][f"{role}Spec"]["podTemplateSpec"]["spec"]["containers"][0]
            environment = {item["name"]: item["value"] for item in container["env"]}
            self.assertTrue(values.items() <= environment.items())
            for retired in ("FLIGHT_RECORDER_RAW_URI", "FLIGHT_RECORDER_RAW_SHA256"):
                self.assertNotIn(retired, environment)
        annotations = application["metadata"]["annotations"]
        for name, value in values.items():
            self.assertEqual(annotations[f"anton.io/{name.lower().replace('_', '-')}"] , value)
        prefix, payload = operator.log.messages[0].split(" ", 1)
        receipt = json.loads(payload)
        self.assertEqual(prefix, "flight_recorder_hour_receipt")
        self.assertEqual((receipt["component_count"], receipt["chunk_count"], receipt["source_count"]), (4, 48, 312))
        self.assertEqual(receipt["manifest_key"], manifest_key)
        self.assertEqual(receipt["manifest_sha256"], manifest.manifest_sha256)
        self.assertNotIn("sources", receipt)
        serialized = json.dumps({"receipt": receipt, "application": application}, sort_keys=True)
        for secret in (self.secret, "RAW_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"):
            self.assertNotIn(secret, serialized)
        self.assertEqual((operator.target, operator.namespace), ("authoritative", "lakehouse"))

    def test_invalid_source_end_fails_before_capture_or_submission(self) -> None:
        for value in (
            None,
            "2026-08-14T12:05:00Z",
            "2026-08-14T12:00:00-05:00",
            "2999-08-14T12:00:00Z",
        ):
            operator, extractor, _, _ = self.operator()
            with self.subTest(value=value), self.assertRaises(AirflowException):
                operator.execute(self.context(value))
            self.assertEqual(extractor.calls, [])
            self.assertIsNone(operator.submitted_spec)

    def test_failed_hour_is_receipted_and_never_submitted(self) -> None:
        operator, extractor, _, _ = self.operator()

        def fail(*, hour):
            raise LOKI.LokiHourCaptureError(
                component="trino", chunk_index=4, completed_queries=28,
            )

        extractor.capture_hour = fail
        with self.assertRaises(AirflowException):
            operator.execute(self.context())
        self.assertIsNone(operator.submitted_spec)
        prefix, payload = operator.log.messages[0].split(" ", 1)
        self.assertEqual("flight_recorder_hour_rejection", prefix)
        self.assertEqual(
            {"attempt": "lh-airflow-run-flig-1e20acc910bd-a1",
             "component": "trino", "chunk_index": 4, "completed_queries": 28,
             "complete_manifest_published": False,
             "source_hour_id": "1786705200000000000-1786708800000000000"},
            json.loads(payload),
        )

    def test_ambiguous_manifest_publication_is_not_accepted_as_absent(self) -> None:
        operator, extractor, _, _ = self.operator()

        def fail(*, hour):
            raise LOKI.LokiPublicationAmbiguousError("write state is unknown")

        extractor.capture_hour = fail
        with self.assertRaises(AirflowException):
            operator.execute(self.context())
        payload = json.loads(operator.log.messages[0].split(" ", 1)[1])
        self.assertIsNone(payload["complete_manifest_published"])
        self.assertIsNone(operator.submitted_spec)

    def test_manual_dag_uses_exact_targets_and_secret_wiring(self) -> None:
        class Model:
            def __init__(self, **values):
                self.__dict__.update(values)

        class Dag:
            def __init__(self, values):
                self.__dict__.update(values)
                self.tasks = {}

            def get_task(self, name):
                return self.tasks[name]

        def dag(**values):
            def decorate(function):
                def create():
                    result = Dag(values)
                    StubSparkOperator.active_dag = result
                    try:
                        function()
                    finally:
                        StubSparkOperator.active_dag = None
                    return result
                return create
            return decorate

        airflow, airflow_sdk = ModuleType("airflow"), ModuleType("airflow.sdk")
        airflow_sdk.dag = dag
        airflow.sdk = airflow_sdk
        kubernetes, kubernetes_client = ModuleType("kubernetes"), ModuleType("kubernetes.client")
        kubernetes_client.models = SimpleNamespace(
            V1EnvFromSource=Model, V1SecretEnvSource=Model, V1Container=Model,
            V1Pod=Model, V1PodSpec=Model,
        )
        kubernetes.client = kubernetes_client
        pendulum = ModuleType("pendulum")
        pendulum.datetime = lambda *args, **kwargs: datetime(*args, tzinfo=timezone.utc)
        with patch.dict(sys.modules, {
            "airflow": airflow,
            "airflow.sdk": airflow_sdk,
            "kubernetes": kubernetes,
            "kubernetes.client": kubernetes_client,
            "pendulum": pendulum,
            "anton_airflow.flight_recorder": WORKFLOW,
            "anton_airflow.lakehouse": LAKEHOUSE,
        }):
            module = load_module(
                f"{PACKAGE}.dag",
                DAGS / "airflow_flight_recorder.py",
            )
        dag_object = module.flight_recorder_dag
        self.assertIsNone(dag_object.schedule)
        self.assertFalse(dag_object.catchup)
        self.assertEqual(dag_object.max_active_runs, 1)
        task = dag_object.get_task("run_flight_recorder_spark_attempt")
        self.assertEqual((task.target, task.namespace), ("authoritative", "lakehouse"))
        self.assertEqual(task.application_spec["spec"]["pyFiles"], "local:///opt/spark/application/flight_recorder.py")
        for role in ("driver", "executor"):
            container = task.application_spec["spec"][f"{role}Spec"]["podTemplateSpec"]["spec"]["containers"][0]
            self.assertEqual(container["envFrom"], [{"secretRef": {"name": "flight-recorder-s3"}}])
        raw_secret = task.executor_config["pod_override"].spec.containers[0].env_from[0]
        self.assertEqual(raw_secret.secret_ref.name, "flight-recorder-raw-s3")


if __name__ == "__main__":
    unittest.main()
