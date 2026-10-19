#!/usr/bin/env python3
"""Collect bounded read-only cooling and Loki WAL evidence from Anton."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix  # noqa: E402

PROXY = "/api/v1/namespaces/observability/services/http:kube-prometheus-stack-prometheus:9090/proxy"
QUERIES = {
    "fan1_rpm": 'node_hwmon_fan_rpm{chip="platform_nct6775_2592",sensor="fan1"} * on(instance) group_left(nodename) node_uname_info',
    "nvme_temp2_celsius": 'node_hwmon_temp_celsius{chip=~"nvme_.*",sensor="temp2"} * on(instance) group_left(nodename) node_uname_info',
    "package_throttles": 'node_cpu_package_throttles_total * on(instance) group_left(nodename) node_uname_info',
}
Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def parse_time(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid RFC3339 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC).replace(microsecond=0)


def summarize_series(response: object, start: datetime, end: datetime, step_seconds: int, *, metric_name: str = "") -> dict[str, object]:
    if not isinstance(response, dict) or response.get("status") != "success":
        return {"state": "query_error", "coverage": None, "series": []}
    data = response.get("data")
    results = data.get("result") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return {"state": "invalid_response", "coverage": None, "series": []}
    if not results:
        return {"state": "no_data", "coverage": {"expected_query_evaluation_points_per_series": expected_samples(start, end, step_seconds), "basis": "Prometheus range-query evaluation points; lookback can fill points and does not prove raw scrape continuity"}, "series": []}
    summaries = []
    expected = expected_samples(start, end, step_seconds)
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("metric"), dict) or not isinstance(item.get("values"), list):
            return {"state": "invalid_response", "coverage": None, "series": []}
        pairs = [pair for pair in item["values"] if isinstance(pair, list) and len(pair) == 2]
        numbers = []
        for _, value in pairs:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number == number and abs(number) != float("inf"):
                numbers.append(number)
        labels = {str(k): str(v) for k, v in sorted(item["metric"].items())}
        points = min(len(numbers), len(pairs))
        record: dict[str, object] = {
            "labels": labels,
            "query_evaluation_points": points,
            "expected_query_evaluation_points": expected,
            "evaluation_point_fraction": round(points / expected, 4) if expected else None,
            "first_evaluation_utc": datetime.fromtimestamp(float(pairs[0][0]), UTC).isoformat().replace("+00:00", "Z") if pairs else None,
            "last_evaluation_utc": datetime.fromtimestamp(float(pairs[-1][0]), UTC).isoformat().replace("+00:00", "Z") if pairs else None,
            "min": min(numbers) if numbers else None,
            "max": max(numbers) if numbers else None,
        }
        if metric_name == "fan1_rpm":
            record["zero_fraction"] = round(sum(number == 0 for number in numbers) / len(numbers), 4) if numbers else None
        if metric_name == "package_throttles" and len(numbers) >= 2:
            reset = any(current < previous for previous, current in zip(numbers, numbers[1:]))
            record["counter_reset_observed"] = reset
            record["counter_delta"] = None if reset else numbers[-1] - numbers[0]
        summaries.append(record)
    return {"state": "observed", "coverage": {"expected_query_evaluation_points_per_series": expected, "basis": "Prometheus range-query evaluation points; lookback can fill points and does not prove raw scrape continuity"}, "series": summaries}


def expected_samples(start: datetime, end: datetime, step_seconds: int) -> int:
    return max(1, int((end - start).total_seconds() // step_seconds) + 1)


def _run(argv: Sequence[str], timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)


def _raw(prefix: tuple[str, ...], path: str, runner: Runner) -> tuple[str, object]:
    try:
        result = runner((*prefix, "get", "--raw", path), 30)
    except (OSError, subprocess.TimeoutExpired):
        return "query_error", None
    if result.returncode:
        return "query_error", None
    try:
        return "observed", json.loads(result.stdout)
    except json.JSONDecodeError:
        return "invalid_response", None


def _query_path(promql: str, start: datetime, end: datetime, step_seconds: int) -> str:
    params = urlencode({"query": promql, "start": start.isoformat(), "end": end.isoformat(), "step": f"{step_seconds}s"})
    return f"{PROXY}/api/v1/query_range?{params}"


def collect(start: datetime, end: datetime, step_seconds: int, *, prefix: tuple[str, ...], runner: Runner = _run) -> dict[str, object]:
    metrics: dict[str, object] = {}
    for name, query in QUERIES.items():
        state, response = _raw(prefix, _query_path(query, start, end, step_seconds), runner)
        metrics[name] = summarize_series(response, start, end, step_seconds, metric_name=name) if state == "observed" else {"state": state, "coverage": None, "series": []}

    return {"schema_version": 1, "observed_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "window": {"start_utc": start.isoformat().replace("+00:00", "Z"), "end_utc": end.isoformat().replace("+00:00", "Z"), "step_seconds": step_seconds}, "interpretation": {"coverage_basis": "Prometheus range-query evaluation points; lookback can fill points and does not prove raw scrape continuity", "nvme_temp2_threshold": "unknown; do not classify as a breach", "nvme_temp2_sensor_mapping": "unknown", "fan1_zero_fraction_contract": "PrometheusRule alerts when >= 0.25 of 30s samples are zero over 10m, then for 5m", "source_is_read_only": True}, "metrics": metrics, "loki_wal_followup": {"plan": "context/plans/0026-investigate-loki-wal-replay.md", "local_checks": ["scripts/verify-log-durability.py", "scripts/verify-log-loss-alerts.py"], "historical_loss_quantity": "unknown"}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=24, help="lookback in hours (1..168)")
    parser.add_argument("--observed-at", help="RFC3339 end time; defaults to current UTC")
    parser.add_argument("--step-seconds", type=int, default=30)
    parser.add_argument("--repo-root", type=Path, default=REPO, help="canonical Anton checkout used for kubeconfig and target preflight")
    args = parser.parse_args(argv)
    if not 1 <= args.window <= 168 or not 10 <= args.step_seconds <= 300:
        parser.error("window must be 1..168 hours and step must be 10..300 seconds")
    try:
        end = parse_time(args.observed_at)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    start = end - timedelta(hours=args.window)
    try:
        prefix = anton_kubectl_prefix(args.repo_root.resolve())
    except TargetPreflightError as exc:
        print(f"cooling/WAL observation blocked by target preflight: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(collect(start, end, args.step_seconds, prefix=prefix), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
