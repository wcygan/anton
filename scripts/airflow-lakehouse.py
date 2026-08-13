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
    APPROVAL_TOKEN,
    KubectlClient,
    OperationError,
    collect_attempt_evidence,
    collect_gate_snapshot,
    evaluate_gate_preflight,
    trigger_shadow_run,
)
from airflow_lakehouse_recovery import SCENARIOS, execute_recovery_case  # noqa: E402
from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser(
        "gate-preflight",
        help="Check the repository and live shadow dependencies without mutation.",
    )

    trigger = subcommands.add_parser(
        "trigger-shadow-run",
        help="Plan or create one manual shadow Workflow Run.",
    )
    trigger.add_argument("--run-id", required=True)
    trigger.add_argument("--logical-date")
    trigger.add_argument("--source-window-end")
    trigger.add_argument("--execute", action="store_true")
    trigger.add_argument("--approval-token")

    evidence = subcommands.add_parser(
        "attempt-evidence",
        help="Collect bounded evidence for one exact Spark Attempt.",
    )
    evidence.add_argument("--run-id", required=True)
    evidence.add_argument("--try-number", type=int, default=1)
    evidence.add_argument("--ledger", type=Path)
    evidence.add_argument("--require-complete", action="store_true")

    recovery = subcommands.add_parser(
        "recovery-case",
        help="Plan or execute one bounded shadow recovery case.",
    )
    recovery.add_argument("--case", choices=SCENARIOS, required=True)
    recovery.add_argument("--run-id", required=True)
    recovery.add_argument("--timeout-seconds", type=float, default=600)
    recovery.add_argument("--execute", action="store_true")
    recovery.add_argument("--approval-token")
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


def _gate(kubectl: KubectlClient) -> dict[str, Any]:
    return evaluate_gate_preflight(collect_gate_snapshot(ROOT, kubectl))


def _main() -> int:
    args = _parser().parse_args()
    prefix = anton_kubectl_prefix(ROOT)
    kubectl = KubectlClient(prefix)
    exit_code = 0

    if args.command == "gate-preflight":
        result = _gate(kubectl)
        exit_code = 0 if result["ready"] else 2
    elif args.command == "trigger-shadow-run":
        preflight = _gate(kubectl) if args.execute else None
        if preflight is not None and not preflight["ready"]:
            identifiers = [item["id"] for item in preflight["blockers"]]
            raise OperationError(f"gate preflight blocked trigger: {', '.join(identifiers)}")
        result = trigger_shadow_run(
            kubectl,
            run_id=args.run_id,
            logical_date=args.logical_date,
            source_window_end=args.source_window_end,
            execute=args.execute,
            approval_token=args.approval_token,
        )
        if preflight is not None:
            result["preflight"] = preflight
    elif args.command == "attempt-evidence":
        result = collect_attempt_evidence(
            kubectl,
            run_id=args.run_id,
            try_number=args.try_number,
            ledger_path=args.ledger,
        )
        if args.require_complete and result["status"] != "complete":
            exit_code = 2
    else:
        result = execute_recovery_case(
            ROOT,
            kubectl,
            scenario=args.case,
            run_id=args.run_id,
            execute=args.execute,
            approval_token=args.approval_token,
            timeout_seconds=args.timeout_seconds,
        )

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
