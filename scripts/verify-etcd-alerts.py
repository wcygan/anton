#!/usr/bin/env python3
"""Exercise the etcd alert rules with promtool against three synthetic members.

Run with `mise exec -- python3 scripts/verify-etcd-alerts.py`.
Requires Docker and yq. Runs one disposable local container; no cluster access.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-etcd.yaml"
PROM = "prom/prometheus:v3.15.0"
MINUTES = 90
MB = 1000**2
QUOTA = 2 * 1024**3
MEMBERS = ("m1", "m2", "m3")
LE = ("0.001", "0.002", "0.004", "0.008", "0.016", "0.032", "0.064", "0.128",
      "0.256", "0.512", "1.024", "2.048", "4.096", "8.192", "+Inf")
# Cumulative observations per minute at each bucket bound. HEALTHY matches the
# live members (about 865 WAL fsyncs a minute, p99 near 10 ms).
HEALTHY = (0, 6, 570, 840, 862, 864, 865, 865, 865, 865, 865, 865, 865, 865, 865)
ELEVATED = (0, 0, 100, 400, 700, 800, 830, 850, 865, 865, 865, 865, 865, 865, 865)  # p99 ~180 ms
BORDER = (0, 0, 100, 400, 700, 800, 830, 840, 850, 865, 865, 865, 865, 865, 865)  # p99 ~360 ms
SLOW = (0, 0, 50, 200, 400, 600, 700, 750, 780, 800, 820, 845, 865, 865, 865)  # p99 ~3 s
FSYNC = "etcd_disk_wal_fsync_duration_seconds_bucket"
COMMIT = "etcd_disk_backend_commit_duration_seconds_bucket"


def labels(member: str) -> str:
    return f'job="kube-etcd",instance="{member}:2381",namespace="kube-system"'


def constant(value: float) -> list:
    return [value] * (MINUTES + 1)


def buckets(name: str, member: str, per_minute: tuple, start: int = 0) -> dict:
    return {f'{name}{{{labels(member)},le="{le}"}}': [None if t < start else count * (t - start)
                                                     for t in range(MINUTES + 1)]
            for le, count in zip(LE, per_minute)}


def cluster(members=MEMBERS) -> dict:
    series = {f'kube_node_role{{job="kube-state-metrics",node="k8s-{i}",role="control-plane"}}': constant(1)
              for i in (1, 2, 3)}
    for member in members:
        series.update({
            f"up{{{labels(member)}}}": constant(1),
            f"etcd_server_has_leader{{{labels(member)}}}": constant(1),
            f"etcd_server_leader_changes_seen_total{{{labels(member)}}}": constant(2),
            f"etcd_mvcc_db_total_size_in_bytes{{{labels(member)}}}": constant(261 * MB),
            f"etcd_mvcc_db_total_size_in_use_in_bytes{{{labels(member)}}}": constant(69 * MB),
            f"etcd_server_quota_backend_bytes{{{labels(member)}}}": constant(QUOTA),
        })
        series.update(buckets(FSYNC, member, HEALTHY))
        series.update(buckets(COMMIT, member, HEALTHY))
    return series


def series_of(series: dict, name: str, member: str) -> list:
    return series[f"{name}{{{labels(member)}}}"]


def outage(series: dict, member: str, start: int, end: int = MINUTES + 1, leader_changes: int = 1) -> dict:
    """Stop scraping a member for [start, end); afterwards it restarts with fresh counters."""
    for key, values in series.items():
        if f'instance="{member}:2381"' not in key:
            continue
        for t in range(start, min(end, MINUTES + 1)):
            values[t] = 0 if key.startswith("up{") else None
    if end <= MINUTES:
        restarted = series_of(series, "etcd_server_leader_changes_seen_total", member)
        restarted[end:] = [leader_changes] * (MINUTES + 1 - end)
        for name in (FSYNC, COMMIT):
            for key, fresh in buckets(name, member, HEALTHY, start=end).items():
                series[key][end:] = fresh[end:]
    return series


def step(values: list, at: int, delta: float = 1) -> None:
    """Raise a counter from minute `at` onward, leaving missing samples missing."""
    for t in range(at, MINUTES + 1):
        if values[t] is not None:
            values[t] += delta


def scenarios() -> list:
    healthy = cluster()

    no_leader = cluster()
    series_of(no_leader, "etcd_server_has_leader", "m2")[3:] = [0] * (MINUTES - 2)

    blip = cluster()
    series_of(blip, "etcd_server_has_leader", "m2")[3] = 0

    flapping = cluster()
    for t in range(3, MINUTES + 1, 4):
        series_of(flapping, "up", "m3")[t] = 0

    churn = cluster()
    for member in MEMBERS:
        for at in (5, 8, 11, 14, 17):
            step(series_of(churn, "etcd_server_leader_changes_seen_total", member), at)

    # One node at a time, ten minutes apart; each rebooting node is the leader.
    roll = cluster()
    for member, start in (("m1", 5), ("m2", 15), ("m3", 25)):
        outage(roll, member, start, start + 2)
        for other in MEMBERS:
            if other != member:
                step(series_of(roll, "etcd_server_leader_changes_seen_total", other), start)

    slow_fsync = cluster()
    slow_fsync.update(buckets(FSYNC, "m1", SLOW))

    border = cluster()
    border.update(buckets(FSYNC, "m1", BORDER))
    border.update(buckets(COMMIT, "m1", BORDER))

    elevated = cluster()
    for member in MEMBERS:
        elevated.update(buckets(FSYNC, member, ELEVATED))
        elevated.update(buckets(COMMIT, member, ELEVATED))

    def sized(total, in_use):
        series = cluster()
        series_of(series, "etcd_mvcc_db_total_size_in_bytes", "m1")[:] = total
        series_of(series, "etcd_mvcc_db_total_size_in_use_in_bytes", "m1")[:] = in_use
        return series

    def growing(per_minute):
        total = [300 * MB + per_minute * t for t in range(MINUTES + 1)]
        return sized(total, [value - 50 * MB for value in total])

    no_targets = {key: values for key, values in cluster().items() if "kube-etcd" not in key}
    two_targets = {key: values for key, values in cluster().items() if 'instance="m3:2381"' not in key}

    near_quota = sized(constant(0.55 * QUOTA), constant(0.5 * QUOTA))
    over_quota = sized(constant(0.85 * QUOTA), constant(0.8 * QUOTA))

    return [
        ("healthy", healthy, [(20, {}), (75, {})]),
        ("no-leader", no_leader, [(2, {}), (5, {("EtcdNoLeader", "critical"): 1})]),
        ("leader-blip-30s", blip, [(5, {}), (10, {})]),
        ("member-down", outage(cluster(), "m3", 2), [(16, {}), (18, {("EtcdMembersDown", "warning"): 1})]),
        ("member-reboot-4m", outage(cluster(), "m3", 2, 6), [(16, {}), (25, {})]),
        ("member-crash-loop", flapping, [(17, {}), (20, {("EtcdMembersDown", "warning"): 1})]),
        ("leader-churn", churn, [(18, {}), (20, {("EtcdFrequentLeaderChanges", "warning"): 1})]),
        ("rolling-reboot", roll, [(20, {}), (35, {}), (45, {})]),
        ("wal-fsync-p99-3s", slow_fsync, [(9, {}), (13, {("EtcdHighFsyncDurations", "warning"): 1})]),
        ("latency-p99-360ms", border, [(13, {("EtcdHighCommitDurations", "warning"): 1})]),
        ("latency-p99-180ms", elevated, [(30, {})]),
        ("db-55pct-of-quota", near_quota, [(9, {}), (12, {("EtcdDatabaseNearQuota", "warning"): 1})]),
        ("db-85pct-of-quota", over_quota, [(12, {("EtcdDatabaseNearQuota", "warning"): 1,
                                                ("EtcdDatabaseNearQuota", "critical"): 1})]),
        ("db-growing-600MBph", growing(10 * MB), [(9, {}), (15, {("EtcdDatabaseGrowingFast", "warning"): 1})]),
        ("db-growing-60MBph", growing(1 * MB), [(60, {})]),
        ("db-700MB-free", sized(constant(800 * MB), constant(100 * MB)),
         [(59, {}), (62, {("EtcdDatabaseFragmented", "info"): 1})]),
        ("no-etcd-targets", no_targets, [(14, {}), (16, {("EtcdMetricsUnavailable", "warning"): 1})]),
        ("two-etcd-targets", two_targets, [(14, {}), (16, {("EtcdMetricsUnavailable", "warning"): 1})]),
    ]


def values(points: list) -> str:
    return " ".join("_" if value is None else repr(float(value)) for value in points)


def main() -> None:
    rules = json.loads(subprocess.check_output(["yq", "-o=json", ".spec", str(RULES)], text=True))
    keys = list(dict.fromkeys((rule["alert"], rule["labels"]["severity"])
                              for group in rules["groups"] for rule in group["rules"]))
    cases = scenarios()
    fired = {key for _, _, checks in cases for _, expected in checks for key, count in expected.items() if count}
    missing = [key for key in keys if key not in fired]
    assert not missing, f"no scenario fires {missing}"
    tests = []
    for name, series, checks in cases:
        exprs = [{"expr": f'count(ALERTS{{alertname="{alert}",severity="{severity}",alertstate="firing"}}) or vector(0)',
                  "eval_time": f"{minute}m",
                  "exp_samples": [{"labels": "{}", "value": expected.get((alert, severity), 0)}]}
                 for minute, expected in checks for alert, severity in keys]
        tests.append({"name": name, "interval": "1m",
                      "input_series": [{"series": key, "values": values(points)} for key, points in series.items()],
                      "promql_expr_test": exprs})
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "rules.json").write_text(json.dumps(rules))
        (root / "tests.json").write_text(json.dumps({"rule_files": ["/test/rules.json"],
                                                    "evaluation_interval": "30s", "tests": tests}))
        for command in (("check", "rules", "/test/rules.json"), ("test", "rules", "/test/tests.json")):
            result = subprocess.run(["docker", "run", "--rm", "-v", f"{root}:/test:ro", "--entrypoint", "/bin/promtool",
                                     PROM, *command], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=300)
            print(result.stdout.strip())
            if result.returncode:
                raise SystemExit(f"promtool {' '.join(command[:2])} failed ({result.returncode})")
    checks = sum(len(test["promql_expr_test"]) for test in tests)
    print(f"etcd alerts: {len(tests)} scenarios, {checks} checks across {len(keys)} alert severities PASS")


if __name__ == "__main__":
    main()
