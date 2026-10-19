#!/usr/bin/env python3
"""Exercise repository alert rules locally with Prometheus, Loki, and OTel.

Run with `mise exec -- python3 scripts/verify-seaweedfs-alerts.py`.
Requires Docker and yq. Creates only disposable local containers; no cluster access.
"""
from __future__ import annotations

import json
from http.client import RemoteDisconnected
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROM = "prom/prometheus:v3.15.0"
LOKI = "grafana/loki:3.7.8"
OTEL = "ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s:0.161.0"


def run(*args: str) -> str:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}):\n{result.stdout}")
    return result.stdout.strip()


def yaml_file(path: str) -> dict:
    return json.loads(run("yq", "-o=json", ".", str(REPO / path)))


def save(root: Path, name: str, value: dict) -> None:
    (root / name).write_text(json.dumps(value))


def http(url: str, value: dict | None = None) -> dict:
    data = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        body = response.read()
        return json.loads(body) if body else {}


def prometheus(root: Path) -> None:
    rules = yaml_file("kubernetes/apps/storage/seaweedfs-config/app/prometheusrule.yaml")["spec"]
    save(root, "prom-rules.json", rules)
    inputs = [
        {"series": 'kube_statefulset_replicas{namespace="storage",statefulset="seaweedfs-volume"}', "values": "3+0x40"},
    ]
    for pod in range(3):
        inputs.append({"series": f'up{{namespace="storage",endpoint="volume-metrics",pod="volume-{pod}"}}', "values": "1+0x40"})
        if pod != 1:
            inputs.append({"series": f'SeaweedFS_volumeServer_read_only_volumes{{namespace="storage",type="IsReadOnly",pod="volume-{pod}",collection=""}}', "values": "0+0x40"})
    gauge = 'SeaweedFS_volumeServer_read_only_volumes{namespace="storage",type="IsReadOnly",pod="volume-1",collection=""}'
    healthy = inputs + [{"series": gauge, "values": "0+0x40"}]
    scenarios = [
        ("healthy", healthy, 0, 0),
        ("read-only", inputs + [{"series": gauge, "values": "1+0x40"}], 1, 0),
        ("recovered", inputs + [{"series": gauge, "values": "1+0x6 0+0x33"}], 0, 0),
        ("cause-series-do-not-trigger", healthy + [{"series": gauge.replace('type="IsReadOnly"', 'type="isDiskSpaceLow"'), "values": "1+0x40"}], 0, 0),
        ("one-down", [dict(item, values="0+0x40") if 'pod="volume-1"' in item["series"] else item for item in healthy], 0, 1),
        ("all-down", [dict(item, values="0+0x40") if item["series"].startswith("up{") else item for item in healthy], 0, 1),
        ("missing-monitor", inputs[:1], 0, 1),
        ("missing-gauge", inputs, 0, 1),
    ]
    tests = []
    for name, series, readonly, unavailable in scenarios:
        checks = []
        for alert, expected in (("SeaweedFSReadOnlyVolumes", readonly), ("SeaweedFSVolumeMetricsUnavailable", unavailable)):
            checks.append({"expr": f'count(ALERTS{{alertname="{alert}",alertstate="firing"}}) or vector(0)',
                           "eval_time": "4m", "exp_samples": [{"labels": "{}", "value": 0}]})
            checks.append({"expr": f'count(ALERTS{{alertname="{alert}",alertstate="firing"}}) or vector(0)',
                           "eval_time": "20m", "exp_samples": [{"labels": "{}", "value": expected}]})
        tests.append({"name": name, "interval": "1m", "input_series": series, "promql_expr_test": checks})
    save(root, "prom-tests.json", {"rule_files": ["/test/prom-rules.json"], "evaluation_interval": "30s", "tests": tests})
    for command in (("check", "rules", "/test/prom-rules.json"), ("test", "rules", "/test/prom-tests.json")):
        print(run("docker", "run", "--rm", "-v", f"{root}:/test:ro", "--entrypoint", "/bin/promtool", PROM, *command))


def loki(root: Path) -> None:
    rules = yaml_file("kubernetes/apps/observability/loki/app/seaweedfs-alerts.yaml")
    tenant = root / "rules/fake"
    tenant.mkdir(parents=True)
    save(tenant, "alerts.json", rules)
    production = yaml_file("kubernetes/apps/observability/loki/app/helmrelease.yaml")["spec"]["values"]["loki"]
    config = {
        "auth_enabled": False,
        "server": {"http_listen_port": 3100, "grpc_listen_port": 9095},
        "common": {"path_prefix": "/tmp/loki", "replication_factor": 1, "ring": {"kvstore": {"store": "inmemory"}},
                   "storage": {"filesystem": {"chunks_directory": "/tmp/loki/chunks", "rules_directory": "/tmp/loki/rules"}}},
        "schema_config": {"configs": [{"from": "2024-01-01", "store": "tsdb", "object_store": "filesystem", "schema": "v13", "index": {"prefix": "index_", "period": "24h"}}]},
        "limits_config": {"allow_structured_metadata": True},
        "ruler": dict(production["structuredConfig"]["ruler"], rule_path="/tmp/loki/ruler", alertmanager_url="http://127.0.0.1:9093"),
    }
    config["ruler"]["storage"]["local"]["directory"] = "/test/rules"
    config["ruler"]["enable_api"] = True
    save(root, "loki.json", config)
    container = run("docker", "run", "-d", "-v", f"{root}:/test:ro", "-p", "127.0.0.1::3100", LOKI, "-config.file=/test/loki.json")
    try:
        port = run("docker", "port", container, "3100/tcp").rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/ready", timeout=2).close()
                break
            except (urllib.error.URLError, RemoteDisconnected, TimeoutError):
                time.sleep(1)
        else:
            raise RuntimeError(run("docker", "logs", container))
        now = time.time_ns()
        streams = []
        fixtures = [
            ("storage", "volume", "bad-dat", "I1019 volumeDataIntegrityChecking failed: CRC mismatch", now - 2_000_000_000),
            ("storage", "volume", "bad-idx", "I1019 idx references end=792591640 marking readonly", now - 2_000_000_000),
            ("storage", "volume", "bad-crc", "invalid CRC for needle 42", now - 2_000_000_000),
            ("storage", "volume", "healthy", "volumeDataIntegrityChecking completed successfully", now - 2_000_000_000),
            ("other", "volume", "wrong-namespace", "volumeDataIntegrityChecking failed", now - 2_000_000_000),
            ("storage", "filer", "wrong-container", "volumeDataIntegrityChecking failed", now - 2_000_000_000),
            ("storage", "volume", "stale", "volumeDataIntegrityChecking failed", now - 3_600_000_000_000),
        ]
        fixtures += [("storage", "s3", "s3-stale", "I1019 read http://old.invalid:8444/20,abc failed, err: dial tcp: i/o timeout", now - i * 1_000_000) for i in range(1, 4)]
        fixtures += [("storage", "s3", "s3-canceled", "read chunk 20,abc failed: context canceled", now - i * 1_000_000) for i in range(1, 4)]
        fixtures += [("storage", "s3", "s3-truncated", "GetObjectHandler: failed to stream object from volume servers", now - i * 1_000_000) for i in range(1, 4)]
        fixtures += [("other", "s3", "s3-foreign", "read chunk 20,abc failed", now - i * 1_000_000) for i in range(1, 4)]
        fixtures += [("storage", "s3", "s3-normal", "GET complete status=200", now - i * 1_000_000) for i in range(1, 4)]
        for namespace, component, pod, line, stamp in fixtures:
            streams.append({"stream": {"k8s_namespace_name": namespace, "k8s_container_name": component, "severity": "info"},
                            "values": [[str(stamp), line, {"k8s_pod_name": pod}]]})
        http(base + "/loki/api/v1/push", {"streams": streams})
        expr = rules["groups"][0]["rules"][0]["expr"]
        query = urllib.parse.urlencode({"query": expr, "time": str(now)})
        result = http(base + "/loki/api/v1/query?" + query)["data"]["result"]
        actual = {item["metric"]["k8s_pod_name"] for item in result}
        assert actual == {"bad-dat", "bad-idx", "bad-crc"}, result
        print("Loki: INFO-level integrity failures match; healthy, foreign, and stale logs do not")
        read_rule = next(rule for group in rules["groups"] for rule in group["rules"] if rule["alert"] == "SeaweedFSS3ReadFailures")
        read_query = urllib.parse.urlencode({"query": read_rule["expr"], "time": str(now)})
        read_result = http(base + "/loki/api/v1/query?" + read_query)["data"]["result"]
        assert {item["metric"]["k8s_pod_name"] for item in read_result} == {"s3-stale", "s3-truncated"}, read_result
        print("Loki: S3 retry and truncated-stream failures match; cancellations, successful reads, and foreign logs do not")
        for _ in range(110):
            groups = http(base + "/prometheus/api/v1/rules")["data"]["groups"]
            alerts = [alert for group in groups for rule in group["rules"] for alert in rule.get("alerts", [])]
            firing = {alert["labels"].get("k8s_pod_name") for alert in alerts if alert["state"] == "firing"}
            if firing == {"bad-dat", "bad-idx", "bad-crc", "s3-stale", "s3-truncated"}:
                print("Loki: mounted ruler evaluates the actual integrity rule and fires for integrity and S3 failure fixtures")
                break
            time.sleep(1)
        else:
            raise AssertionError(groups)
        logs = run("docker", "logs", container)
        assert "failed to load rules" not in logs and "unable to read rules" not in logs, logs
    finally:
        run("docker", "rm", "-f", container)


def collector(root: Path) -> None:
    production = yaml_file("kubernetes/apps/observability/otel-collector/app/helmrelease.yaml")["spec"]["values"]["alternateConfig"]
    receiver = production["receivers"]["file_log/seaweedfs_volumes"]
    receiver["include"] = ["/test/input/*.log"]
    config = {"extensions": {"file_storage": {"directory": "/tmp/checkpoints", "create_directory": True}},
              "receivers": {"file_log/seaweedfs_volumes": receiver}, "exporters": {"debug": {"verbosity": "detailed"}},
              "service": {"extensions": ["file_storage"], "pipelines": {"logs": {"receivers": ["file_log/seaweedfs_volumes"], "exporters": ["debug"]}}}}
    # The container parser identifies CRI format from a Kubernetes log path.
    fixture = root / "input"
    fixture.mkdir()
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    lines = []
    for stamp, text in ((now - timedelta(hours=2), "OLD_INTEGRITY_FAILURE"), (now, "FRESH_INTEGRITY_FAILURE")):
        lines.append(stamp.isoformat().replace("+00:00", "Z") + " stdout F " + text + "\n")
    (fixture / "0.log").write_text("".join(lines))
    # Disable only path-derived metadata for this local fixture.
    receiver["operators"][0]["add_metadata_from_filepath"] = False
    save(root, "otel.json", config)
    print(run("docker", "run", "--rm", "-v", f"{root}:/test:ro", OTEL, "validate", "--config=/test/otel.json"))
    container = run("docker", "run", "-d", "--tmpfs", "/tmp:mode=1777", "-v", f"{root}:/test:ro", OTEL, "--config=/test/otel.json")
    try:
        for _ in range(30):
            logs = run("docker", "logs", container)
            if "FRESH_INTEGRITY_FAILURE" in logs:
                assert "OLD_INTEGRITY_FAILURE" not in logs, logs
                print("OTel: replays fresh startup logs and filters old logs")
                break
            if run("docker", "inspect", "-f", "{{.State.Running}}", container) != "true":
                raise RuntimeError(logs)
            time.sleep(1)
        else:
            raise RuntimeError(logs)
    finally:
        run("docker", "rm", "-f", container)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="anton-seaweed-alerts-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        prometheus(root)
        loki(root)
        collector(root)
    print("SeaweedFS alert behavior checks passed; local containers removed")


if __name__ == "__main__":
    main()
