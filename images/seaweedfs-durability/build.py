#!/usr/bin/env python3
"""Build a local amd64 runtime from pinned source and the reviewed patch."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = "530be3e37337488ecc34d58441e0bc476e121c93"


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", default="localhost/anton/seaweedfs:4.48-durable1")
    args = parser.parse_args()
    out = args.output.resolve()
    assert not out.exists(), "refuse to overwrite build evidence"
    version = subprocess.check_output(["go", "version"], text=True).strip()
    assert " go1.26.7 " in version, version
    fixture = ROOT / "scripts/fixtures/seaweedfs-durability"
    run([sys.executable, str(fixture / "prepare.py"), "--source-repo",
         str(args.source_repo.resolve()), "--output", str(out / "source")])
    context = out / "image"
    context.mkdir()
    shutil.copyfile(Path(__file__).with_name("Dockerfile"), context / "Dockerfile")
    env = dict(os.environ, GOMAXPROCS="4", CGO_ENABLED="0", GOOS="linux", GOARCH="amd64")
    run(["go", "build", "-trimpath", "-buildvcs=false", "-p", "4", "-ldflags",
         "-X github.com/seaweedfs/seaweedfs/weed/util/version.COMMIT=" + UPSTREAM + "+durable1",
         "-o", str(context / "weed"), "./weed"], cwd=out / "source/candidate", env=env)
    patch_hash = hashlib.sha256((fixture / "durable-ack.patch").read_bytes()).hexdigest()
    run(["docker", "build", "--platform", "linux/amd64", "--tag", args.tag,
         "--label", "org.opencontainers.image.revision=" + UPSTREAM,
         "--label", "io.anton.durability-patch.sha256=" + patch_hash, str(context)])
    info = json.loads(subprocess.check_output(["docker", "image", "inspect", args.tag]))[0]
    assert info["Architecture"] == "amd64" and info["Os"] == "linux"
    identity = dict(source_commit=UPSTREAM, go_version=version, patch_sha256=patch_hash,
                    binary_sha256=hashlib.sha256((context / "weed").read_bytes()).hexdigest(),
                    image_id=info["Id"], platform="linux/amd64", tag=args.tag)
    (out / "build-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(json.dumps(identity, indent=2))


if __name__ == "__main__":
    main()
