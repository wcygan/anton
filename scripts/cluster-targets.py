#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Resolve Anton cluster targets or preflight an operator command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from cluster_target_contract import classify_command, preflight_command, resolve_talos_targets  # noqa: E402


def resolve(args: argparse.Namespace) -> int:
    try:
        result = resolve_talos_targets(REPO, source=args.source)
    except ValueError as error:
        print(f"target resolution failed: {error}", file=sys.stderr)
        return 1
    if args.format in {"mapping", "addresses"}:
        if not args.show_addresses:
            print(f"--format {args.format} requires --show-addresses", file=sys.stderr)
            return 2
        print(result.mapping() if args.format == "mapping" else result.addresses())
    elif args.format == "json":
        print(json.dumps(result.evidence(show_addresses=args.show_addresses), indent=2))
    else:
        evidence = result.evidence(show_addresses=args.show_addresses)
        print(f"source: {evidence['source']}")
        if evidence["fallback_reason"]:
            print(f"fallback: {evidence['fallback_reason']}")
        for node in evidence["nodes"]:
            print(f"{node['name']}\t{node['address']}")
    return 0


def preflight(args: argparse.Namespace) -> int:
    operations = classify_command(args.command)
    for operation in operations:
        print(f"{operation.binary} {operation.subcommand or '<none>'}: {operation.classification}")
    violations = preflight_command(args.command, REPO)
    if violations:
        for violation in violations:
            print(
                f"preflight failed: {violation.binary} {violation.subcommand or '<none>'}: "
                f"{violation.message}; actual={violation.actual!r} expected={violation.expected!r}",
                file=sys.stderr,
            )
        return 1
    print("preflight: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--source", choices=("auto", "live", "fallback"), default="auto")
    resolve_parser.add_argument("--format", choices=("table", "mapping", "addresses", "json"), default="table")
    resolve_parser.add_argument("--show-addresses", action="store_true")
    resolve_parser.set_defaults(handler=resolve)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--command", required=True)
    preflight_parser.set_defaults(handler=preflight)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
