#!/usr/bin/env python3
"""Test the committed fan alerts and dashboard using local promtool; no cluster access.

Run: mise exec -- python3 scripts/verify-fan-alerts.py [--promtool /path/to/promtool]
Requires yq and a native promtool binary (Prometheus 3.15.x).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-fan-health.yaml"
DASHBOARD = REPO / "kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml"
NODES = ("node-a", "node-b", "node-c")
MISSING = "NodePhysicalFanTelemetryMissing"
STOPPED = "NodePhysicalFanStoppedOrUnstable"


def cluster() -> list[dict[str, str]]:
    series = []
    for node in NODES:
        labels = f'job="node-exporter",instance="{node}:9100",pod="exporter-{node}"'
        series.extend([
            {"series": f"up{{{labels}}}", "values": "1+0x60"},
            {"series": f'node_uname_info{{{labels},nodename="{node}"}}', "values": "1+0x60"},
        ])
        for sensor in ("fan1", "fan2"):
            series.append({
                "series": f'node_hwmon_fan_rpm{{{labels},chip="platform_nct6775_2592",sensor="{sensor}"}}',
                "values": "1500+0x60",
            })
    return series


def remove(series: list[dict[str, str]], metric: str, node: str = "", sensor: str = "") -> list[dict[str, str]]:
    return [entry for entry in series if not (
        entry["series"].startswith(metric + "{")
        and (not node or f'instance="{node}:9100"' in entry["series"])
        and (not sensor or f'sensor="{sensor}"' in entry["series"])
    )]


def change(series: list[dict[str, str]], metric: str, node: str, values: str, sensor: str = "") -> list[dict[str, str]]:
    return [dict(entry, values=values) if (
        entry["series"].startswith(metric + "{")
        and f'instance="{node}:9100"' in entry["series"]
        and (not sensor or f'sensor="{sensor}"' in entry["series"])
    ) else entry for entry in series]


def expected(node: str, sensor: str, *, identity: bool = True) -> dict[str, str]:
    return {"instance": node + ":9100", "nodename": node if identity else node + ":9100", "sensor": sensor}


def scenarios() -> list[dict]:
    tests = []

    def case(name: str, series: list[dict[str, str]], checks: list[tuple[str, list, list]]) -> None:
        expressions = []
        for at, missing, stopped in checks:
            for alert, severity, alerts in ((MISSING, "warning", missing), (STOPPED, "critical", stopped)):
                samples = []
                for labels in alerts:
                    pairs = dict(labels, severity=severity, component="hardware")
                    samples.append({"labels": "{" + ",".join(f"{key}={json.dumps(value)}" for key, value in pairs.items()) + "}", "value": 1})
                expressions.append({
                    "expr": f'sum by(instance,nodename,sensor,severity,component) (ALERTS{{alertname="{alert}",alertstate="firing"}})',
                    "eval_time": at,
                    "exp_samples": samples,
                })
        tests.append({"name": name, "interval": "30s", "input_series": series, "promql_expr_test": expressions})

    fan1 = [expected("node-b", "fan1")]
    both = [expected("node-b", sensor) for sensor in ("fan1", "fan2")]
    all_fans = [expected(node, sensor) for node in NODES for sensor in ("fan1", "fan2")]
    case("healthy", cluster(), [("20m", [], [])])
    case("one-channel-missing", remove(cluster(), "node_hwmon_fan_rpm", "node-b", "fan1"), [("20m", fan1, [])])
    case("one-node-missing", remove(cluster(), "node_hwmon_fan_rpm", "node-b"), [("20m", both, [])])
    case("all-fan-telemetry-missing", remove(cluster(), "node_hwmon_fan_rpm"), [("9m30s", [], []), ("10m", all_fans, [])])
    case("transient-loss-recovers-before-grace", change(cluster(), "node_hwmon_fan_rpm", "node-b", "1500+0x9 stale _x16 1500+0x32", "fan1"), [("14m", [], []), ("20m", [], [])])
    case("loss-fires-and-recovery-clears", change(cluster(), "node_hwmon_fan_rpm", "node-b", "1500+0x9 stale _x24 1500+0x24", "fan1"), [("14m30s", [], []), ("15m", fan1, []), ("20m", [], [])])
    down = change(remove(cluster(), "node_hwmon_fan_rpm", "node-b"), "up", "node-b", "0+0x60")
    case("unreachable-exporter-is-target-down", down, [("20m", [], [])])
    restarted = change(remove(cluster(), "node_hwmon_fan_rpm", "node-b"), "up", "node-b", "0+0x9 1+0x50")
    case("exporter-restart-gets-full-grace", restarted, [("14m30s", [], []), ("15m", both, [])])
    missing_identity = remove(remove(cluster(), "node_uname_info", "node-b"), "node_hwmon_fan_rpm", "node-b", "fan1")
    case("missing-uname-cannot-hide-missing-fan", missing_identity, [("20m", [expected("node-b", "fan1", identity=False)], [])])
    case("missing-uname-with-present-fans", remove(cluster(), "node_uname_info", "node-b"), [("20m", [], [])])
    other_chip = remove(cluster(), "node_hwmon_fan_rpm", "node-b", "fan1") + [{
        "series": 'node_hwmon_fan_rpm{job="node-exporter",instance="node-b:9100",chip="unrelated",sensor="fan1"}',
        "values": "1500+0x60",
    }]
    case("unrelated-chip-cannot-mask-required-channel", other_chip, [("20m", fan1, [])])
    extra_sensor = cluster() + [{
        "series": 'node_hwmon_fan_rpm{job="node-exporter",instance="node-b:9100",chip="platform_nct6775_2592",sensor="fan3"}',
        "values": "0+0x60",
    }]
    case("unused-channel-zero-is-ignored", extra_sensor, [("20m", [], [])])
    case("zero-rpm-is-present-and-critical", change(cluster(), "node_hwmon_fan_rpm", "node-b", "0+0x60", "fan1"), [("4m30s", [], []), ("5m", [], fan1), ("20m", [], fan1)])

    churn = change(remove(cluster(), "node_hwmon_fan_rpm", "node-b", "fan1"), "node_uname_info", "node-b", "1+0x11 stale")
    churn.append({"series": 'node_uname_info{job="node-exporter",instance="node-b:9100",pod="replacement",nodename="node-b"}', "values": "_x12 1+0x47"})
    case("exporter-pod-change-does-not-reset-grace", churn, [("10m", fan1, [])])
    return tests


def dashboard_scenario() -> dict:
    dashboard = json.loads(subprocess.check_output([
        "yq", "-r", '.data."cluster-health-glance.json"', str(DASHBOARD),
    ], text=True))
    panel = next(panel for panel in dashboard["panels"] if panel["id"] == 805)
    return {
        "name": "dashboard-keeps-zero-required-fans-only",
        "interval": "30s",
        "input_series": [
            {"series": 'node_hwmon_fan_rpm{instance="node-b:9100",chip="platform_nct6775_2592",sensor="fan1"}', "values": "0+0x2"},
            {"series": 'node_hwmon_fan_rpm{instance="node-b:9100",chip="platform_nct6775_2592",sensor="fan2"}', "values": "1500+0x2"},
            {"series": 'node_hwmon_fan_rpm{instance="node-b:9100",chip="platform_nct6775_2592",sensor="fan3"}', "values": "800+0x2"},
            {"series": 'node_hwmon_fan_rpm{instance="node-b:9100",chip="unrelated",sensor="fan1"}', "values": "2200+0x2"},
        ],
        "promql_expr_test": [{
            "expr": panel["targets"][0]["expr"],
            "eval_time": "1m",
            "exp_samples": [
                {"labels": 'node_hwmon_fan_rpm{instance="node-b:9100",chip="platform_nct6775_2592",sensor="fan1"}', "value": 0},
                {"labels": 'node_hwmon_fan_rpm{instance="node-b:9100",chip="platform_nct6775_2592",sensor="fan2"}', "value": 1500},
            ],
        }],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promtool", default="promtool", help="native promtool executable")
    args = parser.parse_args()
    rules = json.loads(subprocess.check_output(["yq", "-o=json", ".spec", str(RULES)], text=True))
    tests = scenarios() + [dashboard_scenario()]
    with tempfile.TemporaryDirectory(prefix="anton-fan-alerts-") as directory:
        root = Path(directory)
        rule_file = root / "rules.json"
        test_file = root / "tests.json"
        rule_file.write_text(json.dumps(rules))
        test_file.write_text(json.dumps({"rule_files": [str(rule_file)], "evaluation_interval": "30s", "tests": tests}))
        subprocess.run([args.promtool, "check", "rules", str(rule_file)], check=True)
        subprocess.run([args.promtool, "test", "rules", str(test_file)], check=True)
    print(f"{len(tests)} native fan alert/dashboard scenarios passed")


if __name__ == "__main__":
    main()
