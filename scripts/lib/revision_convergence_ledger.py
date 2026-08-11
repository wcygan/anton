"""Persist sanitized revision convergence records in one atomic JSON ledger."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import stat
import time
from collections.abc import Mapping
from math import isfinite
from pathlib import Path
from typing import Any

from revision_convergence import (
    ObservationError,
    aggregate_revision_records_v2,
    new_revision_record_v2,
    update_revision_record_v2,
)


LEDGER_SCHEMA_VERSION = 1
LEDGER_MODE = 0o600
MAX_LEDGER_BYTES = 1024 * 1024
LOCK_TIMEOUT_SECONDS = 5.0


class LedgerError(ObservationError):
    """The requested ledger operation is unsafe or invalid."""


class LedgerCommitUncertainError(LedgerError):
    """The replacement succeeded, but directory durability is not confirmed."""


def _empty_ledger() -> dict[str, Any]:
    return {"records": [], "schema_version": LEDGER_SCHEMA_VERSION}


def _open_parent_directory(path: Path) -> tuple[int, str]:
    if not path.is_absolute() or not path.name or path.name in {".", ".."}:
        raise LedgerError("ledger path must be an absolute file path")
    if any(part in {".", "..", "~"} or part.startswith("~") for part in path.parts[1:]):
        raise LedgerError("ledger path contains an unsafe component")

    try:
        canonical_parent = path.parent.resolve(strict=True)
        original_parent_stat = os.stat(path.parent, follow_symlinks=True)
    except (OSError, RuntimeError) as error:
        raise LedgerError("ledger path cannot be resolved safely") from error

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current_fd = os.open("/", flags)
    try:
        for component in canonical_parent.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        parent_stat = os.fstat(current_fd)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise LedgerError("ledger parent is not a directory")
        if (parent_stat.st_dev, parent_stat.st_ino) != (
            original_parent_stat.st_dev,
            original_parent_stat.st_ino,
        ):
            raise LedgerError("ledger parent changed during validation")
        if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) != 0o700:
            raise LedgerError("ledger parent must be owned by the current user with mode 0700")
        return current_fd, path.name
    except Exception:
        os.close(current_fd)
        raise


def validate_ledger_path(path: Path) -> None:
    """Validate an explicit ledger path without creating state."""

    try:
        parent_fd, _ = _open_parent_directory(path)
    except OSError as error:
        raise LedgerError("ledger path cannot be opened safely") from error
    os.close(parent_fd)


def _validate_private_file(fd: int, description: str) -> None:
    file_stat = os.fstat(fd)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise LedgerError(f"{description} must be one regular file")
    if file_stat.st_uid != os.getuid() or stat.S_IMODE(file_stat.st_mode) != LEDGER_MODE:
        raise LedgerError(f"{description} must be owned by the current user with mode 0600")


def _open_lock(parent_fd: int, ledger_name: str) -> int:
    lock_name = f"{ledger_name}.lock"
    flags = os.O_RDWR | os.O_NOFOLLOW
    try:
        lock_fd = os.open(lock_name, flags | os.O_CREAT | os.O_EXCL, LEDGER_MODE, dir_fd=parent_fd)
        os.fchmod(lock_fd, LEDGER_MODE)
    except FileExistsError:
        lock_fd = os.open(lock_name, flags, dir_fd=parent_fd)
    try:
        _validate_private_file(lock_fd, "ledger lock")
    except Exception:
        os.close(lock_fd)
        raise
    return lock_fd


def _acquire_lock(lock_fd: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as error:
            if time.monotonic() >= deadline:
                raise LedgerError("ledger lock timed out") from error
            time.sleep(0.01)


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_LEDGER_BYTES:
            raise LedgerError("ledger exceeds the size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _validated_ledger(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"records", "schema_version"}:
        raise LedgerError("ledger must use the exact version 1 envelope")
    if value.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise LedgerError("ledger schema version is unsupported")
    records = value.get("records")
    if not isinstance(records, list):
        raise LedgerError("ledger records must be a list")
    if any(not isinstance(record, Mapping) for record in records):
        raise LedgerError("ledger records must be objects")
    try:
        aggregate_revision_records_v2(records)
    except ObservationError as error:
        raise LedgerError("ledger contains invalid revision records") from error
    return {"records": [dict(record) for record in records], "schema_version": LEDGER_SCHEMA_VERSION}


def _read_ledger_from_parent(parent_fd: int, ledger_name: str) -> dict[str, Any]:
    try:
        ledger_fd = os.open(ledger_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError:
        return _empty_ledger()
    except OSError as error:
        raise LedgerError("ledger cannot be opened safely") from error
    try:
        _validate_private_file(ledger_fd, "ledger")
        payload = _read_all(ledger_fd)
    finally:
        os.close(ledger_fd)
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LedgerError("ledger contains invalid JSON") from error
    return _validated_ledger(decoded)


def read_revision_ledger(path: Path) -> dict[str, Any]:
    """Read and validate one ledger without creating files."""

    try:
        parent_fd, ledger_name = _open_parent_directory(path)
    except OSError as error:
        raise LedgerError("ledger path cannot be opened safely") from error
    try:
        return _read_ledger_from_parent(parent_fd, ledger_name)
    finally:
        os.close(parent_fd)


def _transition_ledger(
    ledger: Mapping[str, Any], observation: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    validated = _validated_ledger(ledger)
    proposed = new_revision_record_v2(observation)
    records = [dict(record) for record in validated["records"]]
    matching = [index for index, record in enumerate(records) if record.get("revision") == proposed["revision"]]
    if len(matching) > 1:
        raise LedgerError("ledger contains duplicate revisions")
    if matching:
        index = matching[0]
        try:
            records[index] = update_revision_record_v2(records[index], observation)
        except ObservationError as error:
            raise LedgerError("ledger transition is invalid") from error
        action = "updated"
        record = records[index]
    else:
        records.append(proposed)
        action = "inserted"
        record = proposed
    candidate = _validated_ledger({"records": records, "schema_version": LEDGER_SCHEMA_VERSION})
    aggregate = aggregate_revision_records_v2(candidate["records"])
    return candidate, {
        "action": action,
        "aggregate": aggregate,
        "record": record,
    }


def preview_revision_observation(path: Path, observation: Mapping[str, Any]) -> dict[str, Any]:
    """Preview one transition without creating or replacing any file."""

    ledger = read_revision_ledger(path)
    _, result = _transition_ledger(ledger, observation)
    return result


def _canonical_payload(ledger: Mapping[str, Any]) -> bytes:
    return (json.dumps(ledger, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _write_atomic(parent_fd: int, ledger_name: str, ledger: Mapping[str, Any]) -> None:
    temporary_name = f".{ledger_name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    temporary_fd: int | None = None
    replaced = False
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            LEDGER_MODE,
            dir_fd=parent_fd,
        )
        os.fchmod(temporary_fd, LEDGER_MODE)
        payload = _canonical_payload(ledger)
        offset = 0
        while offset < len(payload):
            offset += os.write(temporary_fd, payload[offset:])
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        os.replace(temporary_name, ledger_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        replaced = True
    except OSError as error:
        raise LedgerError("ledger atomic write failed") from error
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if not replaced:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
    try:
        os.fsync(parent_fd)
    except OSError as error:
        raise LedgerCommitUncertainError(
            "ledger replacement succeeded but directory sync failed"
        ) from error


def collect_revision_observation(
    path: Path,
    observation: Mapping[str, Any],
    *,
    lock_timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Apply one observation under a stable lock and atomically replace the ledger."""

    if not isfinite(lock_timeout_seconds) or lock_timeout_seconds < 0:
        raise LedgerError("ledger lock timeout must be finite and nonnegative")
    try:
        parent_fd, ledger_name = _open_parent_directory(path)
    except OSError as error:
        raise LedgerError("ledger path cannot be opened safely") from error
    lock_fd: int | None = None
    try:
        lock_fd = _open_lock(parent_fd, ledger_name)
        _acquire_lock(lock_fd, lock_timeout_seconds)
        ledger = _read_ledger_from_parent(parent_fd, ledger_name)
        candidate, result = _transition_ledger(ledger, observation)
        _write_atomic(parent_fd, ledger_name, candidate)
        return result
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(parent_fd)
