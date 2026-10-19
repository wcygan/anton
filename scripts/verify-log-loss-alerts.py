#!/usr/bin/env python3
"""Test log durability alerts with pinned local binaries; never accesses Kubernetes.

mise exec -- python3 scripts/verify-log-loss-alerts.py
Requires Docker and yq. No live failures or notifications are generated.
"""
from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[1]
PROM = "prom/prometheus:v3.15.0"
LOKI = "grafana/loki:3.7.8"
APP = "kubernetes/apps/observability/"
SELECTOR = 'namespace="observability",pod="collector-0",exporter="otlp_http/loki"'


def run(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return (p.stdout + p.stderr).strip()


def document(path):
    return json.loads(run("yq", "-o=json", ".", str(REPO / path)))


def save(path, value):
    path.write_text(json.dumps(value).replace("$${env:", "${env:"))


def http(url, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        content = response.read().decode()
        return json.loads(content) if content.startswith("{") else content


def eventually(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.25)
    raise AssertionError("Timed out waiting for local fixture")


def prometheus(root):
    groups = []
    for app in ("loki", "otel-collector"):
        groups += document(APP + app + "/app/prometheusrule.yaml")["spec"]["groups"]
    save(root / "rules.json", {"groups": groups})
    names = [r["alert"] for g in groups for r in g["rules"]]
    base = [{"series": 'kube_daemonset_status_desired_number_scheduled{namespace="observability",daemonset="otel-collector-opentelemetry-collector-agent"}', "values": "3+0x40"},
            {"series": 'up{namespace="observability",job="observability/loki",pod="loki-0"}', "values": "1+0x40"},
            {"series": 'loki_ingester_wal_replay_active{namespace="observability",job="observability/loki",pod="loki-0"}', "values": "0+0x40"}]
    for n in range(3):
        base += [{"series": f'up{{namespace="observability",job="observability/otel-collector-opentelemetry-collector-agent",pod="collector-{n}"}}', "values": "1+0x40"},
                 {"series": f'otelcol_exporter_queue_capacity{{namespace="observability",pod="collector-{n}",exporter="otlp_http/loki",data_type="logs"}}', "values": "100+0x40"},
                 {"series": f'otelcol_exporter_queue_size{{namespace="observability",pod="collector-{n}",exporter="otlp_http/loki",data_type="logs"}}', "values": "10+0x40"}]
    tests = []

    def scenario(name, series, at, expected):
        tests.append({"name": name, "interval": "1m", "input_series": series,
                      "promql_expr_test": [{"expr": 'count(ALERTS{alertname="' + alert + '",alertstate="firing"}) or vector(0)',
                          "eval_time": at, "exp_samples": [{"labels": "{}", "value": expected.get(alert, 0)}]} for alert in names]})

    def change(prefix, values):
        return [dict(x, values=values) if x["series"].startswith(prefix) and 'pod="collector-0"' in x["series"] else x for x in base]

    scenario("healthy-no-lazy-error-counters", base, "20m", {})
    scenario("warning-delay", change("otelcol_exporter_queue_size", "85+0x40"), "1m", {})
    scenario("warning", change("otelcol_exporter_queue_size", "85+0x40"), "2m", {"OTelCollectorQueueHigh": 1})
    scenario("critical-delay", change("otelcol_exporter_queue_size", "96+0x40"), "30s", {})
    scenario("critical", change("otelcol_exporter_queue_size", "96+0x40"), "2m", {"OTelCollectorQueueHigh": 1, "OTelCollectorQueueSaturated": 1})
    scenario("transient-spike", change("otelcol_exporter_queue_size", "96 10+0x39"), "5m", {})
    scenario("eighty-percent-boundary", change("otelcol_exporter_queue_size", "80+0x40"), "5m", {})
    scenario("ninety-five-percent-boundary", change("otelcol_exporter_queue_size", "95+0x40"), "5m", {"OTelCollectorQueueHigh": 1})
    for name in ("loki_ingester_wal_corruptions_total", "loki_ingester_wal_discarded_samples_total", "loki_ingester_wal_discarded_bytes_total"):
        series = base + [{"series": name + '{namespace="observability",job="observability/loki",pod="loki-0",type="segment"}', "values": "1+0x40"}]
        scenario(name + "-before-first-scrape", series, "0m", {"LokiWALRecoveryFailure": 1})
    scenario("normal-checkpoint-duplicates", base + [{"series": 'loki_ingester_wal_duplicate_entries_total{namespace="observability",job="observability/loki",pod="loki-0"}', "values": "100+0x40"}], "20m", {})
    scenario("normal-discarded-duplicate-replay", base + [
        {"series": name + '{namespace="observability",job="observability/loki",pod="loki-0",reason="duplicate"}', "values": "8641+0x40"}
        for name in ("loki_ingester_wal_discarded_samples_total", "loki_ingester_wal_discarded_bytes_total")], "20m", {})
    for name in ("loki_ingester_wal_disk_full_failures_total", "loki_ingester_checkpoint_creations_failed_total"):
        other = "loki_ingester_checkpoint_creations_failed_total" if "disk_full" in name else "loki_ingester_wal_disk_full_failures_total"
        series = base + [{"series": x + '{namespace="observability",job="observability/loki",pod="loki-0"}', "values": v + "+0x40"} for x, v in ((name, "1"), (other, "0"))]
        scenario(name + "-first-scrape", series, "0m", {"LokiWALPersistenceFailure": 1})
        scenario(name + "-quiet-resolves", series, "16m", {})
    for metric, alert in (("otelcol_exporter_enqueue_failed_log_records", "OTelCollectorEnqueueFailure"), ("otelcol_exporter_send_failed_log_records", "OTelCollectorExportFailure")):
        series = base + [{"series": metric + "{" + SELECTOR + "}", "values": "_ _ _ _ _ 1+0x35"}]
        scenario(metric + "-late-first-series", series, "5m", {alert: 1})
        scenario(metric + "-quiet-resolves", series, "21m", {})
        series = base + [{"series": metric + "{" + SELECTOR + "}", "values": "0+0x5 1+0x34"}]
        scenario(metric + "-increment", series, "7m", {alert: 1})
        series = base + [{"series": metric + "{" + SELECTOR + "}", "values": "10+0x20 0 1+0x18"}]
        scenario(metric + "-reset", series, "23m", {alert: 1})
        scenario(metric + "-other-exporter", base + [{"series": metric + '{namespace="observability",pod="collector-0",exporter="other"}', "values": "1+0x40"}], "5m", {})
    for prefix in ("up{", "otelcol_exporter_queue_capacity", "otelcol_exporter_queue_size"):
        series = [x for x in base if not ('pod="collector-0"' in x["series"] and x["series"].startswith(prefix))]
        scenario(prefix + "-missing-delay", series, "4m", {})
        scenario(prefix + "-missing", series, "5m", {"OTelCollectorLogMetricsUnavailable": 1})
    scenario("all-collectors-missing", [x for x in base if 'pod="collector-' not in x["series"]], "5m", {"OTelCollectorLogMetricsUnavailable": 1})
    for prefix in ("up{", "loki_ingester_wal_replay_active"):
        scenario("loki-coverage-" + prefix, [x for x in base if not ('pod="loki-0"' in x["series"] and x["series"].startswith(prefix))], "5m", {"LokiLogMetricsUnavailable": 1})
    save(root / "tests.json", {"rule_files": ["/test/rules.json"], "evaluation_interval": "30s", "tests": tests})
    for command in (("check", "rules", "/test/rules.json"), ("test", "rules", "/test/tests.json")):
        print(run("docker", "run", "--rm", "-v", f"{root}:/test:ro", "--entrypoint", "/bin/promtool", PROM, *command), flush=True)
    print(f"Prometheus: {len(tests)} healthy/failure/reset/first-scrape/coverage scenarios passed", flush=True)


def collector(root):
    values = document(APP + "otel-collector/app/helmrelease.yaml")["spec"]["values"]
    image = values["image"]["repository"] + ":" + values["image"]["tag"]
    logs = {}
    for case in ("retry", "enqueue", "permanent", "checkpoint"):
        fixture = root / case
        fixture.mkdir()
        (fixture / "state").mkdir(mode=0o777)
        (fixture / "state").chmod(0o777)
        (fixture / "input").mkdir()
        count = 80 if case == "checkpoint" else 1
        now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        for n in range(count):
            (fixture / "input" / f"{n}.log").write_text(f"{now} stdout F {n}" + "x" * 1200 + "\n")
        config = copy.deepcopy(values["alternateConfig"])
        storage = config["extensions"]["file_storage"]
        storage["directory"] = storage["compaction"]["directory"] = "/state"
        general = config["receivers"]["file_log"]
        general["include"], general["exclude"] = ["/test/input/*.log"], []
        general["operators"][0]["add_metadata_from_filepath"] = False
        config["receivers"] = {"file_log": general}
        config["service"]["pipelines"]["logs"]["receivers"] = ["file_log"]
        exporter = config["exporters"]["otlp_http/loki"]
        # A refused connection is retryable; the collector metrics HTTP server
        # returns a permanent 404 for /otlp/v1/logs. Both stay inside the container.
        exporter["endpoint"] = "http://127.0.0.1:" + ("8888" if case == "permanent" else "1") + "/otlp"
        if case == "enqueue":
            exporter["sending_queue"]["queue_size"] = 1
        if case == "checkpoint":
            storage["max_size"] = 32768
            config["exporters"] = {"debug": {"verbosity": "basic"}}
            config["service"]["pipelines"]["logs"]["exporters"] = ["debug"]
        save(fixture / "config.json", config)
        cid = run("docker", "run", "-d", "--user", "0", "-e", "MY_POD_IP=0.0.0.0", "-v", f"{fixture}:/test:ro", "-v", f"{fixture}/state:/state",
                  "-p", "127.0.0.1::8888", image, "--config=/test/config.json", *values["command"]["extraArgs"])
        try:
            port = run("docker", "port", cid, "8888/tcp").rsplit(":", 1)[1]
            needle = {"retry": "Will retry", "enqueue": "Rejecting data", "permanent": "Dropping data", "checkpoint": "save offsets"}[case]
            eventually(lambda: needle in run("docker", "logs", cid))
            logs[case] = run("docker", "logs", cid)
            metrics = http(f"http://127.0.0.1:{port}/metrics")
            failed = [l for l in metrics.splitlines() if l.startswith("otelcol_exporter_send_failed_log_records{")]
            if case == "retry":
                assert not failed, failed
            if case == "enqueue":
                assert any(l.startswith("otelcol_exporter_enqueue_failed_log_records{") and float(l.rsplit(" ", 1)[1]) > 0 for l in metrics.splitlines())
            if case == "permanent":
                assert len(failed) == 1 and float(failed[0].rsplit(" ", 1)[1]) == 1, failed
        finally:
            run("docker", "rm", "-f", cid)
    print("Collector: real queue rejection, checkpoint cap failure and permanent export failure; retry-only outage does not report final send failure", flush=True)
    return logs


def loki(root, logs):
    rules = document(APP + "loki/app/log-pipeline-alerts.yaml")
    path = root / "rules/fake"
    path.mkdir(parents=True)
    save(path / "alerts.json", rules)
    config = {"auth_enabled": False, "server": {"http_listen_port": 3100},
              "common": {"path_prefix": "/tmp/loki", "replication_factor": 1, "ring": {"kvstore": {"store": "inmemory"}},
                         "storage": {"filesystem": {"chunks_directory": "/tmp/loki/chunks", "rules_directory": "/tmp/loki/rules"}}},
              "schema_config": {"configs": [{"from": "2024-01-01", "store": "tsdb", "object_store": "filesystem", "schema": "v13", "index": {"prefix": "index_", "period": "24h"}}]},
              "limits_config": {"allow_structured_metadata": True},
              "ruler": {"enable_api": True, "storage": {"type": "local", "local": {"directory": "/test/rules"}}, "rule_path": "/tmp/loki/ruler", "alertmanager_url": "http://127.0.0.1:9093", "ring": {"kvstore": {"store": "inmemory"}}}}
    save(root / "loki.json", config)
    cid = run("docker", "run", "-d", "-v", f"{root}:/test:ro", "-p", "127.0.0.1::3100", LOKI, "-config.file=/test/loki.json")
    try:
        port = run("docker", "port", cid, "3100/tcp").rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"
        eventually(lambda: http(base + "/ready"))
        now = time.time_ns()
        checkpoint = next(l for l in logs["checkpoint"].splitlines() if "save offsets" in l)
        dropped = next(l for l in logs["permanent"].splitlines() if "Dropping data" in l)
        retry = next(l for l in logs["retry"].splitlines() if "Will retry" in l)
        fixtures = [
            ("checkpoint", checkpoint, "observability", "opentelemetry-collector", now - 1_000_000_000),
            ("load", "load offsets: corrupt checkpoint database", "observability", "opentelemetry-collector", now - 1_000_000_000),
            ("storage", "storage client: cannot open database", "observability", "opentelemetry-collector", now - 1_000_000_000),
            ("dropped", dropped, "observability", "opentelemetry-collector", now - 1_000_000_000),
            ("retry", retry, "observability", "opentelemetry-collector", now - 1_000_000_000),
            ("healthy", "Resuming from previously known offsets; checkpoint saved", "observability", "opentelemetry-collector", now - 1_000_000_000),
            ("stale", checkpoint, "observability", "opentelemetry-collector", now - 3_600_000_000_000),
            ("foreign", checkpoint, "other", "opentelemetry-collector", now - 1_000_000_000),
            ("wrong-container", checkpoint, "observability", "application", now - 1_000_000_000)]
        streams = [{"stream": {"k8s_namespace_name": ns, "k8s_container_name": container, "severity": "info"},
                    "values": [[str(stamp), line, {"k8s_pod_name": name}]]} for name, line, ns, container, stamp in fixtures]
        http(base + "/loki/api/v1/push", {"streams": streams})
        expected = {"OTelCollectorCheckpointFailure": {"checkpoint", "load", "storage"}, "OTelCollectorExportFailure": {"dropped"}}
        for rule in rules["groups"][0]["rules"]:
            result = http(base + "/loki/api/v1/query?" + urllib.parse.urlencode({"query": rule["expr"], "time": str(now)}))["data"]["result"]
            assert {x["metric"].get("pod", x["metric"].get("k8s_pod_name")) for x in result} == expected[rule["alert"]], result
        def firing():
            groups = http(base + "/prometheus/api/v1/rules")["data"]["groups"]
            actual = {r["name"]: {a["labels"].get("pod", a["labels"].get("k8s_pod_name")) for a in r.get("alerts", []) if a["state"] == "firing"} for g in groups for r in g["rules"]}
            return actual == expected
        eventually(firing, timeout=60)
        print("Loki: actual native checkpoint/drop messages fire both mounted rules; retry, healthy, stale and foreign logs stay quiet", flush=True)
    finally:
        run("docker", "rm", "-f", cid)


def main():
    with tempfile.TemporaryDirectory(prefix="anton-log-alerts-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        prometheus(root)
        logs = collector(root)
        loki(root, logs)
    print("Log-loss alert checks passed; local fixture containers removed")


if __name__ == "__main__":
    main()
