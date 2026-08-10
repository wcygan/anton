#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Validate every Anton Flux application against the shared contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from flux_application_contract import iter_app_roots, validate_repository  # noqa: E402


def main() -> int:
    violations = validate_repository(REPO)
    pointers = (
        (REPO / "kubernetes" / "apps" / "AGENTS.md", "mise exec -- task contracts:validate"),
        (REPO / ".agents" / "skills" / "add-flux-app" / "SKILL.md", "scripts/validate-flux-contract.py"),
        (REPO / ".agents" / "skills" / "anton-repo-conventions" / "SKILL.md", "scripts/validate-flux-contract.py"),
        (REPO / ".claude" / "skills" / "add-flux-app" / "SKILL.md", "scripts/validate-flux-contract.py"),
        (REPO / ".claude" / "skills" / "anton-repo-conventions" / "SKILL.md", "scripts/validate-flux-contract.py"),
        (REPO / ".claude" / "agents" / "flux-app-author.md", "scripts/validate-flux-contract.py"),
        (REPO / ".claude" / "agents" / "conventions-linter.md", "scripts/validate-flux-contract.py"),
        (REPO / ".codex" / "agents" / "anton-flux-app-author.toml", "scripts/validate-flux-contract.py"),
        (REPO / ".codex" / "agents" / "conventions-linter.toml", "scripts/validate-flux-contract.py"),
    )
    pointer_failures = [
        f"[flux.tooling.pointer] {path.relative_to(REPO)}: missing {token!r}"
        for path, token in pointers
        if token not in path.read_text(encoding="utf-8")
    ]
    guidance_requirements = (
        (REPO / ".agents" / "skills" / "add-flux-app" / "SKILL.md", ("raw mode", "explicitly authorizes")),
        (REPO / ".claude" / "skills" / "add-flux-app" / "SKILL.md", ("raw mode", "explicitly authorizes")),
        (REPO / ".claude" / "agents" / "flux-app-author.md", ("raw apps", "exactly one")),
        (REPO / ".claude" / "agents" / "conventions-linter.md", ("raw mode", "exactly one")),
        (REPO / ".codex" / "agents" / "anton-flux-app-author.toml", ("raw Kustomize apps", "explicit operator approval")),
        (REPO / ".codex" / "agents" / "conventions-linter.toml", ("raw mode", "exactly one")),
    )
    guidance_failures: list[str] = []
    for path, tokens in guidance_requirements:
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                guidance_failures.append(
                    f"[flux.tooling.guidance] {path.relative_to(REPO)}: missing {token!r}"
                )

    add_app_skills = (
        REPO / ".agents" / "skills" / "add-flux-app" / "SKILL.md",
        REPO / ".claude" / "skills" / "add-flux-app" / "SKILL.md",
    )
    forbidden_authority = ("**Commit and push.**", "force with `task reconcile`", "after `task reconcile`")
    for path in add_app_skills:
        text = path.read_text(encoding="utf-8")
        for token in forbidden_authority:
            if token in text:
                guidance_failures.append(
                    f"[flux.tooling.authority] {path.relative_to(REPO)}: remove {token!r}"
                )

    task_guidance = (
        REPO / "kubernetes" / "apps" / "AGENTS.md",
        *add_app_skills,
        REPO / ".claude" / "agents" / "flux-app-author.md",
    )
    bare_task = re.compile(r"(?m)(?:^[ \t]*|`)task\s+(?:reconcile|[a-z0-9_-]+:[a-z0-9_-]+)\b")
    for path in task_guidance:
        if bare_task.search(path.read_text(encoding="utf-8")):
            guidance_failures.append(
                f"[flux.tooling.command] {path.relative_to(REPO)}: task command must use 'mise exec --'"
            )
    if violations:
        for violation in violations:
            print(violation.render(REPO), file=sys.stderr)
        return 1
    if pointer_failures:
        for failure in pointer_failures:
            print(failure, file=sys.stderr)
        return 1
    if guidance_failures:
        for failure in guidance_failures:
            print(failure, file=sys.stderr)
        return 1
    count = sum(1 for _ in iter_app_roots(REPO))
    print(f"Flux application contract: PASS ({count} applications)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
