#!/usr/bin/env python3
"""Collect fixed read-only Trino evidence for the Anton lakehouse."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from airflow_lakehouse_operations import OperationError  # noqa: E402
from cluster_target_contract import TargetPreflightError  # noqa: E402
from lakehouse_trino import QUERIES, run_check  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=sorted(QUERIES))
    args = parser.parse_args()
    try:
        print(json.dumps(run_check(ROOT, args.check), indent=2, sort_keys=True))
    except (OperationError, TargetPreflightError) as error:
        print(json.dumps({"error": str(error)}, indent=2), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
