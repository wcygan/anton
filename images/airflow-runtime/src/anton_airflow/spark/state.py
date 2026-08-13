"""Fail-closed SparkApplication state classification."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping


class AttemptState(StrEnum):
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


ACTIVE_STATES = {
    "NEW",
    "PENDING",
    "SUBMITTED",
    "RUNNING",
    "FAILING",
    "SUCCEEDING",
    "INVALIDATING",
    "SHUTTING_DOWN",
}
SUCCESS_STATES = {"COMPLETED", "SUCCEEDED", "SUCCESS"}
FAILURE_STATES = {"FAILED", "FAILURE", "SUBMISSION_FAILED", "INVALID", "ERROR", "DEAD"}


def _state(value: Any) -> str:
    return str(value or "").upper().replace("-", "_")


def state_transition_history(resource: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Spark Operator's state transition history without assuming its shape."""
    status = resource.get("status") if isinstance(resource, Mapping) else None
    history = status.get("stateTransitionHistory") if isinstance(status, Mapping) else None
    if not isinstance(history, list):
        return []
    return [item for item in history if isinstance(item, Mapping)]


def classify_application(resource: Mapping[str, Any] | None) -> AttemptState:
    """Classify an application from history first, then its current state."""
    if resource is None:
        return AttemptState.ABSENT
    status = resource.get("status") if isinstance(resource, Mapping) else None
    if not isinstance(status, Mapping):
        return AttemptState.AMBIGUOUS

    history_states = [_state(item.get("state")) for item in state_transition_history(resource)]
    # The terminal history is authoritative. ResourceReleased alone is not.
    terminal = next((value for value in reversed(history_states) if value in SUCCESS_STATES | FAILURE_STATES), None)
    if terminal in SUCCESS_STATES:
        return AttemptState.SUCCEEDED
    if terminal in FAILURE_STATES:
        return AttemptState.FAILED

    current = _state((status.get("applicationState") or {}).get("state"))
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
        state = _state(item.get("state"))
        if state in SUCCESS_STATES | FAILURE_STATES:
            return state
    return None
