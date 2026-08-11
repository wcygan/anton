#!/usr/bin/env python3
"""Measure Anton platform stability through the Kubernetes Prometheus proxy."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix  # noqa: E402
from platform_stability import evaluate, parse_observed_at  # noqa: E402


def verified_kubectl_prefix() -> tuple[str, ...]:
    """Return a kubectl prefix bound to the verified Anton target."""

    return anton_kubectl_prefix(REPO)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-at", metavar="RFC3339", help="evaluation end time; include an offset")
    args = parser.parse_args(argv)
    try:
        observed_at = parse_observed_at(args.observed_at)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    try:
        report = evaluate(observed_at, prefix_provider=verified_kubectl_prefix)
    except TargetPreflightError as error:
        print(f"platform stability observation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
