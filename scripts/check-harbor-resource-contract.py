#!/usr/bin/env python3
"""Render the pinned Harbor chart and check registry container reservations."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELM_RELEASE = ROOT / "kubernetes/apps/registries/harbor/app/helmrelease.yaml"
CHART_VERSION = "1.19.2"
CHART_URL = f"https://helm.goharbor.io/harbor-{CHART_VERSION}.tgz"
EXPECTED = {
    "registry": {"cpu": "100m", "memory": "256Mi"},
    "registryctl": {"cpu": "10m", "memory": "64Mi"},
}
EXPECTED_LIMITS = {"registry": {"memory": "512Mi"}}


def run(*command: str) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(
            f"{' '.join(command)} failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    return completed.stdout


def main() -> int:
    values = run("yq", "-o=json", ".spec.values", str(HELM_RELEASE))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as value_file:
        value_file.write(values)
        value_file.flush()
        rendered = run(
            "helm",
            "template",
            "harbor",
            CHART_URL,
            "-f",
            value_file.name,
        )
    # yq reads the Helm output from stdin; use a temporary file because the
    # subprocess helper intentionally keeps command execution simple.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as render_file:
        render_file.write(rendered)
        render_file.flush()
        deployment = json.loads(
            run(
                "yq",
                "-o=json",
                'select(.kind == "Deployment" and .metadata.name == "harbor-registry")',
                render_file.name,
            )
        )

    containers = {
        item["name"]: item
        for item in deployment["spec"]["template"]["spec"]["containers"]
    }
    failures = []
    for name, requests in EXPECTED.items():
        container = containers.get(name)
        actual = (container or {}).get("resources", {}).get("requests", {})
        for field, expected_values in (
            ("requests", requests),
            ("limits", EXPECTED_LIMITS.get(name, {})),
        ):
            actual_values = (container or {}).get("resources", {}).get(field, {})
            for resource, expected in expected_values.items():
                if actual_values.get(resource) != expected:
                    failures.append(
                        f"{name} {field}.{resource}: expected {expected}, "
                        f"got {actual_values.get(resource)!r}"
                    )
    if failures:
        print("Harbor resource contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        f"Harbor {CHART_VERSION} rendered harbor-registry requests: "
        "registry=100m/256Mi, registryctl=10m/64Mi"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError, KeyError) as error:
        print(f"Harbor resource contract could not be checked: {error}", file=sys.stderr)
        raise SystemExit(2)
