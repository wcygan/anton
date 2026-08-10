#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Validate or display Anton's Kubernetes logging contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from kubernetes_log_contract import contract_summary, validate_repository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true", help="print the canonical vocabulary and retention policy")
    args = parser.parse_args()
    if args.show:
        print(contract_summary())
        return 0
    violations = validate_repository(REPO)
    if violations:
        for violation in violations:
            print(violation.render(REPO), file=sys.stderr)
        return 1
    print("Kubernetes logging contract: PASS (fixtures + OTel + Loki + Grafana + queries + pointers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
