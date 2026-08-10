"""Executable contract for Anton Flux application structure and ordering.

This module is deliberately dependency-free so Codex hooks, Claude hooks, and
repository validation all exercise the same rules.  It validates committed
source files only; it does not render manifests or contact the cluster.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


SOURCE_FILES = (
    "ocirepository.yaml",
    "helmrepository.yaml",
    "gitrepository.yaml",
)


@dataclass(frozen=True)
class DependencyRule:
    kind: str
    namespace: str
    name: str


DEPENDENCY_RULES = {
    rule.kind: rule
    for rule in (
        DependencyRule("HTTPRoute", "network", "envoy-gateway"),
        DependencyRule("DNSEndpoint", "network", "cloudflare-dns"),
        DependencyRule("ExternalSecret", "external-secrets", "external-secrets"),
        DependencyRule("NetworkAttachmentDefinition", "network", "multus"),
        DependencyRule("Cluster", "databases", "cloudnative-pg"),
        DependencyRule("Dragonfly", "databases", "dragonfly-operator"),
        DependencyRule("Seaweed", "storage", "seaweedfs"),
    )
}


@dataclass(frozen=True)
class Violation:
    code: str
    path: Path
    message: str

    def render(self, root: Path) -> str:
        try:
            path = self.path.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            path = self.path.as_posix()
        return f"[{self.code}] {path}: {self.message}"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _spec_scalar(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^  {re.escape(key)}:\s*([^#\n]+?)\s*$", text)
    return _unquote(match.group(1)) if match else None


def _has_spec_key(text: str, key: str) -> bool:
    return bool(re.search(rf"(?m)^  {re.escape(key)}:\s*(?:#.*)?$", text))


def _yaml_documents(text: str) -> Iterator[str]:
    for document in re.split(r"(?m)^---\s*$", text):
        if document.strip():
            yield document


def _top_level_kind(document: str) -> str | None:
    match = re.search(r"(?m)^kind:\s*([^#\n]+?)\s*$", document)
    return _unquote(match.group(1)) if match else None


def _authored_kinds(app_dir: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for path in sorted((*app_dir.glob("*.yaml"), *app_dir.glob("*.yml"))):
        for document in _yaml_documents(_read(path)):
            kind = _top_level_kind(document)
            if kind:
                result.setdefault(kind, []).append(path)
    return result


def _depends_on(text: str, default_namespace: str) -> set[tuple[str, str]]:
    dependencies: set[tuple[str, str]] = set()
    in_depends_on = False
    current_name: str | None = None
    current_namespace = default_namespace

    def finish() -> None:
        nonlocal current_name, current_namespace
        if current_name:
            dependencies.add((current_namespace, current_name))
        current_name = None
        current_namespace = default_namespace

    for line in text.splitlines():
        if re.match(r"^  dependsOn:\s*(?:#.*)?$", line):
            in_depends_on = True
            continue
        if not in_depends_on:
            continue
        if line and not line.startswith(" "):
            finish()
            break
        if re.match(r"^  \S", line):
            finish()
            break
        name_match = re.match(r"^    - name:\s*([^#]+?)\s*$", line)
        if name_match:
            finish()
            current_name = _unquote(name_match.group(1))
            continue
        namespace_match = re.match(r"^      namespace:\s*([^#]+?)\s*$", line)
        if namespace_match and current_name:
            current_namespace = _unquote(namespace_match.group(1))
    else:
        finish()

    return dependencies


def app_root_for(path: Path, root: Path) -> Path | None:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except (OSError, ValueError):
        return None
    if len(parts) < 4 or parts[:2] != ("kubernetes", "apps"):
        return None
    if len(parts) == 4:
        return None
    return root / "kubernetes" / "apps" / parts[2] / parts[3]


def iter_app_roots(root: Path, namespace: str | None = None) -> Iterator[Path]:
    apps_root = root / "kubernetes" / "apps"
    namespaces: Iterable[Path]
    if namespace:
        namespaces = (apps_root / namespace,)
    else:
        namespaces = sorted(path for path in apps_root.iterdir() if path.is_dir())
    for namespace_root in namespaces:
        if not namespace_root.is_dir():
            continue
        for candidate in sorted(path for path in namespace_root.iterdir() if path.is_dir()):
            app_dir = candidate / "app"
            if (candidate / "ks.yaml").exists() or (app_dir.is_dir() and any(app_dir.iterdir())):
                yield candidate


def _shape_violations(app_root: Path, root: Path) -> list[Violation]:
    violations: list[Violation] = []
    namespace = app_root.parent.name
    app_name = app_root.name
    ks = app_root / "ks.yaml"
    app_kustomization = app_root / "app" / "kustomization.yaml"
    required = (ks, app_kustomization)
    for path in required:
        if not path.exists():
            violations.append(Violation("flux.shape.missing", path, "required Flux application file is missing"))

    namespace_kustomization = app_root.parent / "kustomization.yaml"
    registration = f"./{app_name}/ks.yaml"
    if namespace_kustomization.exists() and registration not in _read(namespace_kustomization):
        violations.append(
            Violation(
                "flux.registration.missing",
                namespace_kustomization,
                f"namespace kustomization must register {registration}",
            )
        )

    if ks.exists():
        expected_path = f"./kubernetes/apps/{namespace}/{app_name}/app"
        actual_path = _spec_scalar(_read(ks), "path")
        if actual_path != expected_path:
            violations.append(
                Violation(
                    "flux.path.invalid",
                    ks,
                    f"spec.path must be {expected_path!r}, found {actual_path!r}",
                )
            )

    helmrelease = app_root / "app" / "helmrelease.yaml"
    sources = [app_root / "app" / name for name in SOURCE_FILES if (app_root / "app" / name).exists()]
    if helmrelease.exists() and len(sources) != 1:
        violations.append(
            Violation(
                "flux.source.count",
                app_root / "app",
                f"Helm applications need exactly one chart source; found {len(sources)}",
            )
        )
    if not helmrelease.exists() and app_kustomization.exists():
        if not re.search(r"(?m)^\s*-\s+\S", _read(app_kustomization)):
            violations.append(
                Violation(
                    "flux.raw.empty",
                    app_kustomization,
                    "raw-resource applications must list at least one resource, component, patch, or generator",
                )
            )
    return violations


def _dependency_violations(app_root: Path) -> list[Violation]:
    ks = app_root / "ks.yaml"
    if not ks.exists():
        return []
    namespace = app_root.parent.name
    app_name = app_root.name
    dependencies = _depends_on(_read(ks), namespace)
    violations: list[Violation] = []
    for kind, paths in _authored_kinds(app_root / "app").items():
        rule = DEPENDENCY_RULES.get(kind)
        if rule is None or (namespace, app_name) == (rule.namespace, rule.name):
            continue
        if (rule.namespace, rule.name) not in dependencies:
            manifests = ", ".join(path.name for path in paths)
            violations.append(
                Violation(
                    "flux.dependency.missing",
                    ks,
                    f"{manifests} authors {kind}; add dependsOn {rule.namespace}/{rule.name} per ADR 0027",
                )
            )
    return violations


def _provider_violations(app_root: Path) -> list[Violation]:
    key = (app_root.parent.name, app_root.name)
    providers = {(rule.namespace, rule.name) for rule in DEPENDENCY_RULES.values()}
    if key not in providers:
        return []
    ks = app_root / "ks.yaml"
    if not ks.exists():
        return []
    text = _read(ks)
    ready = _spec_scalar(text, "wait") == "true" or any(
        _has_spec_key(text, key) for key in ("healthChecks", "healthCheckExprs")
    )
    if ready:
        return []
    return [
        Violation(
            "flux.provider.readiness",
            ks,
            "dependency provider must set wait: true, healthChecks, or healthCheckExprs per ADR 0027",
        )
    ]


def validate_app(app_root: Path, root: Path) -> list[Violation]:
    return [
        *_shape_violations(app_root, root),
        *_dependency_violations(app_root),
        *_provider_violations(app_root),
    ]


def validate_repository(root: Path, namespace: str | None = None) -> list[Violation]:
    return [
        violation
        for app_root in iter_app_roots(root, namespace)
        for violation in validate_app(app_root, root)
    ]


def validate_changed_path(path: Path, root: Path) -> list[Violation]:
    app_root = app_root_for(path, root)
    if app_root is not None:
        return validate_app(app_root, root)
    try:
        rel = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return []
    if len(rel.parts) == 4 and rel.parts[:2] == ("kubernetes", "apps"):
        return validate_repository(root, namespace=rel.parts[2])
    return []
