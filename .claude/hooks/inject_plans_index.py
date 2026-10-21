#!/usr/bin/env python3
"""Thin session adapter for the shared Anton documentation index."""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    root = os.environ.get('CLAUDE_PROJECT_DIR', str(REPO))
    raise SystemExit(subprocess.call(['python3', str(REPO / 'scripts/documentation-index.py'), 'plans', '--root', root]))
