#!/usr/bin/env python3
"""Validate complete benchmark evidence and summarize trial-level variation."""

import argparse
import json
import statistics
from pathlib import Path

CASES = ["baseline", "data-only", "data-index", "full"]


def spread(values):
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows = json.loads((args.directory / "results.json").read_text())
    assert len(rows) == 20, "require five complete rounds of four cases"
    images = {}
    summary = {}
    for case in CASES:
        trials = [r for r in rows if r["case"] == case]
        assert len(trials) == 5
        for r in trials:
            h, l = r["harbor"], r["loki"]
            assert len(h["put_seconds"]) == len(h["get_seconds"]) == 6
            assert h["verified_layer_bytes"] == 68 * 1024 * 1024
            assert len(set(h["layer_hashes"])) == 6 and h["manifest_verified"]
            assert l["verified_records"] == 8000 and l["chunks_stored"] >= 8
            assert l["s3_put_count"] >= 8 and l["index_objects_verified"]
            assert r["native_two_copy_placement"]
            assert all(len(set(v)) == 2 for v in r["native_two_copy_placement"].values())
            assert not r["profile"], "exclude traced trials from scored results"
            expected = "baseline" if case in ["baseline", "data-only"] else "candidate"
            images.setdefault(expected, r["images"]["volume"])
            assert images[expected] == r["images"]["volume"]
        summary[case] = {
            "trials": len(trials),
            "registry_48mib_put_seconds": spread([r["harbor"]["put_seconds"][0] for r in trials]),
            "registry_4mib_put_median_seconds": spread([statistics.median(r["harbor"]["put_seconds"][1:]) for r in trials]),
            "registry_total_put_seconds": spread([sum(r["harbor"]["put_seconds"]) for r in trials]),
            "registry_48mib_get_seconds": spread([r["harbor"]["get_seconds"][0] for r in trials]),
            "loki_push_median_seconds": spread([statistics.median(r["loki"]["push_seconds"]) for r in trials]),
            "loki_flush_seconds": spread([r["loki"]["flush_seconds"] for r in trials]),
            "loki_s3_put_mean_seconds": spread([r["loki"]["s3_put_seconds_sum"] / r["loki"]["s3_put_count"] for r in trials]),
            "loki_chunk_counts": [r["loki"]["chunks_stored"] for r in trials],
            "verified_records": sum(r["loki"]["verified_records"] for r in trials),
            "verified_registry_bytes": sum(r["harbor"]["verified_layer_bytes"] for r in trials),
        }
    print(json.dumps({"cases": summary, "images": images}, indent=2))


if __name__ == "__main__":
    main()
