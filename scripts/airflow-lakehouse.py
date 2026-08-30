#!/usr/bin/env python3
"""Run guarded Airflow Spark lakehouse operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from airflow_lakehouse_operations import (  # noqa: E402
    KubectlClient,
    OperationError,
    _image_digest,
)
from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix  # noqa: E402
from lakehouse_trino import TrinoReadError  # noqa: E402
from spark_attempt_evidence import (  # noqa: E402
    FlightRecorderInitialEvidenceRequest,
    FlightRecorderRejectionEvidenceRequest,
    FlightRecorderReplayEvidenceRequest,
    LakehouseEvidenceRequest,
    collect_spark_attempt_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    lakehouse = subcommands.add_parser(
        "lakehouse-evidence",
        help="Collect lakehouse evidence for one exact Spark Attempt.",
    )
    _add_attempt_identity(lakehouse)
    lakehouse.add_argument(
        "--target", choices=("shadow", "authoritative"), default="shadow",
    )
    lakehouse.add_argument("--ledger", type=Path)
    lakehouse.add_argument("--require-complete", action="store_true")

    initial = subcommands.add_parser(
        "flight-recorder-initial-evidence",
        help="Collect initial Flight Recorder evidence.",
    )
    _add_attempt_identity(initial)
    initial.add_argument("--namespace-baseline", required=True, type=Path)

    replay = subcommands.add_parser(
        "flight-recorder-replay-evidence",
        help="Collect exact Flight Recorder replay evidence.",
    )
    _add_attempt_identity(replay)
    replay.add_argument("--baseline", required=True, type=Path)

    rejection = subcommands.add_parser(
        "flight-recorder-rejection-evidence",
        help="Collect one Flight Recorder rejection.",
    )
    _add_attempt_identity(rejection)

    return parser


def _add_attempt_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--try-number", type=int, default=1)


def _redact_command(value: Any) -> Any:
    """Hide a private context name from displayed commands."""
    if not isinstance(value, Mapping):
        return value
    result = dict(value)
    command = result.get("command")
    if isinstance(command, list):
        command = list(command)
        for index, argument in enumerate(command[:-1]):
            if argument == "--context":
                command[index + 1] = "<verified-anton-context>"
        result["command"] = command
    return result


def _main() -> int:
    args = _parser().parse_args()
    prefix = anton_kubectl_prefix(ROOT)
    kubectl = KubectlClient(prefix)
    exit_code = 0

    expected_digest = None
    if args.command == "lakehouse-evidence":
        request = LakehouseEvidenceRequest(
            run_id=args.run_id,
            try_number=args.try_number,
            target=args.target,
            ledger_path=args.ledger,
        )
        expected_status = "complete" if args.require_complete else None
    else:
        expected_digest = _image_digest(
            ROOT / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml",
        )
        if args.command == "flight-recorder-initial-evidence":
            request = FlightRecorderInitialEvidenceRequest(
                run_id=args.run_id,
                try_number=args.try_number,
                namespace_baseline_path=args.namespace_baseline,
            )
            expected_status = "complete"
        elif args.command == "flight-recorder-replay-evidence":
            request = FlightRecorderReplayEvidenceRequest(
                run_id=args.run_id,
                try_number=args.try_number,
                baseline_path=args.baseline,
            )
            expected_status = "complete"
        else:
            request = FlightRecorderRejectionEvidenceRequest(
                run_id=args.run_id,
                try_number=args.try_number,
            )
            expected_status = "rejected"
    result = collect_spark_attempt_evidence(
        request,
        kubectl=kubectl,
        root=ROOT,
        expected_airflow_digest=expected_digest,
    )
    if expected_status is not None and result["status"] != expected_status:
        exit_code = 2
    print(json.dumps(_redact_command(result), indent=2, sort_keys=True))
    return exit_code


def main() -> int:
    try:
        return _main()
    except (OperationError, TargetPreflightError, TrinoReadError, json.JSONDecodeError, OSError) as error:
        print(json.dumps({"error": str(error)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
