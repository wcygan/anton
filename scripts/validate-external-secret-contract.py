#!/usr/bin/env python3
"""Validate approved ESO references, output keys, and scheduled traffic."""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from external_secret_contract import (  # noqa: E402
    load_external_secrets,
    load_inventory,
    load_yaml_documents,
    validate_admission_guard,
    validate_contract,
)


def main() -> int:
    inventory = load_inventory(REPO / "scripts" / "data" / "external-secret-contract.json")
    try:
        documents = load_external_secrets(REPO)
        admission_documents = load_yaml_documents(
            REPO,
            REPO
            / "kubernetes"
            / "apps"
            / "external-secrets"
            / "external-secrets"
            / "app"
            / "admission-policy.yaml",
        )
    except (OSError, ValueError) as error:
        print(f"[external-secrets.contract] {error}", file=sys.stderr)
        return 1
    report = validate_contract(documents, inventory)
    failures = report.failures + validate_admission_guard(admission_documents)
    if failures:
        for failure in failures:
            print(f"[external-secrets.contract] {failure}", file=sys.stderr)
        return 1
    print(
        "ExternalSecret contract: PASS "
        f"({report.manifest_count} manifests, "
        f"{report.scheduled_operations}/{inventory['dailyOperationLimit']} "
        "estimated scheduled operations daily)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
