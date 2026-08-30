"""Namespace-scoped Kubernetes Lease ownership for Spark Attempts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol


class LeaseConflict(RuntimeError):
    """The target Lease is held by another active Spark Attempt."""


class LeaseTakeoverBlocked(LeaseConflict):
    """A stale Lease cannot be taken while its prior application is active."""


class LeaseApi(Protocol):
    def get_namespaced_lease(self, name: str, namespace: str) -> Mapping[str, Any]: ...

    def create_namespaced_lease(self, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def replace_namespaced_lease(self, name: str, namespace: str, body: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def delete_namespaced_lease(
        self,
        name: str,
        namespace: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> Any: ...


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def lease_expired(lease: Mapping[str, Any] | None, *, now: datetime | None = None) -> bool:
    """Return true when the Lease has no holder or its renew window elapsed."""
    if not lease:
        return True
    spec = lease.get("spec", {})
    if not isinstance(spec, Mapping) or not spec.get("holderIdentity"):
        return True
    renew = _parse_time(spec.get("renewTime"))
    if renew is None:
        return True
    duration = int(spec.get("leaseDurationSeconds") or 60)
    current = now or datetime.now(timezone.utc)
    return current >= renew + timedelta(seconds=duration)


def takeover_allowed(
    lease: Mapping[str, Any] | None,
    *,
    prior_application_active: bool,
    now: datetime | None = None,
) -> bool:
    """Require both expiry and proof that the prior Spark application is inactive."""
    return lease_expired(lease, now=now) and not prior_application_active


@dataclass(slots=True)
class LeaseCoordinator:
    """Create, renew, and release one target Lease for an exact attempt."""

    api: LeaseApi
    namespace: str
    target: str
    lease_duration_seconds: int = 60
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    @property
    def lease_name(self) -> str:
        return f"lakehouse-{self.target}-writer"

    def _body(self, holder: str, *, resource_version: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {"name": self.lease_name, "namespace": self.namespace},
            "spec": {
                "holderIdentity": holder,
                "leaseDurationSeconds": self.lease_duration_seconds,
                "renewTime": self.clock().isoformat(),
            },
        }
        if resource_version:
            body["metadata"]["resourceVersion"] = resource_version
        return body

    def acquire(self, holder: str, *, prior_application_active: bool = True) -> Mapping[str, Any]:
        """Acquire the Lease, or fail closed unless an expired Lease is safe to take."""
        try:
            current = self.api.get_namespaced_lease(self.lease_name, self.namespace)
        except Exception as error:
            if getattr(error, "status", None) != 404:
                raise
            return self.api.create_namespaced_lease(self.namespace, self._body(holder))

        spec = current.get("spec", {})
        existing = spec.get("holderIdentity") if isinstance(spec, Mapping) else None
        if existing == holder:
            return self.renew(holder, current=current)
        if not takeover_allowed(current, prior_application_active=prior_application_active, now=self.clock()):
            raise LeaseTakeoverBlocked(f"Lease {self.lease_name} is held by active attempt {existing!r}")
        return self.api.replace_namespaced_lease(
            self.lease_name,
            self.namespace,
            self._body(holder, resource_version=str(current.get("metadata", {}).get("resourceVersion", ""))),
        )

    def current(self) -> Mapping[str, Any] | None:
        """Read the target Lease without converting a missing Lease into an error."""
        try:
            return self.api.get_namespaced_lease(self.lease_name, self.namespace)
        except Exception as error:
            if getattr(error, "status", None) == 404:
                return None
            raise

    def renew(self, holder: str, *, current: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        current = current or self.api.get_namespaced_lease(self.lease_name, self.namespace)
        existing = (current.get("spec") or {}).get("holderIdentity")
        if existing != holder:
            raise LeaseConflict(f"Lease {self.lease_name} is held by {existing!r}")
        return self.api.replace_namespaced_lease(
            self.lease_name,
            self.namespace,
            self._body(holder, resource_version=str((current.get("metadata") or {}).get("resourceVersion", ""))),
        )

    def release(self, holder: str) -> None:
        current = self.api.get_namespaced_lease(self.lease_name, self.namespace)
        if (current.get("spec") or {}).get("holderIdentity") != holder:
            raise LeaseConflict(f"Lease {self.lease_name} is not held by {holder!r}")
        self.api.delete_namespaced_lease(self.lease_name, self.namespace)

    def release_idempotent(self, holder: str) -> bool:
        """Release one matching Lease and report whether it was already absent."""
        current = self.current()
        if current is None:
            return True
        existing = (current.get("spec") or {}).get("holderIdentity")
        if existing != holder:
            raise LeaseConflict(f"Lease {self.lease_name} is held by {existing!r}")
        metadata = current.get("metadata") or {}
        resource_version = metadata.get("resourceVersion")
        if not resource_version:
            raise LeaseConflict(
                f"Lease {self.lease_name} has no resource version for safe release"
            )
        preconditions = {"resourceVersion": str(resource_version)}
        if metadata.get("uid"):
            preconditions["uid"] = str(metadata["uid"])
        try:
            self.api.delete_namespaced_lease(
                self.lease_name,
                self.namespace,
                body={
                    "apiVersion": "v1",
                    "kind": "DeleteOptions",
                    "preconditions": preconditions,
                },
            )
        except Exception as error:
            if getattr(error, "status", None) == 404:
                return True
            if getattr(error, "status", None) == 409:
                raise LeaseConflict(
                    f"Lease {self.lease_name} changed before safe release"
                ) from error
            raise
        return False

    def release_if_held(self, holder: str) -> None:
        """Release a holder after recovery without failing when it is already gone."""
        current = self.current()
        if current is None:
            return
        if (current.get("spec") or {}).get("holderIdentity") == holder:
            self.api.delete_namespaced_lease(self.lease_name, self.namespace)
