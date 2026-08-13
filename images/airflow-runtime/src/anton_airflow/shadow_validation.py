"""Fail-closed validation predicate for reusable shadow Spark retries."""

from __future__ import annotations

from typing import Any, Mapping

from .spark import AttemptState, classify_application
from .spark.state import terminal_state


def prior_shadow_output_is_valid(resource: Mapping[str, Any]) -> bool:
    """Reuse a prior attempt only after Trino records a completed validation."""
    if classify_application(resource) is not AttemptState.SUCCEEDED:
        return False
    metadata = resource.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    annotations = metadata.get("annotations")
    if not isinstance(annotations, Mapping):
        annotations = {}
    return (
        str(annotations.get("anton.io/prior-output-valid")).lower() == "true"
        and terminal_state(resource) == "SUCCEEDED"
    )
