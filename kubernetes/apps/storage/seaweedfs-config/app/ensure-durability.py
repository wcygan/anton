#!/usr/bin/env python3
"""Converge Harbor/Loki prefix durability and verify both filer readbacks."""

import argparse
import json
import subprocess
import time

PREFIXES = ("/buckets/harbor/", "/buckets/loki/")


def read_config(output):
    decoder = json.JSONDecoder()
    documents = []
    remaining = output.strip()
    while remaining:
        value, end = decoder.raw_decode(remaining)
        documents.append(value)
        remaining = remaining[end:].strip()
    if not documents or not isinstance(documents[-1].get("locations"), list):
        raise ValueError("missing filer configuration readback")
    return documents[-1]


def verify(config):
    for prefix in PREFIXES:
        rules = [r for r in config["locations"] if r.get("locationPrefix") == prefix]
        if len(rules) != 1:
            raise ValueError("missing or duplicate policy for " + prefix)
        rule = rules[0]
        if rule.get("fsync") is not True or rule.get("replication") != "001":
            raise ValueError("durability policy mismatch for " + prefix)
        if rule.get("readOnly", False):
            raise ValueError("bucket is read-only: " + prefix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weed", default="/tools/weed")
    parser.add_argument("--master", required=True)
    parser.add_argument("--filers", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    filers = args.filers.split(",")
    if len(filers) != 2 or any(not f for f in filers):
        parser.error("require exactly two filer endpoints")

    def shell(filer, commands):
        result = subprocess.run(
            [args.weed, "-logtostderr=true", "shell", "-master=" + args.master, "-filer=" + filer],
            input=commands, capture_output=True, text=True, timeout=20,
        )
        if result.returncode:
            raise RuntimeError("weed shell failed for " + filer)
        return result.stdout

    if not args.check_only:
        shell(filers[0], "".join(
            "fs.configure -locationPrefix=" + prefix + " -fsync=true -replication=001 -apply\n"
            for prefix in PREFIXES
        ))
    deadline = time.monotonic() + 30
    while True:
        try:
            for filer in filers:
                verify(read_config(shell(filer, "fs.configure\n")))
            break
        except (ValueError, RuntimeError, subprocess.TimeoutExpired):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    print(json.dumps({"verified_filers": filers, "prefixes": PREFIXES,
                      "fsync": True, "replication": "001", "check_only": args.check_only}))


if __name__ == "__main__":
    main()
