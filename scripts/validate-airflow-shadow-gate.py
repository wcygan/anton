#!/usr/bin/env python3
"""Validate one retained five-run Airflow shadow-gate ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from airflow_shadow_gate import (  # noqa: E402
    ShadowGateError,
    evaluate_shadow_gate,
    expected_spark_image_digest,
    load_shadow_gate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True, help="JSON evidence ledger path")
    parser.add_argument(
        "--dag",
        type=Path,
        default=REPO / "images" / "airflow-runtime" / "dags" / "airflow_spark_lakehouse.py",
        help="Airflow DAG source containing the expected Spark image digest",
    )
    args = parser.parse_args(argv)
    try:
        ledger = load_shadow_gate(args.ledger)
        expected_digest = expected_spark_image_digest(args.dag)
        result = evaluate_shadow_gate(
            ledger,
            expected_digest=expected_digest,
            evidence_root=args.ledger.parent,
        )
    except ShadowGateError as error:
        print(json.dumps({"eligible": False, "errors": [str(error)]}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
