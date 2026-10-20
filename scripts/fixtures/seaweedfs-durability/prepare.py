#!/usr/bin/env python3
"""Export immutable upstream source and install a bounded durability experiment."""

import argparse, hashlib, io, json, shutil, subprocess, tarfile
from pathlib import Path

PIN = "530be3e37337488ecc34d58441e0bc476e121c93"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-repo", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    fixture = Path(__file__).resolve().parent
    revision = subprocess.check_output(
        ["git", "-C", str(a.source_repo), "rev-parse", "4.48"], text=True
    ).strip()
    assert revision == PIN, "upstream tag changed"
    assert not a.output.exists(), "refuse to overwrite existing evidence"
    a.output.mkdir(parents=True)
    raw = subprocess.check_output(
        [
            "git",
            "-C",
            str(a.source_repo),
            "archive",
            PIN,
            "go.mod",
            "go.sum",
            "weed",
            "telemetry",
        ]
    )
    for version in ["baseline", "candidate"]:
        target = a.output / version
        target.mkdir()
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(target, filter="data")
        for source, dest in [
            (
                "volume_durability_test.go",
                "weed/storage/qualification_durability_test.go",
            ),
            (
                "independent_index_test.go",
                "weed/storage/qualification_eager_index_test.go",
            ),
            (
                "metadata_durability_test.go",
                "weed/filer/leveldb2/qualification_durability_test.go",
            ),
        ]:
            shutil.copyfile(fixture / source, target / dest)
    with (fixture / "durable-ack.patch").open() as patch:
        subprocess.run(
            ["patch", "-p1", "--batch"],
            cwd=a.output / "candidate",
            stdin=patch,
            check=True,
        )
    (a.output / "identity.json").write_text(
        json.dumps(
            {
                "source_commit": PIN,
                "source_archive_sha256": hashlib.sha256(raw).hexdigest(),
                "fixture_files": {
                    f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                    for f in fixture.iterdir()
                    if f.is_file()
                },
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
