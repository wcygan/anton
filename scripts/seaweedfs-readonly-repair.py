#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Repair one read-only SeaweedFS volume copy from its healthy peer, preview first.

`plan` also classifies writable copies whose live needles differ: when no
filer references the differing needles it accepts the divergence (nothing to
repair), otherwise it stops with the candidate repair, which this tool does
not run.

Run the subcommands in order; each writes evidence under
<repo-root>/.private/seaweedfs-repair/volume-<id>/:

  plan <id>      Read-only. Topology, read-only cause or differing needles,
                 check.disk simulation, volume.fsck reference join against
                 every filer, file hashes, recommended action.
  preserve <id>  Copy .dat/.idx/.sdx/.vif of every copy and write SHA256SUMS.
  rehearse <id>  Replay the planned repair on the preserved files in Docker with
                 the production image digest, restart every server, check reads.
  apply <id>     Preview the planned repair; with ANTON_DESTRUCTIVE_OK=1, run it.
                 Refuses unless plan, rehearsal and the live files share hashes.
  verify <id>    Read-only. Gauge, check.disk -slow, every referenced needle read
                 from every copy, and each index ending at its data size.

Procedure: .agents/skills/seaweedfs-ops/references/health-alerts.md
("Repair one read-only copy from its healthy peer"). Pass the canonical
checkout with --repo-root when running from a worktree.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from agent_policy_contract import destructive_command_violation, secret_output_violation  # noqa: E402
from cluster_target_contract import TargetPreflightError, anton_kubectl_prefix, preflight_command  # noqa: E402
from seaweedfs_repair import (  # noqa: E402
    COMPACTION_EXTENSIONS,
    REQUIRED_EXTENSIONS,
    CopyFacts,
    DataCheck,
    FsckReport,
    IndexState,
    MissingChunks,
    NeedleHeader,
    RepairError,
    Step,
    SuperBlock,
    Topology,
    VolumeInfo,
    append_time_offset,
    check_data,
    check_disk_diff,
    check_disk_shortfall,
    copy_count,
    cross_check,
    decide,
    differing_needles,
    file_id,
    key_hex,
    parse_check_disk,
    parse_fsck,
    parse_missing_chunks,
    parse_volume_list,
    validate_steps,
    volume_base_name,
    weed_mutation,
)

NAMESPACE = "storage"
INSTANCE = "app.kubernetes.io/instance=seaweedfs"
PROMETHEUS = "/api/v1/namespaces/observability/services/http:kube-prometheus-stack-prometheus:9090/proxy"
GAUGE = 'SeaweedFS_volumeServer_read_only_volumes{namespace="storage",type="IsReadOnly"}'
APPROVAL = "ANTON_DESTRUCTIVE_OK"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
COLLECTION = re.compile(r"^[A-Za-z0-9._-]*$")
TAILNET = re.compile(r"[A-Za-z0-9-]+\.ts\.net\b")
INTEGRITY_FAILURE = re.compile(r"volumeDataIntegrityChecking failed|actual \d+ bytes expected \d+ bytes")
SHELL_TIMEOUT = 1800.0
RESTART_SETTLE = 5.0
TOPOLOGY_TIMEOUT = 120.0
SAMPLE = 20
PLAN_SCHEMA = 2

FILE_STATUS_SCRIPT = r"""
set -eu
cd "$1"
for ext in .dat .idx .sdx .vif .cpd .cpx .cpldb; do
  f="$2$ext"
  [ -e "$f" ] || continue
  sum=-
  if [ -f "$f" ] && { [ "$3" = all ] || { [ "$3" = small ] && [ "$ext" != .dat ]; }; }; then
    sum=$(sha256sum "$f" | cut -d ' ' -f 1)
  fi
  echo "$f $(stat -c %s "$f") $sum"
done
"""
RANGES_SCRIPT = r"""
set -eu
f="$1"
shift
for off in "$@"; do
  dd if="$f" bs=8 skip=$((off / 8)) count=2 2>/dev/null | od -An -tx1 -v | tr -d ' \n'
  echo
done
"""
READ_SCRIPT = r"""
set -u
set -o pipefail
while read -r server fid; do
  if sum=$(wget -q -T 60 -O - "http://$server/$fid?cm=false" | sha256sum); then
    echo "OK $server $fid ${sum%% *}"
  else
    echo "FAIL $server $fid"
  fi
done
"""

SCRIPT_NAMES = {FILE_STATUS_SCRIPT: "$FILE_STATUS_SCRIPT", RANGES_SCRIPT: "$RANGES_SCRIPT", READ_SCRIPT: "$READ_SCRIPT"}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact(text: str) -> str:
    return TAILNET.sub("<tailnet-name>.ts.net", text)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class State:
    """Evidence for one volume in the canonical checkout's ignored .private/ tree."""

    def __init__(self, root: Path, volume_id: int):
        self.dir = root / ".private" / "seaweedfs-repair" / f"volume-{volume_id}"

    def path(self, name: str) -> Path:
        return self.dir / name

    def write_json(self, name: str, document: object) -> Path:
        return self.write_text(name, json.dumps(document, indent=2, sort_keys=True) + "\n")

    def write_text(self, name: str, text: str) -> Path:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text)
        temporary.replace(path)
        return path

    def read_json(self, name: str) -> dict:
        path = self.path(name)
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            raise RepairError(f"{path} is missing; run the earlier subcommand first") from None

    def read_plan(self) -> dict:
        plan = self.read_json("plan.json")
        if plan.get("schema") != PLAN_SCHEMA:
            raise RepairError(f"{self.path('plan.json')} was written by an older version of this tool; run plan again")
        return plan

    def digest(self, name: str) -> str:
        return sha256_file(self.path(name))


class CommandLog:
    """Print every external command before it runs, and keep a copy with the evidence."""

    def __init__(self, path: Path | None = None, stream=None):
        self.path = path
        self.stream = stream

    def __call__(self, argv: Sequence[str], note: str = "") -> None:
        line = redact(shlex.join(SCRIPT_NAMES.get(arg, arg) for arg in argv)) + (f"  # {note}" if note else "")
        print(f"+ {line}", file=self.stream or sys.stderr, flush=True)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as handle:
                handle.write(f"{utc_now()} {line}\n")


@dataclass(frozen=True)
class ShellResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def text(self) -> str:
        """stdout and stderr together, with a non-zero exit reported as an error line."""
        text = self.stdout if not self.stderr else f"{self.stdout}\n{self.stderr}"
        return text if self.returncode == 0 else f"{text}\nerror: weed shell exited {self.returncode}"


@dataclass(frozen=True)
class ServerPod:
    server: str
    pod: str
    node: str
    data_dir: str


@dataclass(frozen=True)
class Runtime:
    image: str
    master_pod: str
    master_host: str
    servers: Mapping[str, ServerPod]
    volume_port: int
    max_volumes: int
    volume_size_limit_mb: int
    default_replication: str
    filers: tuple[str, ...]

    def to_json(self) -> dict:
        return {
            "image": self.image,
            "master_pod": self.master_pod,
            "master_host": self.master_host,
            "servers": {s: {"pod": p.pod, "node": p.node, "data_dir": p.data_dir} for s, p in self.servers.items()},
            "volume_port": self.volume_port,
            "max_volumes": self.max_volumes,
            "volume_size_limit_mb": self.volume_size_limit_mb,
            "default_replication": self.default_replication,
            "filers": list(self.filers),
        }

    @classmethod
    def from_json(cls, value: Mapping) -> Runtime:
        return cls(
            value["image"],
            value["master_pod"],
            value["master_host"],
            {s: ServerPod(s, p["pod"], p["node"], p["data_dir"]) for s, p in value["servers"].items()},
            value["volume_port"],
            value["max_volumes"],
            value["volume_size_limit_mb"],
            value["default_replication"],
            tuple(value["filers"]),
        )


def _container_command(pod: Mapping, container: str) -> str:
    for spec in pod.get("spec", {}).get("containers", []):
        if spec.get("name") == container:
            return " ".join([*spec.get("command", []), *spec.get("args", [])])
    raise RepairError(f"{pod['metadata']['name']} has no {container} container")


def _flag(command: str, name: str) -> str | None:
    match = re.search(rf"(?:^|\s)-{re.escape(name)}=(\S+)", command)
    return match.group(1) if match else None


def _image_id(pod: Mapping, container: str) -> str:
    for status in pod.get("status", {}).get("containerStatuses", []):
        if status.get("name") == container:
            image = str(status.get("imageID", "")).removeprefix("docker-pullable://")
            if "@sha256:" in image:
                return image
    raise RepairError(f"{pod['metadata']['name']}: {container} has no image digest")


def _ready(pod: Mapping) -> bool:
    return not pod["metadata"].get("deletionTimestamp") and any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod.get("status", {}).get("conditions", [])
    )


def parse_runtime(volume_pods: Mapping, master_pods: Mapping, filer_pods: Mapping) -> Runtime:
    """Read server addresses, flags and the image digest from the live pod specs."""
    images: set[str] = set()
    servers: dict[str, ServerPod] = {}
    ports: set[int] = set()
    maxima: set[int] = set()
    for pod in volume_pods.get("items", []):
        name = pod["metadata"]["name"]
        command = _container_command(pod, "volume")
        values = {flag: _flag(command, flag) for flag in ("ip", "port", "dir", "max")}
        if None in values.values():
            raise RepairError(f"{name}: volume command lacks one of -ip/-port/-dir/-max")
        host = str(values["ip"]).replace("$(POD_NAME)", name)
        server = f"{host}:{values['port']}"
        servers[server] = ServerPod(server, name, pod.get("spec", {}).get("nodeName", ""), str(values["dir"]).rstrip("/") or "/")
        ports.add(int(str(values["port"])))
        maxima.add(int(str(values["max"])))
        images.add(_image_id(pod, "volume"))
    if not servers or len(ports) != 1 or len(maxima) != 1:
        raise RepairError("volume pods are missing or disagree on -port/-max")
    masters = sorted((pod for pod in master_pods.get("items", []) if _ready(pod)), key=lambda pod: pod["metadata"]["name"])
    if not masters:
        raise RepairError("no Ready SeaweedFS master pod")
    images.update(_image_id(pod, "master") for pod in master_pods["items"])
    filers: list[str] = []
    for pod in filer_pods.get("items", []):
        command = _container_command(pod, "filer")
        host, port = _flag(command, "ip"), _flag(command, "port")
        if not host or not port:
            raise RepairError(f"{pod['metadata']['name']}: filer command lacks -ip/-port")
        filers.append(f"{host.replace('$(POD_NAME)', pod['metadata']['name'])}:{port}")
        images.add(_image_id(pod, "filer"))
    if not filers:
        raise RepairError("no SeaweedFS filer pod; volume.fsck needs every filer's store")
    if len(images) != 1:
        raise RepairError(f"SeaweedFS pods run different images: {sorted(images)}")
    master = masters[0]
    command = _container_command(master, "master")
    limit, replication = _flag(command, "volumeSizeLimitMB"), _flag(command, "defaultReplication")
    host = (_flag(command, "ip") or "").replace("$(POD_NAME)", master["metadata"]["name"])
    if not limit or not replication or not host:
        raise RepairError("master command lacks -ip/-volumeSizeLimitMB/-defaultReplication")
    return Runtime(
        images.pop(), master["metadata"]["name"], host, servers, ports.pop(), maxima.pop(), int(limit), replication, tuple(sorted(filers))
    )


def parse_file_status(text: str) -> dict[str, dict]:
    files: dict[str, dict] = {}
    for line in text.splitlines():
        name, size, digest = line.split(" ")
        files[name] = {"size": int(size), "sha256": None if digest == "-" else digest}
    return files


def parse_needle_reads(text: str) -> dict[tuple[str, str], str | None]:
    results: dict[tuple[str, str], str | None] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "OK":
            results[(parts[1], parts[2])] = None if parts[3] == EMPTY_SHA256 else parts[3]
        elif len(parts) == 3 and parts[0] == "FAIL":
            results[(parts[1], parts[2])] = None
        else:
            raise RepairError(f"unexpected read output: {line}")
    return results


@dataclass(frozen=True)
class CopyView:
    """Enough of one copy's files to analyze it without holding the .dat."""

    server: str
    index: bytes
    dat_size: int
    superblock: bytes
    vif: bytes
    read_headers: Callable[[Sequence[int]], list[bytes]]

    def read_header(self, offset: int) -> bytes:
        return self.read_headers([offset])[0]


def local_view(server: str, directory: Path, base: str) -> CopyView:
    dat = directory / f"{base}.dat"

    def read_headers(offsets: Sequence[int]) -> list[bytes]:
        with dat.open("rb") as handle:
            headers = []
            for offset in offsets:
                handle.seek(offset)
                headers.append(handle.read(16))
            return headers

    return CopyView(
        server,
        (directory / f"{base}.idx").read_bytes(),
        dat.stat().st_size,
        read_headers([0])[0][:8],
        (directory / f"{base}.vif").read_bytes(),
        read_headers,
    )


class Backend(Protocol):
    def weed_shell(self, commands: Sequence[str], *, approved: bool = False, timeout: float = SHELL_TIMEOUT) -> ShellResult: ...
    def read_needles(self, reads: Sequence[tuple[str, str]]) -> dict[tuple[str, str], str | None]: ...
    def copy_view(self, server: str, base: str) -> CopyView: ...
    def marker(self, server: str, base: str) -> tuple[bytes, int]: ...


class Kube:
    """kubectl bound to the verified Anton target, checked with the shared hook policy."""

    def __init__(
        self,
        prefix: Sequence[str],
        root: Path,
        log: CommandLog,
        *,
        runner=subprocess.run,
        popen=subprocess.Popen,
        preflight=preflight_command,
    ):
        self.prefix = tuple(prefix)
        self.root = root
        self.log = log
        self.runner = runner
        self.popen = popen
        self.preflight = preflight
        self.preflight_passed = False

    def _guard(self, argv: Sequence[str], mutation: bool, note: str = "") -> None:
        """Apply the guard hooks' rules to a command the hooks cannot see.

        Every command shares the verified prefix, so the hook's target preflight
        runs once, at the first exec, rather than again between repair steps.
        """
        text = shlex.join(argv)
        for violation in (destructive_command_violation(text), secret_output_violation(text)):
            if violation is not None:
                raise RepairError(f"agent policy {violation.code}: {violation.message}")
        if mutation and not self.preflight_passed:
            failures = self.preflight(text, self.root)
            if failures:
                raise RepairError("target preflight: " + "; ".join(redact(failure.message) for failure in failures))
            self.preflight_passed = True
        self.log(argv, note)

    def run(
        self,
        args: Sequence[str],
        *,
        input: bytes | None = None,
        timeout: float = 120.0,
        mutation: bool = False,
        note: str = "",
    ) -> subprocess.CompletedProcess:
        argv = [*self.prefix, *args]
        self._guard(argv, mutation, note)
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        try:
            return self.runner(argv, capture_output=True, timeout=timeout, check=False, **stdin)
        except subprocess.TimeoutExpired:
            raise RepairError(f"timed out after {timeout:.0f}s: {redact(shlex.join(args))}") from None

    def checked(self, args: Sequence[str], **kwargs) -> bytes:
        result = self.run(args, **kwargs)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip() if isinstance(result.stderr, bytes) else str(result.stderr)
            raise RepairError(f"kubectl {' '.join(args[:4])} failed (exit {result.returncode}): {redact(message)}")
        return result.stdout

    def stream_to(self, args: Sequence[str], destination: Path, *, timeout: float) -> tuple[int, str]:
        argv = [*self.prefix, *args]
        self._guard(argv, mutation=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        process = self.popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stderr: list[bytes] = []
        drain = threading.Thread(target=lambda: stderr.append(process.stderr.read()), daemon=True)
        watchdog = threading.Timer(timeout, process.kill)
        drain.start()
        watchdog.start()
        digest, size = hashlib.sha256(), 0
        try:
            with destination.open("wb") as handle:
                while chunk := process.stdout.read(1 << 20):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            returncode = process.wait()
        finally:
            watchdog.cancel()
            drain.join(timeout=10)
        if returncode != 0:
            message = redact(b"".join(stderr).decode("utf-8", "replace"))
            raise RepairError(f"copying {destination.name} failed (exit {returncode}): {message}")
        return size, digest.hexdigest()


class Cluster:
    """The live SeaweedFS deployment, reached only through Kube."""

    def __init__(self, kube: Kube):
        self.kube = kube
        self._runtime: Runtime | None = None

    @property
    def runtime(self) -> Runtime:
        return self._runtime or self.discover()

    def discover(self) -> Runtime:
        def pods(component: str) -> dict:
            selector = f"{INSTANCE},app.kubernetes.io/component={component}"
            return json.loads(self.kube.checked(["-n", NAMESPACE, "get", "pods", "-l", selector, "-o", "json"]))

        self._runtime = parse_runtime(pods("volume"), pods("master"), pods("filer"))
        return self._runtime

    def weed_shell(
        self, commands: Sequence[str], *, approved: bool = False, timeout: float = SHELL_TIMEOUT, filer: str | None = None
    ) -> ShellResult:
        mutating = [command for command in commands if weed_mutation(command)]
        if mutating and not approved:
            raise RepairError(f"refusing unapproved weed shell mutation: {mutating}")
        shell = ["weed", "shell", "-master=localhost:9333", *([f"-filer={filer}"] if filer else [])]
        result = self.kube.run(
            ["-n", NAMESPACE, "exec", "-i", self.runtime.master_pod, "-c", "master", "--", *shell],
            input="".join(f"{command}\n" for command in commands).encode(),
            timeout=timeout,
            mutation=True,
            note="weed shell: " + "; ".join(commands),
        )
        return ShellResult(result.returncode, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace"))

    def fsck(self, command: str) -> tuple[FsckReport, dict[str, str]]:
        """Run one read-only fsck against each filer's store; weed shell alone picks a filer at random."""
        outputs = {filer: self.weed_shell(["lock", command, "unlock"], filer=filer).text for filer in self.runtime.filers}
        return FsckReport.intersect([parse_fsck(text) for text in outputs.values()]), outputs

    def missing_chunks(self, command: str) -> tuple[MissingChunks, dict[str, str]]:
        """The same per-filer walk with -findMissingChunksInFiler: references a copy cannot serve."""
        outputs = {filer: self.weed_shell(["lock", command, "unlock"], filer=filer).text for filer in self.runtime.filers}
        return MissingChunks.union([parse_missing_chunks(text) for text in outputs.values()]), outputs

    def _pod(self, server: str) -> ServerPod:
        try:
            return self.runtime.servers[server]
        except KeyError:
            raise RepairError(f"{server} is not a known volume pod") from None

    def _exec(self, server: str, argv: Sequence[str], *, timeout: float = 900.0) -> bytes:
        pod = self._pod(server).pod
        return self.kube.checked(["-n", NAMESPACE, "exec", pod, "-c", "volume", "--", *argv], timeout=timeout, mutation=True)

    def file_status(self, server: str, base: str, mode: str) -> dict[str, dict]:
        pod = self._pod(server)
        output = self._exec(server, ["sh", "-c", FILE_STATUS_SCRIPT, "sh", pod.data_dir, base, mode])
        return parse_file_status(output.decode())

    def read_file(self, server: str, name: str) -> bytes:
        return self._exec(server, ["cat", f"{self._pod(server).data_dir}/{name}"])

    def read_ranges(self, server: str, name: str, offsets: Sequence[int]) -> list[bytes]:
        if not offsets:
            return []
        if any(offset % 8 for offset in offsets):
            raise RepairError("needle offsets must be 8-byte aligned")
        headers: list[bytes] = []
        for start in range(0, len(offsets), 2000):
            batch = offsets[start : start + 2000]
            output = self._exec(server, ["sh", "-c", RANGES_SCRIPT, "sh", f"{self._pod(server).data_dir}/{name}", *map(str, batch)])
            lines = output.decode().splitlines()
            if len(lines) != len(batch):
                raise RepairError(f"{server}: expected {len(batch)} header reads, got {len(lines)}")
            headers.extend(bytes.fromhex(line.strip()) for line in lines)
        return headers

    def copy_view(self, server: str, base: str, status: Mapping[str, dict] | None = None) -> CopyView:
        """Read one copy's index, then its sizes: a .dat append precedes its index entry."""
        index = self.read_file(server, f"{base}.idx")
        status = status or self.file_status(server, base, "stat")
        missing = [base + ext for ext in REQUIRED_EXTENSIONS if base + ext not in status]
        if missing:
            raise RepairError(f"{server} lacks {', '.join(missing)}")
        expected = status[f"{base}.idx"].get("sha256")
        if expected and hashlib.sha256(index).hexdigest() != expected:
            raise RepairError(f"{server}: {base}.idx changed while it was read; fence writers and retry")
        return CopyView(
            server,
            index,
            status[f"{base}.dat"]["size"],
            self.read_ranges(server, f"{base}.dat", [0])[0][:8],
            self.read_file(server, f"{base}.vif"),
            lambda offsets: self.read_ranges(server, f"{base}.dat", offsets),
        )

    def marker(self, server: str, base: str) -> tuple[bytes, int]:
        index = self.read_file(server, f"{base}.idx")
        return index, self.file_status(server, base, "stat")[f"{base}.dat"]["size"]

    def stream_file(self, server: str, name: str, destination: Path) -> tuple[int, str]:
        pod = self._pod(server)
        return self.kube.stream_to(
            ["-n", NAMESPACE, "exec", pod.pod, "-c", "volume", "--", "cat", f"{pod.data_dir}/{name}"],
            destination,
            timeout=3600,
        )

    def read_needles(self, reads: Sequence[tuple[str, str]]) -> dict[tuple[str, str], str | None]:
        if not reads:
            return {}
        output = self.kube.checked(
            ["-n", NAMESPACE, "exec", "-i", self.runtime.master_pod, "-c", "master", "--", "sh", "-c", READ_SCRIPT],
            input="".join(f"{server} {fid}\n" for server, fid in reads).encode(),
            timeout=max(300.0, 2.0 * len(reads)),
            mutation=True,
            note=f"{len(reads)} needle reads",
        )
        return parse_needle_reads(output.decode())

    def volume_logs(self, server: str, base: str) -> list[str]:
        output = self.kube.checked(["-n", NAMESPACE, "logs", self._pod(server).pod, "-c", "volume", "--limit-bytes=8000000"], timeout=120)
        return [line for line in output.decode("utf-8", "replace").splitlines() if f"/{base}." in line][:SAMPLE]

    def read_only_gauge(self) -> list[dict]:
        output = self.kube.checked(["get", "--raw", f"{PROMETHEUS}/api/v1/query?{urlencode({'query': GAUGE})}"], timeout=60)
        document = json.loads(output)
        if document.get("status") != "success":
            raise RepairError("Prometheus query for the read-only gauge failed")
        return [
            {"pod": item["metric"].get("pod", ""), "collection": item["metric"].get("collection", ""), "value": float(item["value"][1])}
            for item in document["data"]["result"]
        ]


def production_cluster(root: Path, log: CommandLog) -> Cluster:
    return Cluster(Kube(anton_kubectl_prefix(root), root, log))


class DockerCluster:
    """A disposable master plus one volume server per production server, same names and image."""

    LABEL = "anton.seaweedfs-rehearsal"

    def __init__(self, runtime: Runtime, work: Path, tag: str, log: CommandLog, *, runner=subprocess.run):
        self.runtime = runtime
        self.work = work
        self.tag = tag
        self.log = log
        self.runner = runner
        self.network = f"swfs-rehearse-{tag}"
        self.master = f"{self.network}-master"
        self.containers = {server: f"{self.network}-{pod.pod}" for server, pod in runtime.servers.items()}

    def docker(
        self, *args: str, input: bytes | None = None, timeout: float = 300.0, check: bool = True, note: str = ""
    ) -> subprocess.CompletedProcess:
        argv = ["docker", *args]
        self.log(argv, note)
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        try:
            result = self.runner(argv, capture_output=True, timeout=timeout, check=False, **stdin)
        except subprocess.TimeoutExpired:
            raise RepairError(f"timed out after {timeout:.0f}s: {shlex.join(argv)}") from None
        if check and result.returncode != 0:
            raise RepairError(f"{shlex.join(argv[:4])} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
        return result

    def data_dir(self, server: str) -> Path:
        return self.work / self.runtime.servers[server].pod

    def image_present(self) -> bool:
        return self.docker("image", "inspect", self.runtime.image, check=False).returncode == 0

    def cleanup(self) -> None:
        listed = self.docker("ps", "-aq", "--filter", f"label={self.LABEL}={self.tag}", check=False)
        ids = listed.stdout.decode().split()
        if ids:
            self.docker("rm", "-f", *ids, check=False)
        self.docker("network", "rm", self.network, check=False)

    def start(self) -> None:
        self.cleanup()
        self.docker("network", "create", "--label", f"{self.LABEL}={self.tag}", self.network)
        common = ["run", "-d", "--label", f"{self.LABEL}={self.tag}", "--network", self.network]
        self.docker(
            *common, "--name", self.master, "--network-alias", self.runtime.master_host, "--entrypoint", "weed", self.runtime.image,
            "-logtostderr=true", "master", f"-ip={self.runtime.master_host}", "-ip.bind=0.0.0.0", "-port=9333", "-mdir=/tmp",
            f"-volumeSizeLimitMB={self.runtime.volume_size_limit_mb}", f"-defaultReplication={self.runtime.default_replication}",
            "-telemetry=false",
        )
        for server, pod in self.runtime.servers.items():
            host = server.rsplit(":", 1)[0]
            self.docker(
                *common, "--name", self.containers[server], "--network-alias", host,
                "-v", f"{self.data_dir(server)}:{pod.data_dir}", "--entrypoint", "weed", self.runtime.image,
                "-logtostderr=true", "volume", f"-port={self.runtime.volume_port}", f"-max={self.runtime.max_volumes}",
                f"-ip={host}", "-ip.bind=0.0.0.0", f"-mserver={self.runtime.master_host}:9333", f"-dir={pod.data_dir}",
            )

    def weed_shell(self, commands: Sequence[str], *, approved: bool = False, timeout: float = SHELL_TIMEOUT) -> ShellResult:
        result = self.docker(
            "exec", "-i", self.master, "weed", "shell", "-master=localhost:9333",
            input="".join(f"{command}\n" for command in commands).encode(), timeout=timeout, check=False,
            note="weed shell: " + "; ".join(commands),
        )
        return ShellResult(result.returncode, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace"))

    def read_needles(self, reads: Sequence[tuple[str, str]]) -> dict[tuple[str, str], str | None]:
        if not reads:
            return {}
        result = self.docker(
            "exec", "-i", self.master, "sh", "-c", READ_SCRIPT,
            input="".join(f"{server} {fid}\n" for server, fid in reads).encode(), timeout=max(300.0, 2.0 * len(reads)),
            note=f"{len(reads)} needle reads",
        )
        return parse_needle_reads(result.stdout.decode())

    def copy_view(self, server: str, base: str) -> CopyView:
        return local_view(server, self.data_dir(server), base)

    def marker(self, server: str, base: str) -> tuple[bytes, int]:
        return (self.data_dir(server) / f"{base}.idx").read_bytes(), (self.data_dir(server) / f"{base}.dat").stat().st_size

    def restart_volumes(self) -> None:
        before = {server: self.started_at(server) for server in self.containers}
        self.docker("restart", *self.containers.values())
        unchanged = [server for server in self.containers if self.started_at(server) == before[server]]
        if unchanged:
            raise RepairError(f"containers did not restart: {unchanged}")
        time.sleep(RESTART_SETTLE)

    def started_at(self, server: str) -> str:
        return self.docker("inspect", "-f", "{{.State.StartedAt}}", self.containers[server]).stdout.decode().strip()

    def logs(self, server: str) -> list[str]:
        result = self.docker("logs", self.containers[server], check=False)
        return (result.stdout + result.stderr).decode("utf-8", "replace").splitlines()


# --- Shared checks ---------------------------------------------------------


def wait_for_topology(backend: Backend, volume_id: int, expected: Mapping[str, bool]) -> list[str]:
    """Poll volume.list until the copies sit on `expected` servers with the given read-only flags."""
    deadline = time.monotonic() + TOPOLOGY_TIMEOUT
    while True:
        problems: list[str] = []
        try:
            shell = backend.weed_shell(["volume.list"], timeout=60)
            copies = {copy.server: copy.read_only for copy in parse_volume_list(shell.stdout).copies_of(volume_id)}
            if copies != dict(expected):
                problems.append(f"volume {volume_id} copies are {copies}, expected {dict(expected)}")
        except RepairError as error:
            problems.append(str(error))
        if not problems or time.monotonic() >= deadline:
            return problems
        time.sleep(3)


def referenced_fids(view: CopyView, state: IndexState, keys: Sequence[int], volume_id: int) -> dict[int, str]:
    """Build fids from the needle headers the index points at; the cookie is not in the index."""
    keys = sorted(keys)
    headers = view.read_headers([state.present[key].offset for key in keys]) if keys else []
    fids: dict[int, str] = {}
    for key, raw in zip(keys, headers):
        header = NeedleHeader.parse(raw)
        if header.key != key or header.size != state.present[key].size:
            raise RepairError(f"{view.server}: needle header at key {key:x} does not match its index entry")
        fids[key] = file_id(volume_id, key, header.cookie)
    return fids


def check_reads(backend: Backend, servers: Sequence[str], fids: Mapping[int, str], baseline: Mapping[str, str] | None = None) -> dict:
    results = backend.read_needles([(server, fid) for fid in fids.values() for server in servers])
    failures: list[str] = []
    for fid in fids.values():
        hashes = {server: results.get((server, fid)) for server in servers}
        if None in hashes.values():
            failures.append(f"{fid} unreadable on {sorted(s for s, h in hashes.items() if h is None)}")
        elif len(set(hashes.values())) != 1:
            failures.append(f"{fid} differs between copies")
        elif baseline is not None and baseline.get(fid) != next(iter(hashes.values())):
            failures.append(f"{fid} differs from its bytes before the repair")
    return {"servers": list(servers), "needles": len(fids), "reads": len(results), "failures": failures[:SAMPLE], "failed": len(failures)}


def disk_check(
    backend: Backend,
    volume_id: int,
    states: Mapping[str, IndexState],
    accepted: Mapping[str, frozenset[int]],
    referenced: frozenset[int],
) -> dict:
    """check.disk -slow -syncDeleted must find nothing to sync beyond the planned divergence."""
    command = f"volume.check.disk -volumeId={volume_id} -slow -syncDeleted -v"
    shell = backend.weed_shell(["lock", command, "unlock"])
    report = parse_check_disk(shell.text)
    failures = report.problems() + cross_check(report, states, volume_id)
    if shell.returncode != 0:
        failures.append(f"weed shell exited {shell.returncode}")
    if len(states) > 1 and not any(line.volume_id == volume_id for line in report.sync):
        failures.append("check.disk did not compare the copies")
    for source, target in itertools.permutations(states, 2):
        diff = check_disk_diff(states[source], states[target])
        if diff.partially_deleted:
            failures.append(f"{target} missed {len(diff.partially_deleted)} deletion(s) from {source}")
        unexpected = diff.absent - accepted.get(target, frozenset())
        if unexpected:
            failures.append(f"{target} lacks {len(unexpected)} needle(s) live on {source}")
        if diff.absent & referenced:
            failures.append(f"{target} lacks {len(diff.absent & referenced)} referenced needle(s)")
    return {"command": command, "failures": failures, "output": shell.text.splitlines()}


@dataclass(frozen=True)
class CopyCheck:
    views: Mapping[str, CopyView]
    states: Mapping[str, IndexState]
    tails: Mapping[str, dict]

    def failures(self) -> list[str]:
        return [
            f"{server}: index does not end at its data size ({tail['status']})"
            for server, tail in self.tails.items()
            if tail["status"] != "consistent"
        ]


def tail_checks(backend: Backend, servers: Sequence[str], base: str, volume_id: int) -> CopyCheck:
    views: dict[str, CopyView] = {}
    states: dict[str, IndexState] = {}
    tails: dict[str, dict] = {}
    for server in servers:
        view = backend.copy_view(server, base)
        state = IndexState.parse(view.index)
        superblock = SuperBlock.parse(view.superblock)
        data = check_data(state, view.dat_size, view.read_header, data_start=superblock.data_start, version=superblock.version)
        views[server], states[server], tails[server] = view, state, data_json(data, volume_id)
    return CopyCheck(views, states, tails)


def settled_checks(
    backend: Backend,
    volume_id: int,
    servers: Sequence[str],
    base: str,
    accepted: Mapping[str, frozenset[int]],
    referenced_for: Callable[[Mapping[str, IndexState]], frozenset[int]],
    *,
    attempts: int = 3,
) -> tuple[CopyCheck, frozenset[int], dict]:
    """Tail checks and check.disk over one window in which no copy grew or changed its index."""
    for _ in range(attempts):
        copies = tail_checks(backend, servers, base, volume_id)
        referenced = referenced_for(copies.states)
        disk = disk_check(backend, volume_id, copies.states, accepted, referenced)
        if all(backend.marker(server, base) == (copies.views[server].index, copies.views[server].dat_size) for server in servers):
            return copies, referenced, disk
    disk["failures"].append(f"the indexes kept changing during {attempts} attempts; fence writers and verify again")
    return copies, referenced, disk


def evaluate_shell_step(step: Step, shell: ShellResult, volume_id: int) -> list[str]:
    failures: list[str] = []
    if shell.returncode != 0:
        failures.append(f"weed shell exited {shell.returncode}")
    if step.name not in ("fix-read-only", "converge-deletions"):
        failures += [line for line in shell.text.splitlines() if line.startswith(("error:", "unknown command:"))]
        return failures
    report = parse_check_disk(shell.text)
    failures += report.problems()
    if report.resurrected:
        failures.append(f"check.disk wrote {len(report.resurrected)} needle(s); the plan only syncs deletions")
    if writable := step.expect.get("writable"):
        if (volume_id, writable) not in report.synced_writable:
            failures.append(f"check.disk did not report {writable} synced and writable")
        if (volume_id, writable) in report.now_read_only:
            failures.append(f"check.disk returned {writable} to read-only")
    expected = {(source, target): count for source, target, count in step.expect.get("deletes", [])}
    observed: dict[tuple[str, str], int] = {}
    for transfer in report.deletes:
        if transfer.volume_id == volume_id:
            observed[(transfer.source, transfer.target)] = observed.get((transfer.source, transfer.target), 0) + 1
    for pair in set(expected) | set(observed):
        if observed.get(pair, 0) != expected.get(pair, 0):
            failures.append(f"deletions {pair[0]} -> {pair[1]}: {observed.get(pair, 0)}, planned {expected.get(pair, 0)}")
    return failures


class StepFailed(RepairError):
    def __init__(self, name: str, failures: Sequence[str], results: list[dict]):
        super().__init__(f"step {name} failed: {'; '.join(failures[:5])}")
        self.results = results


def execute_steps(backend: Backend, plan: Mapping, fids: Mapping[int, str], *, approved: bool) -> list[dict]:
    """Run each planned step in its own lock/unlock session and check it before the next."""
    volume_id = plan["volume_id"]
    decision = plan["decision"]
    healthy, damaged = decision["healthy"], decision["damaged"]
    results: list[dict] = []
    for raw in decision["steps"]:
        step = Step.from_json(raw)
        started = utc_now()
        if step.name == "read-check":
            outcome = check_reads(backend, step.expect["servers"], fids)
            failures = list(outcome["failures"])
            record = {"reads": outcome}
        else:
            shell = backend.weed_shell(["lock", step.command, "unlock"], approved=approved)
            failures = evaluate_shell_step(step, shell, volume_id)
            if step.name in ("fix-read-only", "converge-deletions"):
                expected = {healthy: False, damaged: False}
            else:
                expected = {server: server == damaged for server in step.expect["copies"]}
            failures += wait_for_topology(backend, volume_id, expected)
            record = {"command": step.command, "output": shell.text.splitlines()}
        results.append({"name": step.name, "started_at": started, "finished_at": utc_now(), "failures": failures, **record})
        if failures:
            raise StepFailed(step.name, failures, results)
    return results


# --- Plan -------------------------------------------------------------------


def data_json(data: DataCheck, volume_id: int) -> dict:
    return {
        "status": data.status,
        "dat_size": data.dat_size,
        "expected_size": data.expected_size,
        "tail_key": None if data.tail_key is None else key_hex(data.tail_key),
        "trailing": [
            {"offset": n.offset, "key": key_hex(n.key), "size": n.size, "fid": file_id(volume_id, n.key, n.cookie) if volume_id else ""}
            for n in data.trailing
        ],
        "trailing_complete": data.trailing_complete,
    }


def copy_facts(view: CopyView, read_only: bool, status: Mapping[str, dict]) -> CopyFacts:
    index = IndexState.parse(view.index)
    superblock = SuperBlock.parse(view.superblock)
    data = check_data(index, view.dat_size, view.read_header, data_start=superblock.data_start, version=superblock.version)
    return CopyFacts(
        view.server,
        read_only,
        index,
        data,
        superblock,
        VolumeInfo.parse(view.vif),
        tuple(sorted(name for name in status if name.endswith(COMPACTION_EXTENSIONS))),
    )


def stable_between(before: Mapping[str, Mapping], after: Mapping[str, Mapping]) -> bool:
    """Volume files are append-only: equal sizes and equal small-file hashes mean no change."""
    for server, files in before.items():
        later = after.get(server, {})
        if set(files) != set(later):
            return False
        for name, value in files.items():
            if value["size"] != later[name]["size"]:
                return False
            if later[name]["sha256"] is not None and later[name]["sha256"] != value["sha256"]:
                return False
    return True


def sample_fids(
    views: Mapping[str, CopyView],
    states: Mapping[str, IndexState],
    sets: Mapping[str, frozenset[int]],
    volume_id: int,
    owners: Mapping[str, str],
) -> dict:
    samples: dict[str, dict] = {}
    for name, keys in sets.items():
        listed = sorted(keys)[:SAMPLE]
        server = owners.get(name)
        fids: list[str] = [key_hex(key) for key in listed]
        if server and listed and all(key in states[server].present for key in listed):
            fids = list(referenced_fids(views[server], states[server], listed, volume_id).values())
        samples[name] = {"count": len(keys), "sample": fids}
    return samples


def needle_details(view: CopyView, state: IndexState, keys: Sequence[int], volume_id: int) -> dict[int, dict]:
    """fid, size and append time of live needles, from each needle's header and v3 footer."""
    keys = sorted(keys)
    offsets: list[int] = []
    for key in keys:
        footer = append_time_offset(state.present[key])
        offsets += [state.present[key].offset, footer - footer % 8]
    raw = view.read_headers(offsets)
    details: dict[int, dict] = {}
    for index, key in enumerate(keys):
        entry = state.present[key]
        header = NeedleHeader.parse(raw[2 * index])
        if header.key != key or header.size != entry.size:
            raise RepairError(f"{view.server}: needle header at key {key:x} does not match its index entry")
        start = append_time_offset(entry) % 8
        appended = struct.unpack(">Q", raw[2 * index + 1][start : start + 8])[0]
        details[key] = {
            "fid": file_id(volume_id, key, header.cookie),
            "size": entry.size,
            "appended_at": datetime.fromtimestamp(appended / 1e9, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    return details


def in_flight_keys(first: Mapping[str, IndexState], second: Mapping[str, IndexState], fsck: FsckReport, volume_id: int) -> frozenset[int]:
    """Keys whose difference shows in only one of two index snapshots: writes or deletes landing between the reads."""
    return frozenset(n.key for n in set(differing_needles(first, fsck, volume_id)) ^ set(differing_needles(second, fsck, volume_id)))


def cmd_plan(args: argparse.Namespace, cluster: Cluster, state: State) -> int:
    volume_id = args.volume_id
    runtime = cluster.discover()
    listing = cluster.weed_shell(["volume.list"], timeout=120)
    topology = parse_volume_list(listing.stdout)
    if topology.unrecognized or listing.returncode != 0:
        raise RepairError(f"unexpected volume.list output: {(topology.unrecognized or (listing.stderr,))[:3]}")
    if volume_id in topology.ec_volume_ids:
        raise RepairError(f"volume {volume_id} is erasure coded; this tool repairs replicated volumes only")
    copies = topology.copies_of(volume_id)
    if not copies:
        raise RepairError(f"volume {volume_id} is not in the master topology")
    if len({(c.collection, c.replica_placement) for c in copies}) != 1:
        raise RepairError(f"volume {volume_id} copies disagree on collection or replica placement")
    collection, placement = copies[0].collection, copies[0].replica_placement
    if not COLLECTION.fullmatch(collection):
        raise RepairError(f"unexpected collection name {collection!r}")
    base = volume_base_name(collection, volume_id)
    servers = [copy.server for copy in copies]
    # Writable copies keep taking writes: hash only the small files, and read each index before its sizes.
    writable = not any(copy.read_only for copy in copies)
    before = {server: cluster.file_status(server, base, "small" if writable else "all") for server in servers}
    views = {server: cluster.copy_view(server, base, None if writable else before[server]) for server in servers}

    if writable:
        simulation_command = f"volume.check.disk -volumeId={volume_id} -slow -syncDeleted -v"
    else:
        simulation_command = f"volume.check.disk -volumeId={volume_id} -fixReadOnly -syncDeleted -v"
    simulation = cluster.weed_shell(["lock", simulation_command, "unlock"])
    scope = f"volume.fsck -collection {collection} -volumeId {volume_id}" if collection else f"volume.fsck -volumeId {volume_id}"
    fsck_command, missing_command = f"{scope} -v", f"{scope} -findMissingChunksInFiler -v"
    fsck_report, fsck_outputs = cluster.fsck(fsck_command)
    missing, missing_outputs = cluster.missing_chunks(missing_command) if writable else (None, {})
    after = {server: cluster.file_status(server, base, "small") for server in servers}
    stable = stable_between(before, after)

    leftovers = {
        server: sorted(cluster.file_status(server, base, "stat"))
        for server in runtime.servers
        if server not in servers
    }
    facts = [copy_facts(views[c.server], c.read_only, before[c.server]) for c in copies]
    states = {fact.server: fact.index for fact in facts}
    in_flight: frozenset[int] = frozenset()
    if writable:
        later = {server: cluster.copy_view(server, base) for server in servers}
        if any(SuperBlock.parse(later[f.server].superblock).compaction_revision != f.superblock.compaction_revision for f in facts):
            raise RepairError(f"volume {volume_id} was compacted while planning; plan again")
        in_flight = in_flight_keys(states, {s: IndexState.parse(v.index) for s, v in later.items()}, fsck_report, volume_id)
        # A write in flight leaves its .dat bytes ahead of the index; trust a later read that ends cleanly.
        facts = [
            fact if fact.data.consistent else replace(fact, data=copy_facts(later[fact.server], False, after[fact.server]).data)
            for fact in facts
        ]
    simulation_report = parse_check_disk(simulation.text)
    decision = decide(
        volume_id=volume_id,
        replica_placement=placement,
        copies=facts,
        nodes=topology.nodes,
        simulation=simulation_report,
        fsck=fsck_report,
        stable=stable,
        leftovers=leftovers,
        in_flight=in_flight,
        missing=missing,
    )
    settled = [n for n in differing_needles(states, fsck_report, volume_id) if n.key not in in_flight] if writable else []
    details: dict[tuple[str, int], dict] = {}
    for holder in {needle.holder for needle in settled}:
        keys = [needle.key for needle in settled if needle.holder == holder]
        details.update({(holder, key): value for key, value in needle_details(views[holder], states[holder], keys, volume_id).items()})
    referenced = {server: len(states[server].live - fsck_report.orphans_on(server, volume_id)) for server in servers}
    differences = {
        f"{source} -> {target}": {
            "partially_deleted": len(diff.partially_deleted),
            "absent": len(diff.absent),
        }
        for source, target in itertools.permutations(servers, 2)
        for diff in [check_disk_diff(states[source], states[target])]
    }
    owners = {
        "absent_on_damaged": decision.healthy or "",
        "healthy_missed_deletions": decision.healthy or "",
        "unique_on_damaged": decision.damaged or "",
    }
    samples = sample_fids(views, states, {k: v for k, v in decision.sets.items() if k in owners}, volume_id, owners)
    document = {
        "schema": PLAN_SCHEMA,
        "volume_id": volume_id,
        "collection": collection,
        "replica_placement": placement,
        "base": base,
        "observed_at": utc_now(),
        "runtime": runtime.to_json(),
        "topology": {
            "copies": [
                {"server": c.server, "read_only": c.read_only, "size": c.size, "file_count": c.file_count, "delete_count": c.delete_count}
                for c in copies
            ],
            "nodes": {n.server: {"free": n.free, "volumes": n.volumes, "max": n.max_volumes, "rack": n.rack} for n in topology.nodes.values()},
            "leftovers": leftovers,
        },
        "snapshot": {"files": before, "digest": canonical_digest(before), "stable": stable},
        "copies": {
            fact.server: {
                "read_only": fact.read_only,
                "data": data_json(fact.data, volume_id),
                "superblock": {"version": fact.superblock.version, "compaction_revision": fact.superblock.compaction_revision},
                "info": {"read_only": fact.info.read_only, "bytes_offset": fact.info.bytes_offset},
                "index": {
                    "entries": len(fact.index.entries),
                    "present": len(fact.index.present),
                    "live": len(fact.index.live),
                    "tombstoned": len(fact.index.tombstoned),
                    "zero_offset_entries": fact.index.zero_offset_entries,
                },
                "log_evidence": [redact(line) for line in cluster.volume_logs(fact.server, base)] if fact.read_only else [],
            }
            for fact in facts
        },
        "simulation": {
            "command": simulation_command,
            "problems": simulation_report.problems(),
            "cross_check": (
                check_disk_shortfall(simulation_report, settled, volume_id) if writable else cross_check(simulation_report, states, volume_id)
            ),
        },
        "fsck": {
            "command": fsck_command,
            "filers": list(runtime.filers),
            "problems": fsck_report.problems(),
            "orphans": {server: len(fsck_report.orphans_on(server, volume_id)) for server in servers},
            "referenced": referenced,
            "missing_command": missing_command if writable else None,
            "missing": {server: sorted(missing.missing_on(server, volume_id)) for server in servers} if missing else {},
        },
        "differences": differences,
        "divergence": {
            "needles": [
                {
                    "key": key_hex(n.key),
                    **details[(n.holder, n.key)],
                    "holder": n.holder,
                    "lacking": n.lacking,
                    "deleted": n.deleted,
                    "referenced": n.referenced,
                }
                for n in settled
            ],
            "in_flight": [key_hex(key) for key in sorted(in_flight)],
        },
        "decision": {
            "action": decision.action,
            "summary": decision.summary,
            "reasons": list(decision.reasons),
            "healthy": decision.healthy,
            "damaged": decision.damaged,
            "target": decision.target,
            "steps": [step.to_json() for step in decision.steps],
            "final_copies": list(decision.final_copies),
            "referenced": [key_hex(key) for key in sorted(decision.referenced)],
            "accepted": {server: [key_hex(key) for key in sorted(keys)] for server, keys in sorted(decision.accepted.items())},
            "sets": samples,
        },
    }
    state.write_text("plan-simulation.txt", simulation.text)
    for filer, text in fsck_outputs.items():
        state.write_text(f"plan-fsck-{filer.split('.')[0]}.txt", text)
    for filer, text in missing_outputs.items():
        state.write_text(f"plan-fsck-missing-{filer.split('.')[0]}.txt", text)
    path = state.write_json("plan.json", document)
    print_plan(document, path)
    return 1 if decision.action == "stop" else 0


def describe_step(step: Mapping) -> str:
    if step["command"]:
        return f"lock; {step['command']}; unlock"
    return "read every referenced needle from " + " and ".join(step["expect"]["servers"])


def print_plan(document: Mapping, path: Path) -> None:
    decision = document["decision"]
    collection = document["collection"] or "default collection"
    print(f"SeaweedFS volume {document['volume_id']} ({collection}, placement {document['replica_placement']}), {document['observed_at']}")
    for server, copy in document["copies"].items():
        pod = document["runtime"]["servers"][server]
        data = copy["data"]
        flag = "READ-ONLY" if copy["read_only"] else "writable"
        print(f"  {pod['pod']} on {pod['node']}: {flag}, {data['status']} (.dat {data['dat_size']} bytes, index expects {data['expected_size']})")
        for needle in data["trailing"]:
            print(f"    unindexed needle {needle['fid']}: {needle['size']} bytes at {needle['offset']}")
        for line in copy["log_evidence"][:2]:
            print(f"    log: {line[:160]}")
    simulation = document["simulation"]
    agreement = "matches the indexes" if not simulation["cross_check"] else "; ".join(simulation["cross_check"])
    print(f"  check.disk simulation: {agreement}{' | ' + '; '.join(simulation['problems']) if simulation['problems'] else ''}")
    pods = {server: value["pod"] for server, value in document["runtime"]["servers"].items()}
    fsck = document["fsck"]
    per_copy = ", ".join(f"{pods[s]} {fsck['referenced'][s]} referenced/{fsck['orphans'][s]} orphaned" for s in fsck["referenced"])
    print(f"  volume.fsck ({len(fsck['filers'])} filer stores): {per_copy}{' | ' + '; '.join(fsck['problems']) if fsck['problems'] else ''}")
    for server, paths in fsck["missing"].items():
        if paths:
            print(f"    {pods[server]} cannot serve {len(paths)} referenced chunk(s), e.g. {paths[0]}")
    divergence = document["divergence"]
    if divergence["needles"] or divergence["in_flight"]:
        for needle in divergence["needles"][:SAMPLE]:
            gap = "deleted it" if needle["deleted"] else "lacks it"
            role = "REFERENCED" if needle["referenced"] else "unreferenced"
            print(
                f"    {pods[needle['holder']]} holds {needle['fid']} ({needle['size']} bytes, appended {needle['appended_at']}); "
                f"{pods[needle['lacking']]} {gap}: {role}"
            )
        if divergence["in_flight"]:
            print(f"    {len(divergence['in_flight'])} needle(s) differed in one snapshot only (writes in flight)")
    else:
        for pair, counts in document["differences"].items():
            if any(counts.values()):
                source, target = (pods.get(part, part) for part in pair.split(" -> "))
                print(f"  {target} missed {counts['partially_deleted']} deletion(s) and lacks {counts['absent']} needle(s) present on {source}")
    for name, value in decision["sets"].items():
        if value["count"]:
            print(f"    {name}: {value['count']} {value['sample'][:5]}")
    if not document["snapshot"]["stable"]:
        print("  files changed during the plan: fence the collection's writers before preserve and apply")
    print(f"Action: {decision['action']}: {decision['summary']}")
    for reason in decision["reasons"]:
        print(f"  - {reason}")
    for number, step in enumerate(decision["steps"], 1):
        print(f"  {number}. {describe_step(step)}")
    if decision["action"] in ("check-disk", "copy"):
        print(f"Next: preserve {document['volume_id']}, rehearse {document['volume_id']}, then apply {document['volume_id']}.")
    elif decision["accepted"]:
        print(f"Next: verify {document['volume_id']} reads every referenced needle from each copy.")
    print(f"Evidence: {path}")


# --- Preserve --------------------------------------------------------------


def cmd_preserve(args: argparse.Namespace, cluster: Cluster, state: State) -> int:
    plan = state.read_plan()
    runtime = Runtime.from_json(plan["runtime"])
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot = state.dir / "snapshots" / stamp
    files: dict[str, dict] = {}
    mismatches: list[str] = []
    for server, expected_files in sorted(plan["snapshot"]["files"].items()):
        pod = runtime.servers[server].pod
        files[server] = {}
        for name, expected in sorted(expected_files.items()):
            size, digest = cluster.stream_file(server, name, snapshot / pod / name)
            files[server][name] = {"size": size, "sha256": digest}
            if (size, digest) != (expected["size"], expected["sha256"]):
                mismatches.append(f"{pod}/{name}: {size} bytes {digest[:12]}, planned {expected['size']} bytes {str(expected['sha256'])[:12]}")
    sums = "".join(
        f"{value['sha256']}  {runtime.servers[server].pod}/{name}\n"
        for server, named in sorted(files.items())
        for name, value in sorted(named.items())
    )
    (snapshot / "SHA256SUMS").write_text(sums)
    document = {
        "plan_digest": state.digest("plan.json"),
        "snapshot": stamp,
        "files": files,
        "digest": canonical_digest(files),
        "matches_plan": not mismatches,
        "mismatches": mismatches,
        "created_at": utc_now(),
    }
    state.write_json("preserve.json", document)
    print(f"Preserved {sum(len(v) for v in files.values())} files to {snapshot}")
    if mismatches:
        print("The live files changed since the plan; fence the collection's writers and run plan again:")
        for line in mismatches:
            print(f"  {line}")
        return 1
    print(f"Hashes match plan.json. Next: rehearse {args.volume_id}.")
    return 0


# --- Rehearse --------------------------------------------------------------


def load_snapshot(state: State, plan: Mapping, preserve: Mapping) -> Path:
    if not preserve.get("matches_plan") or preserve.get("plan_digest") != state.digest("plan.json"):
        raise RepairError("the preserved snapshot does not belong to the current plan; run preserve again")
    if preserve.get("digest") != plan["snapshot"]["digest"]:
        raise RepairError("preserved file hashes differ from plan.json")
    snapshot = state.dir / "snapshots" / preserve["snapshot"]
    runtime = Runtime.from_json(plan["runtime"])
    for server, named in plan["snapshot"]["files"].items():
        for name, expected in named.items():
            path = snapshot / runtime.servers[server].pod / name
            if not path.is_file() or sha256_file(path) != expected["sha256"]:
                raise RepairError(f"{path} is missing or does not match its planned hash")
    return snapshot


def require_repair_plan(plan: Mapping) -> None:
    decision = plan["decision"]
    if decision["action"] not in ("check-disk", "copy"):
        raise RepairError(f"plan action is {decision['action']}: nothing to rehearse or apply")
    problems = validate_steps(decision, plan["volume_id"])
    if problems:
        raise RepairError("plan steps are not the planned commands: " + "; ".join(problems))


def snapshot_fids(plan: Mapping, snapshot: Path) -> dict[int, str]:
    runtime = Runtime.from_json(plan["runtime"])
    healthy = plan["decision"]["healthy"]
    view = local_view(healthy, snapshot / runtime.servers[healthy].pod, plan["base"])
    keys = [int(key, 16) for key in plan["decision"]["referenced"]]
    return referenced_fids(view, IndexState.parse(view.index), keys, plan["volume_id"])


def cmd_rehearse(args: argparse.Namespace, state: State, log: CommandLog, docker_factory=DockerCluster) -> int:
    plan = state.read_plan()
    require_repair_plan(plan)
    snapshot = load_snapshot(state, plan, state.read_json("preserve.json"))
    runtime = Runtime.from_json(plan["runtime"])
    volume_id, base, decision = plan["volume_id"], plan["base"], plan["decision"]
    work = state.dir / "rehearsal-work"
    docker = docker_factory(runtime, work, f"v{volume_id}", log)
    if not docker.image_present():
        raise RepairError(f"image {runtime.image} is not local; pull it explicitly first: docker pull {runtime.image}")
    fids = snapshot_fids(plan, snapshot)
    document: dict = {
        "plan_digest": state.digest("plan.json"),
        "snapshot_digest": plan["snapshot"]["digest"],
        "image": runtime.image,
        "started_at": utc_now(),
        "pass": False,
    }
    shutil.rmtree(work, ignore_errors=True)
    for server, pod in runtime.servers.items():
        (work / pod.pod).mkdir(parents=True)
        for name in plan["snapshot"]["files"].get(server, {}):
            shutil.copyfile(snapshot / pod.pod / name, work / pod.pod / name)
    failures: list[str] = []
    try:
        docker.start()
        planned = {copy["server"]: copy["read_only"] for copy in plan["topology"]["copies"]}
        failures += wait_for_topology(docker, volume_id, planned)
        evidence = [line for line in docker.logs(decision["damaged"]) if f"/{base}." in line and INTEGRITY_FAILURE.search(line)]
        document["reproduced"] = {"topology": not failures, "integrity_log": evidence[:SAMPLE]}
        if failures or not evidence:
            failures.append("the snapshot did not reproduce the read-only copy")
            raise RepairError(failures[-1])
        baseline_reads = docker.read_needles([(decision["healthy"], fid) for fid in fids.values()])
        baseline = {fid: digest for (_, fid), digest in baseline_reads.items() if digest}
        if len(baseline) != len(fids):
            failures.append(f"{len(fids) - len(baseline)} referenced needle(s) unreadable before the repair")
            raise RepairError(failures[-1])
        document["steps"] = execute_steps(docker, plan, fids, approved=True)
        final = {server: False for server in decision["final_copies"]}

        def integrity_lines() -> dict[str, int]:
            return {server: sum(1 for line in docker.logs(server) if INTEGRITY_FAILURE.search(line)) for server in final}

        before_restart = integrity_lines()
        docker.restart_volumes()
        failures += wait_for_topology(docker, volume_id, final)
        checks = final_checks(docker, plan, fids, final, baseline=baseline)
        after_restart = integrity_lines()
        checks["integrity_failures_after_restart"] = {s: after_restart[s] - before_restart[s] for s in final}
        if any(checks["integrity_failures_after_restart"].values()):
            failures.append("a copy failed the startup integrity check after restart")
        failures += checks["failures"]
        document["checks"] = checks
    except StepFailed as error:
        document["steps"] = error.results
        failures.append(str(error))
    except RepairError as error:
        if str(error) not in failures:
            failures.append(str(error))
    finally:
        docker.cleanup()
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)
    document.update({"pass": not failures, "failures": failures, "finished_at": utc_now()})
    path = state.write_json("rehearsal.json", document)
    print(f"Rehearsal {'PASS' if not failures else 'FAIL'} for volume {volume_id} ({decision['action']}): {path}")
    for failure in failures:
        print(f"  - {failure}")
    if not failures:
        print(f"Next: apply {volume_id} (preview), then ANTON_DESTRUCTIVE_OK=1 ... apply {volume_id} after approval.")
    return 0 if not failures else 1


def accepted_divergence(decision: Mapping) -> dict[str, frozenset[int]]:
    """Needles each copy may keep lacking: unreferenced ones the plan accepted."""
    return {server: frozenset(int(key, 16) for key in keys) for server, keys in decision.get("accepted", {}).items()}


def final_checks(
    backend: Backend,
    plan: Mapping,
    fids: Mapping[int, str],
    final: Mapping[str, bool],
    *,
    baseline: Mapping[str, str] | None = None,
) -> dict:
    decision = plan["decision"]
    servers = sorted(final)
    accepted = accepted_divergence(decision)
    copies, referenced, disk = settled_checks(backend, plan["volume_id"], servers, plan["base"], accepted, lambda _: frozenset(fids))
    reads = check_reads(backend, servers, fids, baseline)
    failures = copies.failures() + disk["failures"] + reads["failures"]
    if reads["failed"] > len(reads["failures"]):
        failures.append(f"{reads['failed']} needle read failures in total")
    return {"tails": dict(copies.tails), "check_disk": disk, "reads": reads, "failures": failures}


# --- Apply -----------------------------------------------------------------


def apply_preconditions(cluster: Cluster, state: State, plan: Mapping) -> list[str]:
    problems: list[str] = []
    rehearsal = state.read_json("rehearsal.json")
    if rehearsal.get("pass") is not True:
        problems.append("the last rehearsal did not pass")
    if rehearsal.get("plan_digest") != state.digest("plan.json"):
        problems.append("the rehearsal ran against a different plan.json")
    if rehearsal.get("snapshot_digest") != plan["snapshot"]["digest"]:
        problems.append("the rehearsal used different file hashes")
    runtime = cluster.discover()
    if runtime.image != plan["runtime"]["image"] or rehearsal.get("image") != runtime.image:
        problems.append(f"image {runtime.image} differs from the planned and rehearsed image")
    listing = cluster.weed_shell(["volume.list"], timeout=120)
    topology = parse_volume_list(listing.stdout)
    planned = {copy["server"]: copy["read_only"] for copy in plan["topology"]["copies"]}
    live = {copy.server: copy.read_only for copy in topology.copies_of(plan["volume_id"])}
    if live != planned:
        problems.append(f"copies are now {live}, planned {planned}")
    target = plan["decision"]["target"]
    if target:
        node = topology.nodes.get(target)
        if node is None or node.free < 1:
            problems.append(f"{target} has no free volume slot")
        if cluster.file_status(target, plan["base"], "stat"):
            problems.append(f"{target} already holds files for {plan['base']}")
    for server, named in plan["snapshot"]["files"].items():
        live_files = cluster.file_status(server, plan["base"], "all")
        if live_files != named:
            changed = sorted(set(live_files) ^ set(named) | {n for n in named if live_files.get(n) != named[n]})
            problems.append(f"{server}: {', '.join(changed)} changed since plan; fence writers, then plan, preserve and rehearse again")
    return problems


def cmd_apply(args: argparse.Namespace, cluster: Cluster, state: State) -> int:
    plan = state.read_plan()
    require_repair_plan(plan)
    preserve = state.read_json("preserve.json")
    snapshot = load_snapshot(state, plan, preserve)
    problems = apply_preconditions(cluster, state, plan)
    decision = plan["decision"]
    print(f"Planned repair of volume {plan['volume_id']} ({decision['action']}): {decision['summary']}")
    for number, step in enumerate(decision["steps"], 1):
        print(f"  {number}. {describe_step(step)}")
    if problems:
        print("Refusing to apply:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if os.environ.get(APPROVAL) != "1":
        print(f"Preview only. After operator approval, rerun with {APPROVAL}=1 to perform exactly these steps.")
        return 3
    fids = snapshot_fids(plan, snapshot)
    document: dict = {"plan_digest": state.digest("plan.json"), "started_at": utc_now()}
    try:
        document["steps"] = execute_steps(cluster, plan, fids, approved=True)
        document["result"] = "applied"
    except StepFailed as error:
        document.update({"steps": error.results, "result": "stopped", "error": str(error)})
    document["finished_at"] = utc_now()
    path = state.write_json("apply.json", document)
    if document["result"] != "applied":
        print(f"Stopped: {document['error']}\nDo not retry blindly; the preserved snapshot is {snapshot}. Evidence: {path}")
        return 1
    print(f"Applied. Evidence: {path}\nNext: verify {plan['volume_id']}.")
    return 0


# --- Verify ----------------------------------------------------------------


def cmd_verify(args: argparse.Namespace, cluster: Cluster, state: State) -> int:
    volume_id = args.volume_id
    plan = state.read_plan() if state.path("plan.json").exists() else None
    runtime = cluster.discover()
    topology = parse_volume_list(cluster.weed_shell(["volume.list"], timeout=120).stdout)
    copies = topology.copies_of(volume_id)
    if not copies:
        raise RepairError(f"volume {volume_id} is not in the master topology")
    collection, placement = copies[0].collection, copies[0].replica_placement
    base = volume_base_name(collection, volume_id)
    servers = sorted(copy.server for copy in copies)
    failures: list[str] = []
    if len(copies) != copy_count(placement):
        failures.append(f"{len(copies)} copies, placement {placement} needs {copy_count(placement)}")
    if any(copy.read_only for copy in copies):
        failures.append(f"read-only copies: {sorted(c.server for c in copies if c.read_only)}")
    expected_servers = plan["decision"].get("final_copies") if plan and plan["decision"]["action"] in ("check-disk", "copy") else None
    if expected_servers and servers != sorted(expected_servers):
        failures.append(f"copies on {servers}, the plan expected {sorted(expected_servers)}")

    pods = {runtime.servers[server].pod for server in servers}
    gauge: list[dict] = []
    deadline = time.monotonic() + args.settle_seconds
    while True:
        gauge = [g for g in cluster.read_only_gauge() if g["pod"] in pods and g["collection"] == collection]
        if gauge and all(g["value"] == 0 for g in gauge) or time.monotonic() >= deadline:
            break
        time.sleep(10)
    if {g["pod"] for g in gauge} != pods or any(g["value"] for g in gauge):
        failures.append(f"read-only gauge for {collection or 'default'} on {sorted(pods)}: {gauge}")

    fsck_command = f"volume.fsck -collection {collection} -volumeId {volume_id} -v" if collection else f"volume.fsck -volumeId {volume_id} -v"
    fsck, _ = cluster.fsck(fsck_command)
    failures += fsck.problems()
    for server in servers:
        if (server, volume_id) not in fsck.collected:
            failures.append(f"volume.fsck did not collect {server}")
    accepted = accepted_divergence(plan["decision"]) if plan and plan["decision"]["action"] in ("none", "check-disk") else {}

    def referenced_for(states: Mapping[str, IndexState]) -> frozenset[int]:
        return frozenset().union(*(states[s].live - fsck.orphans_on(s, volume_id) for s in servers))

    copies_checked, referenced, disk = settled_checks(cluster, volume_id, servers, base, accepted, referenced_for)
    states = copies_checked.states
    failures += copies_checked.failures() + disk["failures"]
    for server in servers:
        missing = referenced - states[server].live
        if missing:
            failures.append(f"{server} lacks {len(missing)} referenced needle(s)")
    owner = {key: server for server in reversed(servers) for key in states[server].live}
    fids: dict[int, str] = {}
    for server in servers:
        keys = [key for key in referenced if owner.get(key) == server]
        fids.update(referenced_fids(copies_checked.views[server], states[server], keys, volume_id))
    reads = check_reads(cluster, servers, fids)
    failures += reads["failures"]
    if reads["failed"] > len(reads["failures"]):
        failures.append(f"{reads['failed']} needle read failures in total")
    document = {
        "volume_id": volume_id,
        "observed_at": utc_now(),
        "copies": servers,
        "gauge": gauge,
        "tails": dict(copies_checked.tails),
        "check_disk": disk,
        "fsck": {"command": fsck_command, "filers": list(runtime.filers), "referenced": len(referenced)},
        "accepted": {server: len(keys) for server, keys in sorted(accepted.items())},
        "reads": reads,
        "failures": failures,
        "pass": not failures,
    }
    path = state.write_json("verify.json", document)
    verdict = "PASS" if not failures else "FAIL"
    print(f"Verify {verdict} for volume {volume_id}: {len(servers)} copies, {len(referenced)} referenced needle(s) read from each.")
    if accepted:
        print(f"Accepted divergence from the plan: {sum(len(keys) for keys in accepted.values())} unreferenced needle(s).")
    print(f"Evidence: {path}")
    for failure in failures:
        print(f"  - {failure}")
    return 0 if not failures else 1


# --- Entry point -------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", type=Path, default=REPO, help="canonical Anton checkout (kubeconfig and .private/)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "preserve", "rehearse", "apply", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("volume_id", type=int)
        if name == "rehearse":
            sub.add_argument("--keep-work", action="store_true", help="keep the rehearsal data directories")
        if name == "verify":
            sub.add_argument("--settle-seconds", type=float, default=90.0, help="wait this long for the gauge to clear")
    args = parser.parse_args(argv)
    if args.volume_id <= 0:
        parser.error("volume_id must be positive")
    return args


COMMANDS = {"plan": cmd_plan, "preserve": cmd_preserve, "apply": cmd_apply, "verify": cmd_verify}


def main(argv: Sequence[str] | None = None, *, cluster_factory=production_cluster, docker_factory=DockerCluster) -> int:
    args = parse_args(argv)
    root = args.repo_root.resolve()
    state = State(root, args.volume_id)
    log = CommandLog(state.path("commands.log"))
    try:
        if args.command == "rehearse":
            return cmd_rehearse(args, state, log, docker_factory)
        return COMMANDS[args.command](args, cluster_factory(root, log), state)
    except TargetPreflightError as error:
        print(f"blocked by target preflight: {redact(str(error))}", file=sys.stderr)
    except RepairError as error:
        print(f"stopped: {redact(str(error))}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
