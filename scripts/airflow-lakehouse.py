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
    collect_attempt_evidence,
)
from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix  # noqa: E402


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
    evidence.add_argument("--ledger", type=Path)
    evidence.add_argument("--require-complete", action="store_true")

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
        result = collect_attempt_evidence(
            kubectl,
            run_id=args.run_id,
            try_number=args.try_number,
            target=args.target,
            ledger_path=args.ledger,
        )
        if args.require_complete and result["status"] != "complete":
            exit_code = 2
    print(json.dumps(_redact_command(result), indent=2, sort_keys=True))
    return exit_code


def main() -> int:
    try:
        return _main()
    except (OperationError, TargetPreflightError) as error:
        print(json.dumps({"error": str(error)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
