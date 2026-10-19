"""Render Harbor's pinned chart and check its nginx continuity resources."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "kubernetes/apps/registries/harbor/app/helmrelease.yaml"


def run(command, *, timeout, **kwargs):
    return subprocess.run(command, check=True, timeout=timeout, **kwargs)


def main():
    version = subprocess.check_output(
        ["yq", ".spec.chart.spec.version", str(RELEASE)],
        text=True,
        timeout=20,
    ).strip()
    if not version or any(char not in "0123456789." for char in version):
        raise SystemExit(f"unexpected Harbor chart version: {version!r}")

    with tempfile.TemporaryDirectory(prefix="harbor-chart-check-") as temp:
        temp = Path(temp)
        helm_env = os.environ.copy()
        for key, dirname in (
            ("HELM_CACHE_HOME", "cache"),
            ("HELM_CONFIG_HOME", "config"),
            ("HELM_DATA_HOME", "data"),
        ):
            helm_env[key] = str(temp / dirname)
        archive_dir = temp / "chart"
        archive_dir.mkdir()
        archive = archive_dir / f"harbor-{version}.tgz"
        values = temp / "values.yaml"
        rendered = temp / "rendered.yaml"
        chart_url = f"https://helm.goharbor.io/harbor-{version}.tgz"

        run(["helm", "pull", chart_url, "--destination", str(archive_dir)],
            timeout=120, env=helm_env, capture_output=True, text=True)
        chart_version = subprocess.check_output(
            ["helm", "show", "chart", str(archive)],
            text=True,
            timeout=30,
            env=helm_env,
        )
        chart_version = subprocess.run(
            ["yq", ".version", "-"], input=chart_version,
            check=True, capture_output=True, text=True, timeout=20,
        ).stdout.strip().strip('"')
        if chart_version != version:
            raise SystemExit(f"downloaded chart {chart_version}, expected {version}")

        values.write_text(subprocess.check_output(
            ["yq", ".spec.values", str(RELEASE)], text=True, timeout=20
        ))
        with rendered.open("w") as output:
            run(["helm", "template", "harbor", str(archive),
                 "--namespace", "registries", "--values", str(values)],
                timeout=60, env=helm_env, stdout=output, text=True)

        checks = {
            "nginx Deployment": (
                'select(.kind == "Deployment" and .metadata.name == "harbor-nginx") '
                '| .spec.replicas == 2 and '
                '.spec.template.spec.topologySpreadConstraints[0].maxSkew == 1 and '
                '.spec.template.spec.topologySpreadConstraints[0].topologyKey == "kubernetes.io/hostname" and '
                '.spec.template.spec.topologySpreadConstraints[0].whenUnsatisfiable == "ScheduleAnyway" and '
                '.spec.template.spec.topologySpreadConstraints[0].labelSelector.matchLabels.component == "nginx"'
            ),
            "nginx PDB": (
                'select(.kind == "PodDisruptionBudget" and .metadata.name == "harbor-nginx") '
                '| .spec.minAvailable == 1 and '
                '.spec.selector.matchLabels.component == "nginx" and '
                '.spec.selector.matchLabels.app == "harbor" and '
                '.spec.selector.matchLabels.release == "harbor"'
            ),
        }
        for name, expression in checks.items():
            run(["yq", "-e", expression, str(rendered)],
                timeout=20, capture_output=True, text=True)
            print(f"PASS: {name} from Harbor chart {version}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as exc:
        print(f"timed out after {exc.timeout}s: {exc.cmd}", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else str(exc)
        print(detail, file=sys.stderr)
        raise SystemExit(exc.returncode)
