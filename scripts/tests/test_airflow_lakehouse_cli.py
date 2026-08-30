"""Tests for the Airflow lakehouse command adapter."""

from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
from io import StringIO
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
sys.path.insert(0, str(LIB))


def _load_command_adapter():
    path = REPO / "scripts" / "airflow-lakehouse.py"
    spec = importlib.util.spec_from_file_location("airflow_lakehouse_command", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AirflowLakehouseCommandTests(unittest.TestCase):
    def test_command_modes_reject_cross_mode_options(self) -> None:
        parser = _load_command_adapter()._parser()
        valid = (
            ("lakehouse-evidence", "--run-id", "run-1", "--target", "shadow"),
            ("flight-recorder-initial-evidence", "--run-id", "run-1",
             "--namespace-baseline", "namespace.json"),
            ("flight-recorder-replay-evidence", "--run-id", "run-2",
             "--baseline", "baseline.json"),
            ("flight-recorder-rejection-evidence", "--run-id", "run-3"),
        )
        for argv in valid:
            with self.subTest(argv=argv):
                parser.parse_args(argv)

        invalid = (
            ("lakehouse-evidence", "--run-id", "run-1", "--baseline", "baseline.json"),
            ("flight-recorder-initial-evidence", "--run-id", "run-1",
             "--baseline", "baseline.json"),
            ("flight-recorder-replay-evidence", "--run-id", "run-2",
             "--namespace-baseline", "namespace.json"),
            ("flight-recorder-rejection-evidence", "--run-id", "run-3",
             "--baseline", "baseline.json"),
        )
        for argv in invalid:
            with (
                self.subTest(argv=argv),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                parser.parse_args(argv)

    def test_task_targets_select_one_evidence_mode(self) -> None:
        source = (REPO / ".taskfiles" / "airflow" / "Taskfile.yaml").read_text(encoding="utf-8")
        for command in (
            "lakehouse-evidence",
            "flight-recorder-initial-evidence",
            "flight-recorder-replay-evidence",
            "flight-recorder-rejection-evidence",
        ):
            self.assertIn(command, source)
        self.assertNotIn("--workflow", source)
        self.assertNotIn("--require-rejected", source)


if __name__ == "__main__":
    unittest.main()
