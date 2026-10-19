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
HELM_REPOSITORY = HELM_RELEASE.with_name("helmrepository.yaml")
COMMAND_TIMEOUT_SECONDS = 180
EXPECTED = {
    "registry": {"cpu": "100m", "memory": "256Mi"},
    "registryctl": {"cpu": "10m", "memory": "64Mi"},
}
EXPECTED_LIMITS = {"registry": {"memory": "512Mi"}}


def run(*command: str) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"{' '.join(command)} exceeded {COMMAND_TIMEOUT_SECONDS}s timeout"
        ) from error
    if completed.returncode:
        raise RuntimeError(
            f"{' '.join(command)} failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    return completed.stdout


def resource_failures(deployment: dict[str, object]) -> list[str]:
    spec = deployment["spec"]
    template = spec["template"]
    pod_spec = template["spec"]
    containers = {item["name"]: item for item in pod_spec["containers"]}
    failures = []
    for name, requests in EXPECTED.items():
        container = containers.get(name, {})
        resources = container.get("resources", {})
        for field, expected_values in (
            ("requests", requests),
            ("limits", EXPECTED_LIMITS.get(name, {})),
        ):
            actual_values = resources.get(field, {})
            for resource, expected in expected_values.items():
                if actual_values.get(resource) != expected:
                    failures.append(
                        f"{name} {field}.{resource}: expected {expected}, "
                        f"got {actual_values.get(resource)!r}"
                    )
    return failures


def main() -> int:
    release = json.loads(run("yq", "-o=json", ".", str(HELM_RELEASE)))
    repository = json.loads(run("yq", "-o=json", ".", str(HELM_REPOSITORY)))
    chart = release["spec"]["chart"]["spec"]
    source = chart["sourceRef"]
    if source["kind"] != "HelmRepository" or source["name"] != repository["metadata"]["name"]:
        raise RuntimeError("Harbor chart sourceRef does not match the adjacent HelmRepository")
    chart_name = chart["chart"]
    chart_version = chart["version"]
    chart_url = f"{repository['spec']['url'].rstrip('/')}/{chart_name}-{chart_version}.tgz"
    values = json.dumps(release["spec"]["values"])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as value_file:
        value_file.write(values)
        value_file.flush()
        rendered = run(
            "helm",
            "template",
            "harbor",
            chart_url,
            "-f",
            value_file.name,
        )
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

    failures = resource_failures(deployment)
    if failures:
        print("Harbor resource contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        f"Harbor {chart_version} rendered harbor-registry requests: "
        "registry=100m/256Mi, registryctl=10m/64Mi"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError, KeyError) as error:
        print(f"Harbor resource contract could not be checked: {error}", file=sys.stderr)
        raise SystemExit(2)
