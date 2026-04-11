#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PostToolUse check: enforce anton's Flux 3-file pattern for apps.

After any Edit/Write under `kubernetes/apps/{namespace}/{app}/...`, verify
the mandatory scaffolding exists. Surfaces missing files as hook feedback
(exit 2) so the agent notices before flux silently fails to deploy.
"""
import json
import sys
from pathlib import Path

REQUIRED = (
    "ks.yaml",
    "app/kustomization.yaml",
    "app/helmrelease.yaml",
    "app/ocirepository.yaml",
)


def find_app_root(p: Path) -> Path | None:
    """Return the /{app}/ directory under kubernetes/apps/{ns}/, or None."""
    parts = p.parts
    for i, part in enumerate(parts):
        if part != "apps":
            continue
        if i == 0 or parts[i - 1] != "kubernetes":
            continue
        if len(parts) < i + 3:
            continue
        return Path(*parts[: i + 3])
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if data.get("tool_name") not in {"Edit", "Write", "MultiEdit"}:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    try:
        path = Path(file_path).resolve()
    except OSError:
        return 0

    app_root = find_app_root(path)
    if app_root is None:
        return 0

    # Namespace-level files (namespace.yaml, kustomization.yaml) live one
    # level above the app root — skip them.
    if path.parent == app_root.parent:
        return 0

    # Only check if we just created a file inside an app that isn't yet complete.
    missing = [f for f in REQUIRED if not (app_root / f).exists()]
    if not missing:
        return 0

    listing = "\n".join(f"  - {app_root / f}" for f in missing)
    print(
        f"Flux app at {app_root} is missing required files from the 3-file pattern:\n"
        f"{listing}\n"
        f"→ See kubernetes/apps/CLAUDE.md. Every app needs: ks.yaml, "
        f"app/kustomization.yaml, app/helmrelease.yaml, app/ocirepository.yaml.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
