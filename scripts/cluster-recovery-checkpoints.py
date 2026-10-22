#!/usr/bin/env python3
"""Documented operator entry point; execution is permitted only inside Kubernetes."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "kubernetes/apps/storage/longhorn-maintenance/app/cluster-recovery-checkpoints.py"), run_name="__main__")
