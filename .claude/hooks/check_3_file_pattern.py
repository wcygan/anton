#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PostToolUse check: enforce anton's Flux app scaffolding.

After any Edit/Write under `kubernetes/apps/{namespace}/{app}/...`, verify
the app has a valid scaffold. Two modes are accepted:

- **Helm mode** (the default 3-file pattern): ks.yaml + app/kustomization.yaml
  + app/helmrelease.yaml + one chart source (ocirepository.yaml or
  helmrepository.yaml).
- **Raw-resource mode** (e.g. tailnet-rbac, hubble-tailscale-ingress):
  ks.yaml + app/kustomization.yaml that lists at least one resource under
  resources/components/patches/generators. No HelmRelease, no chart source.

Surfaces missing pieces as hook feedback (exit 2) so the agent notices
before flux silently fails to deploy.
"""
import json
import re
import sys
from pathlib import Path

BASE_REQUIRED = (
    "ks.yaml",
    "app/kustomization.yaml",
)

# In Helm mode, each app needs exactly one chart source. OCIRepository is
# the preferred shape; HelmRepository is accepted when upstream does not
# publish an OCI chart (e.g. Longhorn ships only https://charts.longhorn.io).
SOURCE_ALTERNATIVES = (
    "app/ocirepository.yaml",
    "app/helmrepository.yaml",
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


def kustomization_has_entries(path: Path) -> bool:
    """True if the kustomization.yaml has at least one list item.

    Text scan (dep-free) matching any `- ` list entry with content. In practice
    this covers resources / components / patches / generators blocks — the only
    places a Flux-managed Kustomize app holds material.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"^\s*-\s+\S", text, re.MULTILINE))


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

    missing: list[str] = [
        f for f in BASE_REQUIRED if not (app_root / f).exists()
    ]

    hr = app_root / "app" / "helmrelease.yaml"
    app_kust = app_root / "app" / "kustomization.yaml"

    if hr.exists():
        # Helm mode — also require a chart source.
        if not any((app_root / f).exists() for f in SOURCE_ALTERNATIVES):
            missing.append(" or ".join(SOURCE_ALTERNATIVES))
        mode_hint = (
            "Helm mode: needs ks.yaml, app/kustomization.yaml, "
            "app/helmrelease.yaml, and an app/ocirepository.yaml "
            "(preferred) or app/helmrepository.yaml source."
        )
    else:
        # Raw-resource mode — app/kustomization.yaml must list at least one entry.
        if app_kust.exists() and not kustomization_has_entries(app_kust):
            missing.append(
                "app/kustomization.yaml (raw-resource mode: must list at "
                "least one entry under resources/components/patches/generators)"
            )
        mode_hint = (
            "Raw-resource mode (no HelmRelease): needs ks.yaml and an "
            "app/kustomization.yaml that lists at least one resource. See "
            "kubernetes/apps/kube-system/tailnet-rbac/ for a working example."
        )

    if not missing:
        return 0

    listing = "\n".join(f"  - {app_root / f}" for f in missing)
    print(
        f"Flux app at {app_root} is missing required scaffolding:\n"
        f"{listing}\n"
        f"→ {mode_hint}\n"
        f"See kubernetes/apps/CLAUDE.md for the full pattern reference.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
