"""Canonical locations shared by documentation tools and agent adapters."""
from pathlib import Path

DECISIONS = Path('docs/docs/decisions')
PLANS = Path('docs/operations/platform-work/plans')


def plans_directory(root: Path) -> Path:
    root = root.resolve()
    if (root / '.agents').is_dir():
        return root.parent / 'anton-private' / PLANS
    if (root / PLANS).is_dir():
        return root / PLANS
    return root.parent / 'anton-private' / PLANS


def is_plan(path: Path, root: Path) -> bool:
    candidates = {plans_directory(root).resolve(), (root / PLANS).resolve()}
    return path.resolve().parent in candidates
