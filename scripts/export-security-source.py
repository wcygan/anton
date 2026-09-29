"""Export a committed website snapshot without ignored files or operator state."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile


INCLUDE = (
    "src", "public", "package.json", "bun.lock", "Dockerfile", ".dockerignore",
    ".github/workflows", "tsconfig.json", "vite.config.ts", "server.ts", "index.html",
)
OPERATOR_FILES = {
    "age.key", "github-deploy.key", "cloudflare-tunnel.json", "kubeconfig",
    "talosconfig", ".npmrc", ".netrc",
}


def git(repository, *args):
    result = subprocess.run(["git", "-C", str(repository), *args], capture_output=True)
    if result.returncode:
        raise ValueError("Git could not resolve or export the selected repository/revision")
    return result.stdout


def atomic_private_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def check_source_path(path):
    if (path.is_absolute() or ".." in path.parts or any(
            part in OPERATOR_FILES or part.startswith(".env") or
            PurePosixPath(part).suffix in {".key", ".pem"} or ".sops." in part
            for part in path.parts)):
        raise ValueError("selected source contains an unsafe or credential-like path; review before export")


def export_source(repository, revision, destination):
    repository = repository.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", repository.name):
        raise ValueError("repository directory name must be a simple archive name")
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("Git did not return a full commit identifier")
    tracked = git(repository, "ls-tree", "-r", "-z", "--name-only", commit).decode().split("\0")
    selected = [prefix for prefix in INCLUDE if any(
        name == prefix or name.startswith(prefix + "/") for name in tracked)]
    if "package.json" not in selected or "Dockerfile" not in selected:
        raise ValueError("expected a website repository with package.json and Dockerfile")
    # Check names and modes before reading any selected Git blob payload.
    entries = git(repository, "ls-tree", "-r", "-z", commit).decode().split("\0")
    for entry in filter(None, entries):
        header, name = entry.split("\t", 1)
        if any(name == prefix or name.startswith(prefix + "/") for prefix in selected):
            check_source_path(PurePosixPath(name))
            if header.split()[0] not in {"100644", "100755"}:
                raise ValueError("selected source contains a link or submodule; review before export")
    data = git(repository, "archive", "--format=tar.gz", commit, "--", *selected)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("archive contains a link or unsafe entry; review before export")
            check_source_path(path)
        files = sorted(member.name for member in members if member.isfile())
        if not {"package.json", "Dockerfile"}.issubset(files):
            raise ValueError("archive attributes excluded required deployment files")
    stem = repository.name + "-" + commit[:12]
    metadata = {
        "sourceRevision": commit, "sourceDirectoryName": repository.name,
        "archive": stem + ".tar.gz", "manifest": stem + ".json",
        "sha256": hashlib.sha256(data).hexdigest(),
        "includedPaths": selected, "files": files,
        "excluded": ["local edits", "Git metadata/history", "ignored files", "operator manifests", "docs"],
    }
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_private_write(destination / metadata["archive"], data)
    atomic_private_write(destination / metadata["manifest"], (json.dumps(metadata, indent=2) + "\n").encode())
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="explicit source commit/ref; local edits are excluded")
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / ".private/security-review/source-bundles"
    try:
        metadata = export_source(args.repository, args.revision, destination)
    except (ValueError, OSError, UnicodeError, tarfile.TarError) as error:
        parser.exit(1, f"Export stopped: {error}\n")
    print(json.dumps({"archive": str(destination / metadata["archive"]),
                      "manifest": str(destination / metadata["manifest"]),
                      "sourceRevision": metadata["sourceRevision"], "fileCount": len(metadata["files"])}))


if __name__ == "__main__":
    main()
