"""Fail-closed SparkApplication state classification for the Apache operator.

The Apache Spark Kubernetes Operator (spark.apache.org) tracks application
state in ``status.currentState.currentStateSummary`` and appends every state
transition to ``status.stateTransitionHistory`` (a map keyed by attempt state
sequence). Each ``ApplicationState`` carries a ``currentStateSummary`` enum and
an optional ``message``. This module normalizes that shape so the adapter and
receipts classify outcomes without assuming Kubeflow's ``applicationState``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping


class AttemptState(StrEnum):
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


# Apache operator ApplicationStateSummary enum values, normalized to
# upper-case with no separators. Intermediate/running states are not outcomes.
ACTIVE_STATES = {
    "SUBMITTED",
    "SCHEDULEDTORESTART",
    "DRIVERREQUESTED",
    "DRIVERSTARTED",
    "DRIVERREADY",
    "INITIALIZEDBELOWTHRESHOLDEXECUTORS",
    "RUNNINGHEALTHY",
    "RUNNINGWITHPARTIALCAPACITY",
    "RUNNINGWITHBELOWTHRESHOLDEXECUTORS",
}
SUCCESS_STATES = {"SUCCEEDED"}
FAILURE_STATES = {
    "FAILED",
    "SCHEDULINGFAILURE",
    "DRIVERSTARTTIMEDOUT",
    "EXECUTORSSTARTTIMEDOUT",
    "DRIVERREADYTIMEDOUT",
    "DRIVEREVICTED",
}
# Resource-cleanup states are not outcomes on their own.
RESOURCE_CLEANUP_STATES = {"RESOURCERELEASED", "TERMINATEDWITHOUTRELEASERESOURCES"}


def _state(value: Any) -> str:
    return str(value or "").upper().replace("-", "_")


def state_transition_history(resource: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read the Apache operator's transition history without assuming its shape.

    Returns a chronological list of ``{state, transitionTime, message}`` items
    normalized from either the Apache map or a list-shaped history.
    """
    status = resource.get("status") if isinstance(resource, Mapping) else None
    if not isinstance(status, Mapping):
        return []
    raw = status.get("stateTransitionHistory")
    entries: list[tuple[Any, Mapping[str, Any]]] = []
    if isinstance(raw, dict):
        for key, item in raw.items():
            if isinstance(item, Mapping) and _entry_state(item) is not None:
                entries.append((key, item))
        entries.sort(key=lambda pair: _sort_key(pair[0]))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping) and _entry_state(item) is not None:
                entries.append((-1, item))
    elif isinstance(raw, Mapping):
        for key, item in raw.items():
            if isinstance(item, Mapping) and _entry_state(item) is not None:
                entries.append((key, item))
        entries.sort(key=lambda pair: _sort_key(pair[0]))
    result: list[Mapping[str, Any]] = []
    for _, item in entries:
        result.append(
            {
                "state": _state(_entry_state(item)),
                "transitionTime": (
                    item.get("lastTransitionTime")
                    or item.get("transitionTime")
                    or item.get("timestamp")
                    or ""
                ),
                "message": item.get("message") or "",
            }
        )
    return result


def _entry_state(item: Mapping[str, Any]) -> Any:
    value = item.get("currentStateSummary")
    if value is None:
        value = item.get("state")
    return value


def _sort_key(key: Any) -> tuple[bool, Any]:
    # Numeric attempt sequence keys sort naturally; anything else sorts last.
    try:
        return (False, int(key))
    except (TypeError, ValueError):
        return (True, str(key))


def _current_summary(status: Mapping[str, Any]) -> str:
    current = status.get("currentState")
    if isinstance(current, Mapping) and current.get("currentStateSummary") is not None:
        return _state(current["currentStateSummary"])
    # Tolerate a legacy shallow shape for read-only fallback.
    legacy = status.get("applicationState")
    if isinstance(legacy, Mapping) and legacy.get("state") is not None:
        return _state(legacy["state"])
    return ""


def classify_application(resource: Mapping[str, Any] | None) -> AttemptState:
    """Classify an application from history first, then its current state."""
    if resource is None:
        return AttemptState.ABSENT
    status = resource.get("status") if isinstance(resource, Mapping) else None
    if not isinstance(status, Mapping):
        return AttemptState.AMBIGUOUS

    history_states = [item.get("state") for item in state_transition_history(resource)]
    # The terminal history is authoritative. Resource cleanup is not an outcome.
    terminal = next(
        (value for value in reversed(history_states) if value in SUCCESS_STATES | FAILURE_STATES),
        None,
    )
    if terminal in SUCCESS_STATES:
        return AttemptState.SUCCEEDED
    if terminal in FAILURE_STATES:
        return AttemptState.FAILED

    current = _current_summary(status)
    # A current terminal value without a transition history is not an outcome
    # record. Treat it as ambiguous so a retry cannot write blindly.
    if not history_states:
        if current in ACTIVE_STATES:
            return AttemptState.ACTIVE
        return AttemptState.AMBIGUOUS
    if current in ACTIVE_STATES:
        return AttemptState.ACTIVE
    return AttemptState.AMBIGUOUS


def terminal_state(resource: Mapping[str, Any]) -> str | None:
    """Return the authoritative terminal state from transition history."""
    for item in reversed(state_transition_history(resource)):
        state = item.get("state")
        if state in SUCCESS_STATES | FAILURE_STATES:
            return state
    return None
