#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read Flux revision convergence state without modifying the cluster."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from revision_convergence import (  # noqa: E402
    DEFAULT_CRITICAL_KUSTOMIZATIONS,
    ObservationError,
    evaluate_revision_convergence,
    parse_utc_timestamp,
)
from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix  # noqa: E402


JsonRunner = Callable[[list[str]], Mapping[str, Any]]
KubectlPrefixProvider = Callable[[], tuple[str, ...]]


def verified_kubectl_prefix() -> tuple[str, ...]:
    """Return a kubectl prefix bound to the verified Anton target."""

    return anton_kubectl_prefix(REPO)


def kubectl_json(command: list[str]) -> Mapping[str, Any]:
    """Run one read-only kubectl JSON command."""

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except OSError as error:
        raise ObservationError("cannot run read-only kubectl command") from error
    except subprocess.TimeoutExpired as error:
        raise ObservationError("read-only kubectl command timed out") from error
    if result.returncode != 0:
        raise ObservationError("read-only kubectl command failed")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ObservationError("kubectl returned invalid JSON") from error
    if not isinstance(data, Mapping):
        raise ObservationError("kubectl returned a non-object JSON value")
    return data


def read_cluster_snapshot(
    *,
    source_namespace: str = "flux-system",
    source_name: str = "flux-system",
    runner: JsonRunner = kubectl_json,
    prefix_provider: KubectlPrefixProvider = verified_kubectl_prefix,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Read only the GitRepository and Kustomization resources for one observation."""

    prefix = list(prefix_provider())
    source = runner(
        [
            *prefix,
            "-n",
            source_namespace,
            "get",
            "gitrepositories.source.toolkit.fluxcd.io",
            source_name,
            "-o",
            "json",
        ]
    )
    kustomizations = runner(
        [
            *prefix,
            "get",
            "kustomizations.kustomize.toolkit.fluxcd.io",
            "-A",
            "-o",
            "json",
        ]
    )
    return source, kustomizations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, prog="evaluate_revision_convergence.py")
    parser.add_argument("--observed-at", help="RFC 3339 time for a reproducible observation")
    args = parser.parse_args(argv)
    try:
        observed_at = parse_utc_timestamp(args.observed_at) if args.observed_at else None
        source, kustomizations = read_cluster_snapshot()
        observation = evaluate_revision_convergence(
            source,
            kustomizations,
            critical=DEFAULT_CRITICAL_KUSTOMIZATIONS,
            observed_at=observed_at,
        )
    except (ObservationError, TargetPreflightError) as error:
        print(f"revision convergence observation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(observation, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
