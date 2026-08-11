#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Collect one target-verified revision observation into an explicit ledger."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import TargetPreflightError  # noqa: E402
from evaluate_revision_convergence import read_cluster_snapshot  # noqa: E402
from revision_convergence import (  # noqa: E402
    DEFAULT_CRITICAL_KUSTOMIZATIONS,
    ObservationError,
    evaluate_revision_convergence,
)
from revision_convergence_ledger import (  # noqa: E402
    LedgerError,
    collect_revision_observation,
    preview_revision_observation,
    read_revision_ledger,
    validate_ledger_path,
)


ObservationProvider = Callable[[], Mapping[str, Any]]
TransitionProvider = Callable[[Path, Mapping[str, Any]], Mapping[str, Any]]


def observe_revision() -> Mapping[str, Any]:
    """Read one target-bound Flux snapshot and return its sanitized observation."""

    source, kustomizations = read_cluster_snapshot()
    return evaluate_revision_convergence(
        source,
        kustomizations,
        critical=DEFAULT_CRITICAL_KUSTOMIZATIONS,
    )


def _summary(result: Mapping[str, Any], *, dry_run: bool) -> dict[str, Any]:
    record = result.get("record")
    aggregate = result.get("aggregate")
    if not isinstance(record, Mapping) or not isinstance(aggregate, Mapping):
        raise LedgerError("collector transition returned an invalid result")
    return {
        "action": result.get("action"),
        "aggregate": dict(aggregate),
        "dry_run": dry_run,
        "record": {
            "admission": record.get("admission"),
            "duration_seconds": record.get("duration_seconds"),
            "revision": record.get("revision"),
            "status": record.get("status"),
        },
    }


def run(
    argv: Sequence[str] | None = None,
    *,
    observation_provider: ObservationProvider = observe_revision,
    persistence_provider: TransitionProvider = collect_revision_observation,
    preview_provider: TransitionProvider = preview_revision_observation,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, prog="collect_revision_convergence.py")
    parser.add_argument("--records-path", required=True, help="approved absolute JSON ledger path")
    parser.add_argument("--dry-run", action="store_true", help="observe and preview without writing files")
    args = parser.parse_args(argv)
    try:
        records_path = Path(args.records_path)
        validate_ledger_path(records_path)
        read_revision_ledger(records_path)
        observation = observation_provider()
        result = (
            preview_provider(records_path, observation)
            if args.dry_run
            else persistence_provider(records_path, observation)
        )
        summary = _summary(result, dry_run=args.dry_run)
    except TargetPreflightError:
        print("revision convergence collection failed: Anton target preflight failed", file=sys.stderr)
        return 1
    except LedgerError as error:
        print(f"revision convergence collection failed: {error}", file=sys.stderr)
        return 1
    except ObservationError:
        print("revision convergence collection failed: observation rejected", file=sys.stderr)
        return 1
    except OSError:
        print("revision convergence collection failed: local state operation failed", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
