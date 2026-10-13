"""Read-only image inventory. References, image bytes and disk bytes differ."""

from __future__ import annotations

import datetime as dt
import re


def parse_table(text: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    lines = text.splitlines()
    if not lines:
        raise ValueError("empty Talos table")
    header = lines[0]
    starts = [header.index(field) for field in fields]
    if starts != sorted(starts):
        raise ValueError("unexpected Talos table layout")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = {field: line[start:end].strip() for field, start, end in
               zip(fields, starts, starts[1:] + [None])}
        if not row[fields[0]]:
            raise ValueError("malformed Talos row")
        rows.append(row)
    return rows


def workload_references(items: list[dict]) -> set[str]:
    refs: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("image"), str):
                refs.add(value["image"])
            if isinstance(value.get("imageID"), str):
                refs.add(value["imageID"].removeprefix("docker-pullable://"))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(items)
    return refs


def canonical_ref(ref: str) -> str:
    ref = ref.removeprefix("docker-pullable://").removeprefix("containerd://")
    if ref.startswith("sha256:"):
        return ref
    if "/" not in ref:
        ref = "docker.io/library/" + ref
    elif not any(c in ref.split("/", 1)[0] for c in ".:") and not ref.startswith("localhost/"):
        ref = "docker.io/" + ref
    if "@" not in ref and ":" not in ref.rsplit("/", 1)[-1]:
        ref += ":latest"
    return ref.replace("index.docker.io/", "docker.io/", 1)


def classify(images: list[dict], containers: list[dict], desired: set[str]) -> dict:
    # Protect all runtime records, including stopped containers and sandboxes.
    protected_refs = {canonical_ref(ref) for ref in desired | {row["IMAGE"] for row in containers}}
    protected_digests = {ref.rsplit("@", 1)[-1] for ref in protected_refs if "@sha256:" in ref}
    protected_digests |= {row["DIGEST"] for row in images if canonical_ref(row["IMAGE"]) in protected_refs}
    candidates = [row for row in images if canonical_ref(row["IMAGE"]) not in protected_refs
                  and row["DIGEST"] not in protected_digests]
    return {
        "reference_count": len(images),
        "unique_digest_count": len({row["DIGEST"] for row in images}),
        "cri_managed_reference_count": sum("io.cri-containerd.image=managed" in
                                            row.get("LABELS", "") for row in images),
        "runtime_record_count": len(containers),
        "candidate_reference_count": len(candidates),
        "candidate_unique_digest_count": len({row["DIGEST"] for row in candidates}),
        "images": images,
        "runtime_containers": containers,
        "candidate_references": [row["IMAGE"] for row in candidates],
        "reclaimable_bytes": None,
        "caveat": "Unmatched references are candidates only; layers/leases may be shared. Created is not last-used time.",
    }


def gc_eligibility(service: str, now: dt.datetime) -> dict:
    match = re.search(r"Started task kubelet[^\n]*\(([^)]+) ago\)", service)
    if not match:
        return {"eligible_after": None, "reason": "kubelet start time unavailable"}
    parts = re.findall(r"([0-9.]+)(h|m|s)", match[1])
    if "".join(n + unit for n, unit in parts) != match[1]:
        return {"eligible_after": None, "reason": "unrecognized kubelet age"}
    age = sum(float(n) * {"h": 3600, "m": 60, "s": 1}[unit] for n, unit in parts)
    started = now - dt.timedelta(seconds=age)
    eligible = started + dt.timedelta(hours=168, minutes=30)
    return {"kubelet_started_at": started.isoformat(), "eligible_after": eligible.isoformat(),
            "aging_window_complete": now >= eligible}
