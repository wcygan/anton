#!/usr/bin/env python3
"""Audit rebuild source coverage and detect Harbor-dependent bootstrap images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "scripts/data/rebuild-prerequisites.json"
IMAGE_FIELD = re.compile(r"^\s*image:\s*['\"]?([^\s'\"]+)")


def audit(root: Path, contract: dict) -> tuple[list[dict[str, str]], bool]:
    """Return findings as PASS/UNKNOWN/FAIL and whether a pre-Harbor image is unresolved."""
    findings: list[dict[str, str]] = []
    stages = contract["stages"]
    stage_index = {name: index for index, name in enumerate(stages)}

    for path in contract["required_paths"]:
        exists = (root / path).exists()
        findings.append({
            "status": "PASS" if exists else "FAIL",
            "subject": path,
            "detail": "declared source present" if exists else "declared source missing",
        })

    for name in stages:
        detail = contract["stage_details"][name]
        findings.append({
            "status": "INFO",
            "subject": f"stage {name}",
            "detail": f"order={detail['order']} owner={detail['owner']} origin={detail['origin']}",
        })

    pre_harbor_image_unresolved = False
    harbor_index = stage_index[contract["harbor_stage"]]
    for scan_root in contract["scan_roots"]:
        for manifest in sorted((root / scan_root).rglob("*.yaml")):
            if ".sops." in manifest.name:
                continue
            relative = manifest.relative_to(root).as_posix()
            stage = next((name for name in stages if any(
                relative.startswith(prefix) for prefix in contract["stage_paths"].get(name, [])
            )), None)
            try:
                lines = manifest.read_text(encoding="utf-8").splitlines()
            except OSError:
                findings.append({"status": "UNKNOWN", "subject": relative,
                                 "detail": "manifest could not be read"})
                continue
            for number, line in enumerate(lines, start=1):
                match = IMAGE_FIELD.match(line)
                if not match or contract["private_registry_host"] not in match.group(1):
                    continue
                image = match.group(1)
                if stage is None:
                    detail = f"stage assignment is undeclared for private image {image}; rebuild order is unknown"
                else:
                    before_harbor = stage_index[stage] < harbor_index
                    pre_harbor_image_unresolved |= before_harbor
                    detail = (f"potential cold-start cycle: {stage} references {image} at Harbor; "
                              "Spegel can serve existing node cache, but cache survival/seeding for a rebuild is unverified"
                              if before_harbor else
                              f"private image {image} availability is not independently verified")
                findings.append({"status": "UNKNOWN", "subject": f"{relative}:{number}", "detail": detail})

    for item in contract["unverified_inputs"]:
        findings.append({"status": "UNKNOWN", "subject": item,
                         "detail": "not observable from committed source; requires operator or external evidence"})
    return findings, pre_harbor_image_unresolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    parser.add_argument("--contract", type=Path, default=CONTRACT, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="emit machine-readable findings")
    args = parser.parse_args()

    try:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        ordered_stages = [contract["stage_details"][stage]["order"] for stage in contract["stages"]]
        if contract.get("schema") != 1 or not contract["required_paths"] or \
                contract["harbor_stage"] not in contract["stages"] or \
                any(stage not in contract["stage_details"] for stage in contract["stages"]) or \
                ordered_stages != sorted(ordered_stages):
            raise ValueError("unsupported or inconsistent rebuild contract")
        findings, pre_harbor_image_unresolved = audit(args.root.resolve(), contract)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: invalid rebuild audit input ({error})", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        for finding in findings:
            print(f"{finding['status']:7} {finding['subject']} — {finding['detail']}")
        counts = {status: sum(f["status"] == status for f in findings)
                  for status in ("PASS", "UNKNOWN", "FAIL")}
        print("Totals: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
        print("Scope: committed source audit only; no live cluster or secret values inspected")

    if any(f["status"] == "FAIL" for f in findings):
        return 1
    if pre_harbor_image_unresolved or any(f["status"] == "UNKNOWN" for f in findings):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
