#!/usr/bin/env python3
"""Thin adapter: re-read canonical guidance after compaction."""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    raise SystemExit(subprocess.call(['python3', str(REPO / 'scripts/documentation-index.py'), 'conventions', '--root', os.environ.get('CLAUDE_PROJECT_DIR', str(REPO))]))
