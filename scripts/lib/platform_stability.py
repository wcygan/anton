"""Evaluate Anton platform stability from Prometheus proxy responses."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Callable, Sequence
from urllib.parse import urlencode, urlsplit, parse_qs


PLATFORM_SCOPE = (
    "flux-system|kube-system|network|external-secrets|storage|observability|"
    "envoy-gateway-system"
)
WINDOW_DAYS = 15
PROXY_PREFIX = (
    "/api/v1/namespaces/observability/services/"
    "http:kube-prometheus-stack-prometheus:9090/proxy"
)
QUERY_TIMEOUT_SECONDS = 30
TOTAL_QUERY_BUDGET_SECONDS = 60
NUMBER_QUANTUM = Decimal("0.000001")
ATTRIBUTION_SUBQUERY_RANGE = "14d23h59m"
ATTRIBUTION_INTERVAL_COUNT = 21600
EXPECTED_SCRAPE_TARGETS = {
    "apiserver": 3,
    "kube-state-metrics": 1,
    "kubelet": 9,
    "node-exporter": 3,
}


@dataclass(frozen=True)
class QuerySpec:
    key: str
    promql: str


@dataclass(frozen=True)
class ConservationResult:
    state: str
    raw_total: Decimal | None
    attributed_total: Decimal | None
    residual: Decimal | None
    samples: list[dict[str, object]] | None


QUERY_CATALOG = {
    "restart_total": QuerySpec(
        "restart_total",
        f'''sum(increase(kube_pod_container_status_restarts_total{{namespace=~"{PLATFORM_SCOPE}",container!=""}}[15d]))''',
    ),
    "restart_attribution_total": QuerySpec(
        "restart_attribution_total",
        f'''sum(sum_over_time((increase(kube_pod_container_status_restarts_total{{namespace=~"{PLATFORM_SCOPE}",container!=""}}[1m]))[{ATTRIBUTION_SUBQUERY_RANGE}:1m]))''',
    ),
    "restart_attribution_by_node": QuerySpec(
        "restart_attribution_by_node",
        f'''sum by (node) (sum_over_time(((increase(kube_pod_container_status_restarts_total{{namespace=~"{PLATFORM_SCOPE}",container!=""}}[1m])) * on (namespace,pod,uid) group_left(node) kube_pod_info{{node!=""}})[{ATTRIBUTION_SUBQUERY_RANGE}:1m]))''',
    ),
    "oom_restart_attribution_detail": QuerySpec(
        "oom_restart_attribution_detail",
        f'''(sum by (node,namespace,container,reason) (sum_over_time((((increase(kube_pod_container_status_restarts_total{{namespace=~"{PLATFORM_SCOPE}",container!=""}}[1m])) * on (namespace,pod,uid,container) group_left(reason) kube_pod_container_status_last_terminated_reason{{reason!=""}}) * on (namespace,pod,uid) group_left(node) kube_pod_info{{node!=""}})[{ATTRIBUTION_SUBQUERY_RANGE}:1m]))) > 0''',
    ),
    "running_container_hours": QuerySpec(
        "running_container_hours",
        f'''sum(sum_over_time(kube_pod_container_status_running{{namespace=~"{PLATFORM_SCOPE}",container!=""}}[15d:1h]))''',
    ),
    "scrape_continuity": QuerySpec(
        "scrape_continuity",
        '''min_over_time(((count by (job) (min_over_time(up{job="apiserver"}[1m]) == 1) == bool 3) or label_replace(vector(0), "job", "apiserver", "", ""))[15d:1m])
or min_over_time(((count by (job) (min_over_time(up{job="kube-state-metrics"}[1m]) == 1) == bool 1) or label_replace(vector(0), "job", "kube-state-metrics", "", ""))[15d:1m])
or min_over_time(((count by (job) (min_over_time(up{job="kubelet"}[1m]) == 1) == bool 9) or label_replace(vector(0), "job", "kubelet", "", ""))[15d:1m])
or min_over_time(((count by (job) (min_over_time(up{job="node-exporter"}[1m]) == 1) == bool 3) or label_replace(vector(0), "job", "node-exporter", "", ""))[15d:1m])''',
    ),
    "cilium_memory_warning": QuerySpec(
        "cilium_memory_warning",
        '''sum by (node) (sum_over_time((container_memory_working_set_bytes{namespace="kube-system",container="cilium-agent"} > bool 2048 * 1024 * 1024)[15d:1m]))''',
    ),
    "cilium_memory_critical": QuerySpec(
        "cilium_memory_critical",
        '''sum by (node) (sum_over_time((container_memory_working_set_bytes{namespace="kube-system",container="cilium-agent"} > bool 3072 * 1024 * 1024)[15d:1m]))''',
    ),
    "multus_memory": QuerySpec(
        "multus_memory",
        '''sum by (node) (sum_over_time((container_memory_working_set_bytes{namespace="network",container="kube-multus"} > bool 400 * 1024 * 1024)[15d:1m]))''',
    ),
    "whereabouts_memory": QuerySpec(
        "whereabouts_memory",
        '''sum by (node) (sum_over_time((container_memory_working_set_bytes{namespace="network",container="whereabouts"} > bool 400 * 1024 * 1024)[15d:1m]))''',
    ),
    "storage_vxlan_memory": QuerySpec(
        "storage_vxlan_memory",
        '''sum by (node) (sum_over_time((container_memory_working_set_bytes{namespace="network",container="vxlan"} > bool 96 * 1024 * 1024)[15d:1m]))''',
    ),
    "package_throttle": QuerySpec(
        "package_throttle",
        '''sum by (nodename) (sum_over_time((rate(node_cpu_package_throttles_total[1m]) > bool 0)[15d:1m]) * on(instance) group_left(nodename) node_uname_info)''',
    ),
    "storage_peak_percent": QuerySpec(
        "storage_peak_percent",
        f'''topk(20, max by (namespace,persistentvolumeclaim) (max_over_time((kubelet_volume_stats_used_bytes{{namespace=~"{PLATFORM_SCOPE}"}} / kubelet_volume_stats_capacity_bytes{{namespace=~"{PLATFORM_SCOPE}"}} * 100)[15d:1h])))''',
    ),
    "api_5xx_total": QuerySpec(
        "api_5xx_total",
        '''sum(increase(apiserver_request_total{code=~"5.."}[15d]))''',
    ),
    "api_5xx_max_ratio": QuerySpec(
        "api_5xx_max_ratio",
        '''max_over_time(((sum(rate(apiserver_request_total{code=~"5.."}[5m])) / sum(rate(apiserver_request_total[5m]))) and (sum(rate(apiserver_request_total[5m])) > 0))[15d:5m])''',
    ),
    "api_p99_current_seconds": QuerySpec(
        "api_p99_current_seconds",
        '''max(histogram_quantile(0.99, sum by (le,verb)(rate(apiserver_request_duration_seconds_bucket{verb!="WATCH"}[5m]))))''',
    ),
    "api_p99_historical_seconds": QuerySpec(
        "api_p99_historical_seconds",
        '''max_over_time((max(histogram_quantile(0.99, sum by (le,verb)(rate(apiserver_request_duration_seconds_bucket{verb!="WATCH"}[5m])))))[15d:1h])''',
    ),
}


Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
Clock = Callable[[], float]
KubectlPrefixProvider = Callable[[], tuple[str, ...]]


def parse_observed_at(value: str | None) -> datetime:
    """Parse an RFC3339 observation time, or use the current UTC time."""
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid observation time {value!r}: {error}") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("observation time must include a UTC offset")
    return parsed.astimezone(UTC).replace(microsecond=0)


def format_rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_runner(argv: Sequence[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _proxy_query_path(promql: str, observed_at: datetime) -> str:
    parameters = urlencode({"query": promql, "time": format_rfc3339(observed_at)})
    return f"{PROXY_PREFIX}/api/v1/query?{parameters}"


def _run_raw(
    path: str,
    runner: Runner,
    *,
    kubectl_prefix: tuple[str, ...],
    deadline: float,
    clock: Clock,
) -> tuple[str, dict[str, object] | None]:
    """Run the sole permitted cluster operation and normalize its response."""
    argv = (*kubectl_prefix, "get", "--raw", path)
    remaining_seconds = deadline - clock()
    if remaining_seconds <= 0:
        return "budget_exhausted", None
    try:
        completed = runner(argv, min(QUERY_TIMEOUT_SECONDS, remaining_seconds))
    except (OSError, subprocess.TimeoutExpired):
        return "query_error", None
    if completed.returncode != 0:
        return "query_error", None
    try:
        decoded = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return "invalid_response", None
    if not isinstance(decoded, dict):
        return "invalid_response", None
    if decoded.get("status") != "success":
        return "query_error", decoded
    return "observed", decoded


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _number(value: Decimal) -> float:
    return float(value.quantize(NUMBER_QUANTUM, rounding=ROUND_HALF_EVEN))


def _samples(
    response: dict[str, object],
    *,
    retain_exact: bool = False,
) -> tuple[str, list[dict[str, object]]]:
    data = response.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        return "invalid_response", []
    result = data.get("result")
    if not isinstance(result, list):
        return "invalid_response", []
    if not result:
        return "no_data", []

    normalized: list[dict[str, object]] = []
    for item in result:
        if not isinstance(item, dict):
            return "invalid_response", []
        labels = item.get("metric")
        value = item.get("value")
        if not isinstance(labels, dict) or not isinstance(value, list) or len(value) != 2:
            return "invalid_response", []
        parsed = _decimal(value[1])
        if parsed is None:
            return "invalid_response", []
        sample: dict[str, object] = {
            "labels": {str(key): str(labels[key]) for key in sorted(labels)},
            "value": _number(parsed),
        }
        if retain_exact:
            sample["exact_value"] = str(parsed)
        normalized.append(sample)
    normalized.sort(key=lambda sample: json.dumps(sample["labels"], sort_keys=True, separators=(",", ":")))
    return "observed", normalized


def _query_evidence(
    spec: QuerySpec,
    observed_at: datetime,
    runner: Runner,
    *,
    kubectl_prefix: tuple[str, ...],
    deadline: float,
    clock: Clock,
) -> dict[str, object]:
    state, response = _run_raw(
        _proxy_query_path(spec.promql, observed_at),
        runner,
        kubectl_prefix=kubectl_prefix,
        deadline=deadline,
        clock=clock,
    )
    evidence: dict[str, object] = {"promql": spec.promql, "state": state}
    if response is not None:
        for field in ("warnings", "infos"):
            if field in response:
                evidence[field] = response[field]
    if response is None or state != "observed":
        return evidence
    sample_state, samples = _samples(
        response,
        retain_exact=spec.key
        in {
            "restart_attribution_total",
            "restart_attribution_by_node",
            "oom_restart_attribution_detail",
        },
    )
    evidence["state"] = sample_state
    if sample_state == "observed":
        evidence["samples"] = samples
    return evidence


def _state(*evidence: dict[str, object]) -> str:
    states = {str(item["state"]) for item in evidence}
    for candidate in ("invalid_response", "query_error", "budget_exhausted", "no_data"):
        if candidate in states:
            return candidate
    return "observed"


def _scalar(evidence: dict[str, object]) -> float | None:
    samples = evidence.get("samples")
    if not isinstance(samples, list) or len(samples) != 1:
        return None
    sample = samples[0]
    if not isinstance(sample, dict) or sample.get("labels") != {}:
        return None
    value = sample.get("value")
    return float(value) if isinstance(value, int | float) else None


def _exact_scalar(evidence: dict[str, object]) -> Decimal | None:
    samples = evidence.get("samples")
    if not isinstance(samples, list) or len(samples) != 1:
        return None
    sample = samples[0]
    if not isinstance(sample, dict) or sample.get("labels") != {}:
        return None
    return _decimal(sample.get("exact_value"))


def _conserved_labeled_evidence(
    raw_evidence: dict[str, object],
    labeled_evidence: dict[str, object],
    *,
    label_names: tuple[str, ...],
) -> ConservationResult:
    """Validate exact labeled totals against one raw scalar."""

    raw_state = str(raw_evidence["state"])
    labeled_state = str(labeled_evidence["state"])
    for failure_state in ("invalid_response", "query_error", "budget_exhausted"):
        if failure_state in {raw_state, labeled_state}:
            return ConservationResult(failure_state, None, None, None, None)
    if raw_state == "no_data":
        return ConservationResult("no_data", None, None, None, None)
    if raw_state != "observed":
        return ConservationResult("incomplete", None, None, None, None)

    raw_total = _exact_scalar(raw_evidence)
    if raw_total is None or raw_total < 0:
        return ConservationResult("incomplete", raw_total, None, None, None)
    if labeled_state == "no_data":
        if raw_total == 0:
            return ConservationResult("complete", raw_total, Decimal(0), Decimal(0), [])
        return ConservationResult("no_data", raw_total, None, None, None)
    if labeled_state != "observed":
        return ConservationResult("incomplete", raw_total, None, None, None)

    samples = labeled_evidence.get("samples")
    if not isinstance(samples, list):
        return ConservationResult("incomplete", raw_total, None, None, None)
    expected_labels = set(label_names)
    observed_labels: set[tuple[str, ...]] = set()
    values: list[Decimal] = []
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("labels"), dict):
            return ConservationResult("incomplete", raw_total, None, None, samples)
        labels = sample["labels"]
        identity = tuple(str(labels.get(name, "")) for name in label_names)
        value = _decimal(sample.get("exact_value"))
        if (
            set(labels) != expected_labels
            or any(not item for item in identity)
            or identity in observed_labels
            or value is None
            or value < 0
        ):
            return ConservationResult("incomplete", raw_total, None, None, samples)
        observed_labels.add(identity)
        values.append(value)

    attributed_total = sum(values, Decimal(0))
    residual = abs(raw_total - attributed_total)
    state = "complete" if residual <= NUMBER_QUANTUM else "incomplete"
    return ConservationResult(state, raw_total, attributed_total, residual, samples)


def _aggregate_exact_samples(
    samples: list[dict[str, object]] | None,
    *,
    group_labels: tuple[str, ...],
    reason: str | None = None,
) -> list[dict[str, object]]:
    """Aggregate exact samples by selected labels."""

    totals: dict[tuple[str, ...], Decimal] = {}
    for sample in samples or []:
        labels = sample["labels"]
        if reason is not None and labels.get("reason") != reason:
            continue
        identity = tuple(str(labels[label]) for label in group_labels)
        value = _decimal(sample.get("exact_value"))
        if value is None:
            continue
        totals[identity] = totals.get(identity, Decimal(0)) + value
    return [
        {
            "exact_value": str(value),
            "labels": dict(zip(group_labels, identity, strict=True)),
            "value": _number(value),
        }
        for identity, value in sorted(totals.items())
    ]


def _threshold_measure(
    evidence: dict[str, object],
    *,
    component: str,
    threshold_mib: int,
    alert_for: str,
    attribution_label: str,
    coverage_reasons: set[str],
) -> dict[str, object]:
    samples = evidence.get("samples")
    if isinstance(samples, list) and any(
        not isinstance(sample, dict)
        or not isinstance(sample.get("labels"), dict)
        or attribution_label not in sample["labels"]
        for sample in samples
    ):
        coverage_reasons.add(f"{component}_node_attribution_missing")
    if evidence["state"] != "observed":
        coverage_reasons.add(f"{component}_{evidence['state']}")
    return {
        "alert_for": alert_for,
        "breach_minutes": samples if evidence["state"] == "observed" else None,
        "component": component,
        "promql": evidence["promql"],
        "state": evidence["state"],
        "threshold_mib": threshold_mib,
        "threshold_state": "deployed_rule",
    }


def _scrape_continuity_measure(
    evidence: dict[str, object],
    coverage_reasons: set[str],
) -> dict[str, object]:
    """Require each fixed telemetry source in every one-minute interval."""

    evidence_state = str(evidence["state"])
    samples = evidence.get("samples")
    state = evidence_state
    if evidence_state != "observed":
        coverage_reasons.add(f"scrape_continuity_{evidence_state}")
    elif not isinstance(samples, list):
        state = "incomplete"
        coverage_reasons.add("scrape_continuity_incomplete")
    else:
        observed: dict[str, float] = {}
        invalid = False
        for sample in samples:
            if not isinstance(sample, dict) or not isinstance(sample.get("labels"), dict):
                invalid = True
                continue
            labels = sample["labels"]
            job = labels.get("job")
            value = sample.get("value")
            if (
                not isinstance(job, str)
                or job not in EXPECTED_SCRAPE_TARGETS
                or job in observed
                or not isinstance(value, int | float)
            ):
                invalid = True
                continue
            observed[job] = float(value)
        if invalid or set(observed) != set(EXPECTED_SCRAPE_TARGETS) or any(value != 1.0 for value in observed.values()):
            state = "incomplete"
            coverage_reasons.add("scrape_continuity_incomplete")
        else:
            state = "complete"
    return {
        "expected_target_counts": EXPECTED_SCRAPE_TARGETS,
        "query": evidence,
        "resolution": "1m",
        "sources": samples if evidence_state == "observed" else None,
        "state": state,
    }


def _restart_attribution_measure(
    raw_evidence: dict[str, object],
    node_evidence: dict[str, object],
    coverage_reasons: set[str],
) -> dict[str, object]:
    """Require the time-local node join to conserve restart increments."""

    conservation = _conserved_labeled_evidence(
        raw_evidence,
        node_evidence,
        label_names=("node",),
    )
    if conservation.state != "complete":
        coverage_reasons.add(f"historical_restart_node_attribution_{conservation.state}")

    return {
        "by_node_query": node_evidence,
        "comparison": "unrounded_prometheus_decimal",
        "interval_count": ATTRIBUTION_INTERVAL_COUNT,
        "node_total_sum": (
            _number(conservation.attributed_total)
            if conservation.attributed_total is not None
            else None
        ),
        "node_totals": conservation.samples,
        "raw_total_query": raw_evidence,
        "resolution": "1m",
        "state": conservation.state,
        "tolerance": _number(NUMBER_QUANTUM),
        "unattributed_restart_increments": (
            _number(conservation.residual) if conservation.residual is not None else None
        ),
    }


def _oom_attribution_measure(
    raw_evidence: dict[str, object],
    detail_evidence: dict[str, object],
    *,
    running_hours_evidence: dict[str, object],
    scrape_continuity: dict[str, object],
    coverage_reasons: set[str],
) -> dict[str, object]:
    """Normalize OOM restart attribution evidence."""

    conservation = _conserved_labeled_evidence(
        raw_evidence,
        detail_evidence,
        label_names=("node", "namespace", "container", "reason"),
    )
    state = conservation.state
    oom_total: Decimal | None = None
    oom_rate: Decimal | None = None
    if state == "complete":
        oom_total = sum(
            (
                _decimal(sample.get("exact_value")) or Decimal(0)
                for sample in conservation.samples or []
                if sample["labels"].get("reason") == "OOMKilled"
            ),
            Decimal(0),
        )
    if state == "complete":
        continuity_state = str(scrape_continuity["state"])
        if continuity_state != "complete":
            query = scrape_continuity.get("query")
            query_state = str(query.get("state")) if isinstance(query, dict) else "incomplete"
            state = query_state if query_state != "observed" else "incomplete"
            coverage_reasons.add(f"oom_scrape_continuity_{state}")
        else:
            running_state = str(running_hours_evidence["state"])
            if running_state != "observed":
                state = running_state
                coverage_reasons.add(f"oom_restart_denominator_{state}")
            else:
                running_hours = _scalar(running_hours_evidence)
                if running_hours is None or running_hours <= 0:
                    state = "no_data"
                    coverage_reasons.add("oom_restart_denominator_no_data")
                elif oom_total is not None:
                    oom_rate = Decimal(1000) * oom_total / Decimal(str(running_hours))
    if state != "complete" and not any(reason.startswith("oom_") for reason in coverage_reasons):
        coverage_reasons.add(f"oom_restart_attribution_{state}")

    return {
        "attributed_restart_increments": (
            _number(conservation.attributed_total)
            if conservation.attributed_total is not None
            else None
        ),
        "attribution_dimensions": ["node", "namespace", "container", "reason"],
        "by_component": _aggregate_exact_samples(
            conservation.samples,
            group_labels=("namespace", "container"),
            reason="OOMKilled",
        ),
        "by_node": _aggregate_exact_samples(
            conservation.samples,
            group_labels=("node",),
            reason="OOMKilled",
        ),
        "detail_query": detail_evidence,
        "comparison": "unrounded_prometheus_decimal",
        "measurement_kind": "time_local_1m_restart_reason_estimator",
        "rate_per_1000_container_hours": _number(oom_rate) if oom_rate is not None else None,
        "raw_total_query": raw_evidence,
        "reason_totals": _aggregate_exact_samples(
            conservation.samples,
            group_labels=("reason",),
        ),
        "resolution": "1m",
        "state": state,
        "tolerance": _number(NUMBER_QUANTUM),
        "total": _number(oom_total) if state == "complete" and oom_total is not None else None,
        "unattributed_restart_increments": (
            _number(conservation.residual) if conservation.residual is not None else None
        ),
    }


def evaluate(
    observed_at: datetime,
    runner: Runner = _default_runner,
    clock: Clock = time.monotonic,
    *,
    prefix_provider: KubectlPrefixProvider,
) -> dict[str, object]:
    """Return the Metric 4 report without changing the cluster."""
    kubectl_prefix = prefix_provider()
    deadline = clock() + TOTAL_QUERY_BUDGET_SECONDS
    query_evidence = {
        key: _query_evidence(
            spec,
            observed_at,
            runner,
            kubectl_prefix=kubectl_prefix,
            deadline=deadline,
            clock=clock,
        )
        for key, spec in QUERY_CATALOG.items()
    }
    coverage_reasons: set[str] = set()

    scrape_continuity = _scrape_continuity_measure(
        query_evidence["scrape_continuity"],
        coverage_reasons,
    )
    restart_attribution = _restart_attribution_measure(
        query_evidence["restart_attribution_total"],
        query_evidence["restart_attribution_by_node"],
        coverage_reasons,
    )

    restart_total = _scalar(query_evidence["restart_total"])
    running_hours = _scalar(query_evidence["running_container_hours"])
    restart_state = _state(query_evidence["restart_total"], query_evidence["running_container_hours"])
    restart_rate: float | None = None
    if restart_total is not None and running_hours is not None and running_hours > 0:
        restart_rate = _number(Decimal(str(1000 * restart_total)) / Decimal(str(running_hours)))
    elif restart_state == "observed":
        restart_state = "no_data"
        coverage_reasons.add("restart_denominator_missing")

    oom_attribution = _oom_attribution_measure(
        query_evidence["restart_attribution_total"],
        query_evidence["oom_restart_attribution_detail"],
        running_hours_evidence=query_evidence["running_container_hours"],
        scrape_continuity=scrape_continuity,
        coverage_reasons=coverage_reasons,
    )
    oom_state = "observed" if oom_attribution["state"] == "complete" else str(oom_attribution["state"])

    memory = {
        "cilium_warning": _threshold_measure(
            query_evidence["cilium_memory_warning"],
            component="cilium-agent",
            threshold_mib=2048,
            alert_for="5m",
            attribution_label="node",
            coverage_reasons=coverage_reasons,
        ),
        "cilium_critical": _threshold_measure(
            query_evidence["cilium_memory_critical"],
            component="cilium-agent",
            threshold_mib=3072,
            alert_for="2m",
            attribution_label="node",
            coverage_reasons=coverage_reasons,
        ),
        "multus": _threshold_measure(
            query_evidence["multus_memory"],
            component="kube-multus",
            threshold_mib=400,
            alert_for="2m",
            attribution_label="node",
            coverage_reasons=coverage_reasons,
        ),
        "whereabouts": _threshold_measure(
            query_evidence["whereabouts_memory"],
            component="whereabouts",
            threshold_mib=400,
            alert_for="2m",
            attribution_label="node",
            coverage_reasons=coverage_reasons,
        ),
        "storage_vxlan": _threshold_measure(
            query_evidence["storage_vxlan_memory"],
            component="vxlan",
            threshold_mib=96,
            alert_for="2m",
            attribution_label="node",
            coverage_reasons=coverage_reasons,
        ),
    }

    throttle = query_evidence["package_throttle"]
    if throttle["state"] != "observed":
        coverage_reasons.add(f"package_throttle_{throttle['state']}")
    else:
        samples = throttle.get("samples")
        if isinstance(samples, list) and any(
            not isinstance(sample, dict)
            or not isinstance(sample.get("labels"), dict)
            or "nodename" not in sample["labels"]
            for sample in samples
        ):
            coverage_reasons.add("package_throttle_node_attribution_missing")

    storage = query_evidence["storage_peak_percent"]
    if storage["state"] != "observed":
        coverage_reasons.add(f"storage_{storage['state']}")
    api_error_total = query_evidence["api_5xx_total"]
    api_error_ratio = query_evidence["api_5xx_max_ratio"]
    api_latency_current = query_evidence["api_p99_current_seconds"]
    api_latency_historical = query_evidence["api_p99_historical_seconds"]
    for name, evidence in (
        ("api_error_total", api_error_total),
        ("api_error_ratio", api_error_ratio),
        ("api_latency_current", api_latency_current),
        ("api_latency_historical", api_latency_historical),
    ):
        if evidence["state"] != "observed":
            coverage_reasons.add(f"{name}_{evidence['state']}")

    outcome_gaps = {
        "api_thresholds_unapproved",
        "oom_event_counter_unavailable",
        "storage_threshold_unapproved",
    }
    if oom_state != "observed":
        outcome_gaps.add(f"oom_{oom_state}")
    all_coverage_reasons = coverage_reasons | outcome_gaps
    window_start = observed_at - timedelta(days=WINDOW_DAYS)
    return {
        "contract_version": 1,
        "coverage": {
            "observer_instrumentation_reasons": sorted(coverage_reasons),
            "observer_instrumentation_state": "complete" if not coverage_reasons else "partial",
            "outcome_gaps": sorted(outcome_gaps),
            "reasons": sorted(all_coverage_reasons),
            "scrape_continuity": scrape_continuity,
            "state": "complete" if not all_coverage_reasons else "partial",
        },
        "measures": {
            "api_error": {
                "breach_minutes": None,
                "max_ratio": api_error_ratio,
                "state": _state(api_error_total, api_error_ratio),
                "threshold_state": "unapproved",
                "total_5xx": api_error_total,
            },
            "api_latency": {
                "breach_minutes": None,
                "current_p99_seconds": api_latency_current,
                "historical_max_p99_seconds": api_latency_historical,
                "state": _state(api_latency_current, api_latency_historical),
                "threshold_state": "unapproved",
            },
            "memory": memory,
            "oom": {
                "attribution": oom_attribution,
                "authoritative_event_count_state": "no_data",
                "component_attribution": (
                    "time_local_1m_estimator" if oom_attribution["state"] == "complete" else "incomplete"
                ),
                "measurement_kind": oom_attribution["measurement_kind"],
                "node_attribution": (
                    "time_local_1m_estimator" if oom_attribution["state"] == "complete" else "incomplete"
                ),
                "rate_per_1000_container_hours": oom_attribution["rate_per_1000_container_hours"],
                "running_container_hours": query_evidence["running_container_hours"],
                "state": oom_state,
                "total": oom_attribution["total"],
            },
            "package_throttle": {
                "breach_minutes": throttle.get("samples") if throttle["state"] == "observed" else None,
                "condition": "rate(node_cpu_package_throttles_total[1m]) > bool 0",
                "promql": throttle["promql"],
                "state": throttle["state"],
                "threshold_state": "event_condition",
            },
            "restarts": {
                "attribution": restart_attribution,
                "node_attribution": "time_local_1m_estimator" if restart_attribution["state"] == "complete" else "incomplete",
                "rate_per_1000_container_hours": restart_rate,
                "running_container_hours": query_evidence["running_container_hours"],
                "state": restart_state,
                "total": query_evidence["restart_total"],
            },
            "storage": {
                "breach_minutes": None,
                "peak_percent": storage,
                "state": storage["state"],
                "threshold_state": "unapproved",
            },
        },
        "observation": {
            "observed_at": format_rfc3339(observed_at),
            "platform_namespace_scope": PLATFORM_SCOPE,
            "prometheus_service_proxy": PROXY_PREFIX,
            "window_days": WINDOW_DAYS,
            "window_start": format_rfc3339(window_start),
        },
    }


def parse_query_path(path: str) -> str | None:
    """Return the PromQL string from a proxy query path for test runners."""
    parsed = urlsplit(path)
    values = parse_qs(parsed.query).get("query")
    return values[0] if values else None
