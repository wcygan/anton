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
    collect_attempt_evidence,
)
from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix  # noqa: E402
from flight_recorder_evidence import add_flight_recorder_checks  # noqa: E402
from lakehouse_trino import TrinoReadError  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    evidence = subcommands.add_parser(
        "attempt-evidence",
        help="Collect bounded evidence for one exact Spark Attempt.",
    )
    evidence.add_argument("--run-id", required=True)
    evidence.add_argument("--try-number", type=int, default=1)
    evidence.add_argument("--target", choices=("shadow", "authoritative"), default="shadow")
    evidence.add_argument("--workflow", choices=("lakehouse", "flight-recorder"), default="lakehouse")
    evidence.add_argument("--ledger", type=Path)
    evidence.add_argument("--baseline", type=Path)
    evidence.add_argument("--namespace-baseline", type=Path)
    required_state = evidence.add_mutually_exclusive_group()
    required_state.add_argument("--require-complete", action="store_true")
    required_state.add_argument("--require-rejected", action="store_true")

    return parser


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

    if args.command == "attempt-evidence":
        expected_digest = (
            _image_digest(ROOT / "kubernetes/apps/airflow/airflow/app/helmrelease.yaml")
            if args.workflow == "flight-recorder" else None
        )
        result = collect_attempt_evidence(
            kubectl,
            run_id=args.run_id,
            try_number=args.try_number,
            target=args.target,
            workflow=args.workflow,
            expected_airflow_digest=expected_digest,
            ledger_path=args.ledger,
        )
        if args.workflow == "flight-recorder":
            add_flight_recorder_checks(
                result,
                args.baseline,
                root=ROOT,
                namespace_baseline_path=args.namespace_baseline,
            )
        if args.require_complete and result["status"] != "complete":
            exit_code = 2
        if args.require_rejected and result["status"] != "rejected":
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
