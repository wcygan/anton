"""SeaweedFS read-only copy repair: volume model, weed shell parsers, and CLI flows.

Volumes are synthetic .dat/.idx bytes written the way a 4.48 volume server
writes them; weed shell output comes from fixtures. Nothing reaches a cluster
or Docker.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import seaweedfs_repair as model  # noqa: E402

SCRIPT = ROOT / "scripts" / "seaweedfs-readonly-repair.py"
SPEC = importlib.util.spec_from_file_location("seaweedfs_readonly_repair", SCRIPT)
CLI = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(CLI)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "seaweedfs-repair"
SERVERS = [f"seaweedfs-volume-{i}.seaweedfs-volume-peer.storage:8444" for i in range(3)]
DAMAGED, HEALTHY, TARGET = SERVERS
POD_SERVERS = {f"seaweedfs-volume-{i}": server for i, server in enumerate(SERVERS)}
IMAGE = "docker.io/chrislusf/seaweedfs@sha256:" + "a" * 64
BASE = "loki_31"
VIF = json.dumps({"version": 3, "replication": "001", "bytesOffset": 4, "readOnly": False}).encode()
INTEGRITY_LOG = (
    "I1023 15:35:15.625116 volume_loading.go:294 volumeDataIntegrityChecking failed "
    "CheckVolumeDataIntegrity /data0/loki_31.idx failed: data file /data0/loki_31.dat actual 488 bytes expected 400 bytes"
)
VOLUME_COMMAND = (
    "weed -logtostderr=true volume -port=8444 -max=24 -ip=$(POD_NAME).seaweedfs-volume-peer.storage -ip.bind=0.0.0.0 "
    "-mserver=seaweedfs-master-0.seaweedfs-master-peer.storage:9333 -dir=/data0 -metricsPort=9327"
)
MASTER_COMMAND = (
    "weed -logtostderr=true master -volumeSizeLimitMB=5000 -defaultReplication=001 "
    "-ip=$(POD_NAME).seaweedfs-master-peer.storage -ip.bind=0.0.0.0 -telemetry=false"
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def cookie(key: int) -> int:
    return 0x10000 + key


def needle(key: int, size: int) -> bytes:
    record = struct.pack(">IQi", cookie(key), key, size) + bytes([key % 251 + 1]) * size + b"\0" * 4 + struct.pack(">Q", key)
    return record + b"\0" * (8 - len(record) % 8)


class Volume:
    """An append-only .dat/.idx pair, written the way a 4.48 volume server writes it."""

    def __init__(self) -> None:
        self.dat = bytearray(bytes([3, 1, 0, 0, 0, 0, 0, 0]))
        self.idx = bytearray()

    def copy(self) -> Volume:
        clone = Volume()
        clone.dat, clone.idx = bytearray(self.dat), bytearray(self.idx)
        return clone

    def put(self, key: int, size: int = 40, *, indexed: bool = True) -> Volume:
        offset = len(self.dat)
        self.dat += needle(key, size)
        self.idx += struct.pack(">QIi", key, offset // 8, size) if indexed else bytes(16)
        return self

    def delete(self, key: int) -> Volume:
        offset = len(self.dat)
        self.dat += needle(key, 0)
        self.idx += struct.pack(">QIi", key, offset // 8, -1)
        return self

    def files(self) -> dict[str, bytes]:
        return {f"{BASE}.dat": bytes(self.dat), f"{BASE}.idx": bytes(self.idx), f"{BASE}.sdx": b"", f"{BASE}.vif": VIF}


def scenario(*, trailing_referenced: bool) -> tuple[Volume, Volume]:
    """Volume 31: copy 0 died mid-append (zero index entry for key 7) and refused later deletes.

    Copy 0 alone deleted key 5 before the kill; copy 1 then deleted keys 2 and 3.
    fsck.txt marks key 5 unreferenced on copy 1 and keys 2 and 3 on copy 0.
    """
    common = Volume().put(1).put(2).put(3).put(4).put(5)
    damaged = common.copy().delete(5).put(7, indexed=False)
    healthy = common.copy().put(7)
    if not trailing_referenced:
        healthy.delete(7)
    return healthy.delete(2).delete(3), damaged


def index_state(volume: Volume) -> model.IndexState:
    return model.IndexState.parse(bytes(volume.idx))


def facts(volume: Volume, server: str, read_only: bool) -> model.CopyFacts:
    files = volume.files()
    view = CLI.CopyView(
        server, files[f"{BASE}.idx"], len(volume.dat), bytes(volume.dat[:8]), VIF,
        lambda offsets: [bytes(volume.dat[o : o + 16]) for o in offsets],
    )
    return CLI.copy_facts(view, read_only, {name: {} for name in files})


def nodes(free: tuple[int, int, int] = (1, 0, 1)) -> dict[str, model.DataNode]:
    return {s: model.DataNode(s, "DefaultDataCenter", "DefaultRack", 24 - f, 24, f) for s, f in zip(SERVERS, free)}


def render_volume_list(copies: dict[str, bool], free: tuple[int, int, int]) -> str:
    lines = [
        "Topology volumeSizeLimit:5000 MB hdd(volume:70/72 active:69 free:2 remote:0)",
        "  DataCenter DefaultDataCenter hdd(volume:70/72 active:69 free:2 remote:0)",
        "    Rack DefaultRack hdd(volume:70/72 active:69 free:2 remote:0)",
    ]
    for server, slots in zip(SERVERS, free):
        usage = f"volume:{24 - slots}/24 active:{24 - slots} free:{slots} remote:0"
        lines += [f"      DataNode {server} hdd({usage})", f"        Disk hdd({usage}) id:0"]
        lines.append(
            "          volume Id:9, Size:8, ReplicaPlacement:001, Collection:, Version:3, Ttl:, FileCount:0, "
            "DeleteCount:0, DeletedByteCount:0, ReadOnly:false, ModifiedAtSecond:1792780926 "
        )
        if server in copies:
            lines.append(
                "          volume Id:31, Size:488, ReplicaPlacement:001, Collection:loki, Version:3, Ttl:, FileCount:6, "
                f"DeleteCount:1, DeletedByteCount:56, ReadOnly:{str(copies[server]).lower()}, ModifiedAtSecond:1792647280 "
            )
        lines += ["        Disk hdd {Size:8 FileCount:0 DeletedFileCount:0 DeletedBytes:0} ", f"      DataNode {server} {{Size:8}} "]
    lines += ["    Rack DefaultRack {Size:8} ", "  DataCenter DefaultDataCenter {Size:8} ", "total size:8 file_count:0 deleted_file:0 deleted_bytes:0"]
    return "\n".join(lines) + "\n"


class MemoryStore:
    def __init__(self, files: dict[str, dict[str, bytes]]):
        self.files = {server: dict(named) for server, named in files.items()}

    def names(self, server: str) -> list[str]:
        return sorted(self.files.get(server, {}))

    def get(self, server: str, name: str) -> bytes:
        return self.files[server][name]

    def put(self, server: str, name: str, data: bytes) -> None:
        self.files.setdefault(server, {})[name] = data

    def drop(self, server: str) -> None:
        self.files[server] = {}


class DirStore:
    """The rehearsal's per-server data directories."""

    def __init__(self, directories: dict[str, Path]):
        self.directories = directories

    def names(self, server: str) -> list[str]:
        return sorted(path.name for path in self.directories[server].iterdir())

    def get(self, server: str, name: str) -> bytes:
        return (self.directories[server] / name).read_bytes()

    def put(self, server: str, name: str, data: bytes) -> None:
        (self.directories[server] / name).write_bytes(data)

    def drop(self, server: str) -> None:
        for path in self.directories[server].iterdir():
            path.unlink()


def read_needle(store, server: str, fid: str) -> str | None:
    if f"{BASE}.idx" not in store.names(server):
        return None
    hexadecimal = fid.split(",", 1)[1].split("?", 1)[0]
    key, expected_cookie = int(hexadecimal[:-8], 16), int(hexadecimal[-8:], 16)
    entry = model.IndexState.parse(store.get(server, f"{BASE}.idx")).present.get(key)
    if entry is None or entry.size <= 0:
        return None
    dat = store.get(server, f"{BASE}.dat")
    if model.NeedleHeader.parse(dat[entry.offset : entry.offset + 16]).cookie != expected_cookie:
        return None
    return hashlib.sha256(dat[entry.offset + 16 : entry.offset + 16 + entry.size]).hexdigest()


def read_output(store, payload: bytes) -> bytes:
    lines = []
    for line in payload.decode().splitlines():
        server, fid = line.split()
        digest = read_needle(store, server, fid)
        lines.append(f"OK {server} {fid} {digest}" if digest else f"FAIL {server} {fid}")
    return ("\n".join(lines) + "\n").encode()


class SeaweedShell:
    """Answer weed shell sessions from fixtures and apply the effects SeaweedFS would."""

    def __init__(self, store, copies: dict[str, bool], *, simulation: str, slow: str, fsck: str = "fsck.txt", free=(1, 0, 1)):
        self.store = store
        self.copies = dict(copies)
        self.simulation, self.slow, self.fsck, self.free = simulation, slow, fsck, free
        self.sessions: list[list[str]] = []

    def tombstone(self, server: str, key: int) -> None:
        dat, idx = self.store.get(server, f"{BASE}.dat"), self.store.get(server, f"{BASE}.idx")
        self.store.put(server, f"{BASE}.dat", dat + needle(key, 0))
        self.store.put(server, f"{BASE}.idx", idx + struct.pack(">QIi", key, len(dat) // 8, -1))

    def __call__(self, commands: list[str]) -> tuple[int, str, str]:
        self.sessions.append(list(commands))
        output: list[str] = []
        for command in commands:
            if command in ("lock", "unlock"):
                continue
            if command == "volume.list":
                output.append(render_volume_list(self.copies, self.free))
            elif command.startswith("volume.fsck"):
                output.append(fixture(self.fsck))
            elif command.startswith("volume.check.disk") and "-apply" not in command:
                output.append(fixture(self.slow if "-slow" in command else self.simulation))
            elif "-fixReadOnly" in command:
                self.tombstone(DAMAGED, 3)
                self.tombstone(DAMAGED, 2)
                self.copies[DAMAGED] = False
                output.append(fixture("check-disk-fix.txt"))
            elif command.startswith("volume.check.disk"):
                self.tombstone(HEALTHY, 5)
                output.append(fixture("check-disk-converge.txt"))
            elif command.startswith("volume.copy"):
                for name in self.store.names(HEALTHY):
                    self.store.put(TARGET, name, self.store.get(HEALTHY, name))
                self.copies[TARGET] = False
            elif command.startswith("volume.delete"):
                self.store.drop(DAMAGED)
                del self.copies[DAMAGED]
            else:
                return 1, "", f"unknown command: {command}\n"
        return 0, "\n".join(output), "master: localhost:9333 filers: [seaweedfs-filer-0.seaweedfs-filer-peer.storage:8888]\n"


def pod(name: str, component: str, command: str, node: str, *, ready: bool = True, image: str = IMAGE) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"nodeName": node, "containers": [{"name": component, "command": ["/bin/sh", "-ec", command]}]},
        "status": {
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "containerStatuses": [{"name": component, "imageID": image}],
        },
    }


VOLUME_PODS = {"items": [pod(f"seaweedfs-volume-{i}", "volume", VOLUME_COMMAND, f"k8s-{i + 1}") for i in range(3)]}
MASTER_PODS = {
    "items": [
        pod("seaweedfs-master-0", "master", MASTER_COMMAND, "k8s-1", ready=False),
        pod("seaweedfs-master-1", "master", MASTER_COMMAND, "k8s-2"),
    ]
}


class FakeKube:
    """Stands in for Kube: emulates kubectl get/logs/exec and the tool's busybox scripts."""

    def __init__(self, store, shell: SeaweedShell, *, gauge: dict[str, float] | None = None):
        self.store = store
        self.shell = shell
        self.gauge = gauge or {}
        self.calls: list[list[str]] = []

    def run(self, args, *, input=None, timeout=120.0, mutation=False, note=""):
        args = list(args)
        self.calls.append(args)
        stdout, stderr, code = self.dispatch(args, input)
        return subprocess.CompletedProcess(args, code, stdout, stderr)

    def checked(self, args, **kwargs) -> bytes:
        result = self.run(args, **kwargs)
        if result.returncode:
            raise model.RepairError(result.stderr.decode())
        return result.stdout

    def stream_to(self, args, destination: Path, *, timeout: float):
        args = list(args)
        self.calls.append(args)
        data = self.store.get(POD_SERVERS[args[3]], args[-1].rsplit("/", 1)[1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return len(data), hashlib.sha256(data).hexdigest()

    def dispatch(self, args: list[str], payload: bytes | None) -> tuple[bytes, bytes, int]:
        if args[2:4] == ["get", "pods"]:
            return json.dumps(VOLUME_PODS if "component=volume" in args[5] else MASTER_PODS).encode(), b"", 0
        if args[:2] == ["get", "--raw"]:
            result = [
                {"metric": {"pod": name, "collection": "loki", "type": "IsReadOnly"}, "value": [0, str(value)]}
                for name, value in self.gauge.items()
            ]
            return json.dumps({"status": "success", "data": {"result": result}}).encode(), b"", 0
        if args[2] == "logs":
            return (INTEGRITY_LOG + "\n").encode(), b"", 0
        tail = args[args.index("--") + 1 :]
        target = args[args.index("-c") - 1]
        if tail[:2] == ["weed", "shell"]:
            code, out, err = self.shell(payload.decode().splitlines())
            return out.encode(), err.encode(), code
        if tail[:3] == ["sh", "-c", CLI.READ_SCRIPT]:
            return read_output(self.store, payload), b"", 0
        server = POD_SERVERS[target]
        if tail[:3] == ["sh", "-c", CLI.FILE_STATUS_SCRIPT]:
            base, mode = tail[5], tail[6]
            lines = []
            for extension in (".dat", ".idx", ".sdx", ".vif", ".cpd", ".cpx", ".cpldb"):
                if base + extension in self.store.names(server):
                    data = self.store.get(server, base + extension)
                    hashed = mode == "all" or (mode == "small" and extension != ".dat")
                    lines.append(f"{base + extension} {len(data)} {hashlib.sha256(data).hexdigest() if hashed else '-'}\n")
            return "".join(lines).encode(), b"", 0
        if tail[:3] == ["sh", "-c", CLI.RANGES_SCRIPT]:
            data = self.store.get(server, tail[4].rsplit("/", 1)[1])
            return "".join(data[int(o) : int(o) + 16].hex() + "\n" for o in tail[5:]).encode(), b"", 0
        if tail[0] == "cat":
            name = tail[1].rsplit("/", 1)[1]
            if name not in self.store.names(server):
                return b"", b"cat: can't open", 1
            return self.store.get(server, name), b"", 0
        raise AssertionError(f"unexpected kubectl call: {args}")


class FakeDocker(CLI.DockerCluster):
    """The rehearsal cluster with docker replaced by SeaweedShell over the real data directories."""

    def __init__(self, runtime, work, tag, log, *, make_shell, read_only_reproduced: bool = True):
        super().__init__(runtime, work, tag, log)
        self.make_shell = make_shell
        self.read_only_reproduced = read_only_reproduced
        self.shell: SeaweedShell | None = None
        self.starts = 0
        self.calls: list[tuple] = []

    def docker(self, *args: str, input=None, timeout=300.0, check=True, note=""):
        self.calls.append(args)
        done = lambda stdout=b"", stderr=b"", code=0: subprocess.CompletedProcess(args, code, stdout, stderr)  # noqa: E731
        if args[0] == "run" and self.shell is None:
            store = DirStore({server: self.data_dir(server) for server in self.containers})
            copies = {DAMAGED: self.read_only_reproduced, HEALTHY: False}
            self.shell = self.make_shell(store, copies)
        if args[:2] == ("inspect", "-f"):
            self.starts += 1
            return done(str(self.starts).encode())
        if args[0] == "logs":
            return done(stderr=(INTEGRITY_LOG + "\n").encode() if args[1] == self.containers[DAMAGED] else b"")
        if args[0] == "exec":
            tail = args[args.index(self.master) + 1 :]
            if tail[:2] == ("weed", "shell"):
                code, out, err = self.shell(input.decode().splitlines())
                return done(out.encode(), err.encode(), code)
            if tail[:3] == ("sh", "-c", CLI.READ_SCRIPT):
                return done(read_output(self.shell.store, input))
        if args[0] in ("image", "ps", "rm", "network", "run", "restart"):
            return done()
        raise AssertionError(f"unexpected docker call: {args}")


class Flow:
    """One volume's evidence directory and fakes for every subcommand."""

    def __init__(self, testcase: unittest.TestCase, *, trailing_referenced: bool, free=(1, 0, 1)):
        self.temporary = tempfile.TemporaryDirectory()
        testcase.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        healthy, damaged = scenario(trailing_referenced=trailing_referenced)
        self.store = MemoryStore({DAMAGED: damaged.files(), HEALTHY: healthy.files(), TARGET: {}})
        name = "copy" if trailing_referenced else "sync"
        self.simulation, self.slow = f"check-disk-simulation-{name}.txt", f"check-disk-slow-{name}.txt"
        self.fsck_after = "fsck-after-copy.txt" if trailing_referenced else "fsck.txt"
        self.shell = SeaweedShell(self.store, {DAMAGED: True, HEALTHY: False}, simulation=self.simulation, slow=self.slow, free=free)
        self.kube = FakeKube(self.store, self.shell, gauge={})
        self.docker: FakeDocker | None = None
        self.read_only_reproduced = True

    def state(self) -> CLI.State:
        return CLI.State(self.root, 31)

    def make_shell(self, store, copies) -> SeaweedShell:
        return SeaweedShell(store, copies, simulation=self.simulation, slow=self.slow)

    def docker_factory(self, runtime, work, tag, log) -> FakeDocker:
        self.docker = FakeDocker(runtime, work, tag, log, make_shell=self.make_shell, read_only_reproduced=self.read_only_reproduced)
        return self.docker

    def run(self, *argv: str) -> tuple[int, str]:
        output = io.StringIO()
        with (
            redirect_stdout(output),
            redirect_stderr(io.StringIO()),
            patch.object(CLI, "RESTART_SETTLE", 0),
            patch.object(CLI, "TOPOLOGY_TIMEOUT", 0),
            patch.object(CLI.time, "sleep", lambda _: None),
        ):
            code = CLI.main(
                ["--repo-root", str(self.root), *argv],
                cluster_factory=lambda root, log: CLI.Cluster(self.kube),
                docker_factory=self.docker_factory,
            )
        return code, output.getvalue()

    def plan(self) -> dict:
        return json.loads(self.state().path("plan.json").read_text())


class IndexModelTests(unittest.TestCase):
    def test_needle_disk_size_matches_the_4_48_padding_rule(self) -> None:
        self.assertEqual(32, model.needle_disk_size(model.TOMBSTONE_SIZE))
        self.assertEqual(32, model.needle_disk_size(0))
        # Volume 31's unindexed needle on 2026-10-23: 1238 bytes occupied 21030544 - 21029272.
        self.assertEqual(1272, model.needle_disk_size(1238))
        self.assertEqual(40, model.needle_disk_size(4), "an already aligned record still gets 8 bytes of padding")
        self.assertEqual(len(needle(9, 41)), model.needle_disk_size(41))

    def test_index_replay_follows_check_disk_and_fsck_liveness(self) -> None:
        state = index_state(Volume().put(1).put(2).delete(2).put(3, indexed=False).put(4).delete(4).put(4))
        self.assertEqual({1, 4}, state.live)
        self.assertEqual({2}, state.tombstoned)
        self.assertNotIn(3, state.present)
        self.assertEqual(1, state.zero_offset_entries)
        with self.assertRaises(model.RepairError):
            model.parse_index(b"\0" * 17)

    def test_tail_entry_uses_the_last_entry_or_the_highest_offset(self) -> None:
        volume = Volume().put(1).put(2)
        entries = model.parse_index(bytes(volume.idx))
        self.assertEqual(2, model.dat_tail_entry(entries, len(volume.dat)).key)
        # weed fix can rewrite the index in key order; the .dat tail is still the highest offset.
        self.assertEqual(2, model.dat_tail_entry(tuple(reversed(entries)), len(volume.dat)).key)
        self.assertIsNone(model.dat_tail_entry(model.parse_index(bytes(16)), 8))

    def test_check_data_classifies_the_startup_check_outcomes(self) -> None:
        healthy, damaged = scenario(trailing_referenced=True)
        self.assertEqual("consistent", facts(healthy, HEALTHY, False).data.status)
        data = facts(damaged, DAMAGED, True).data
        self.assertEqual("unindexed-tail", data.status)
        self.assertEqual(len(damaged.dat) - model.needle_disk_size(40), data.expected_size)
        self.assertEqual([(7, cookie(7), 40)], [(n.key, n.cookie, n.size) for n in data.trailing])
        self.assertTrue(data.trailing_complete)

        torn = damaged.copy()
        torn.dat = torn.dat[:-8]
        self.assertFalse(facts(torn, DAMAGED, True).data.trailing_complete)
        short = healthy.copy()
        short.dat = short.dat[:-16]
        self.assertEqual("short-data", facts(short, HEALTHY, False).data.status)
        wrong = healthy.copy()
        wrong.dat[-32 + 4 : -32 + 12] = struct.pack(">Q", 99)
        self.assertEqual("header-mismatch", facts(wrong, HEALTHY, False).data.status)
        self.assertEqual("consistent", facts(Volume(), HEALTHY, False).data.status)

    def test_superblock_and_volume_info(self) -> None:
        superblock = model.SuperBlock.parse(bytes([3, 1, 0, 0, 0, 105, 0, 0]))
        self.assertEqual((3, "001", 105, 8), (superblock.version, superblock.replica_placement, superblock.compaction_revision, superblock.data_start))
        info = model.VolumeInfo.parse(b'{"version": 3, "replication": "001", "bytesOffset": 4, "readOnly": true}')
        self.assertTrue(info.read_only)
        with self.assertRaises(model.RepairError):
            model.VolumeInfo.parse(b"not json")

    def test_check_disk_diff_reproduces_the_simulation_counts(self) -> None:
        healthy, damaged = scenario(trailing_referenced=True)
        to_damaged = model.check_disk_diff(index_state(healthy), index_state(damaged))
        self.assertEqual((6, {2, 3}, {7}), (to_damaged.entries, set(to_damaged.partially_deleted), set(to_damaged.absent)))
        to_healthy = model.check_disk_diff(index_state(damaged), index_state(healthy))
        self.assertEqual((5, {5}, set()), (to_healthy.entries, set(to_healthy.partially_deleted), set(to_healthy.absent)))


class ParserTests(unittest.TestCase):
    def test_volume_list(self) -> None:
        topology = model.parse_volume_list(fixture("volume-list.txt"))
        self.assertEqual((), topology.unrecognized)
        self.assertEqual(5000, topology.volume_size_limit_mb)
        copies = {copy.server: copy for copy in topology.copies_of(31)}
        self.assertEqual({DAMAGED, HEALTHY}, set(copies))
        self.assertTrue(copies[DAMAGED].read_only)
        self.assertEqual(("loki", "001"), (copies[HEALTHY].collection, copies[HEALTHY].replica_placement))
        self.assertEqual("", topology.copies_of(9)[0].collection)
        self.assertEqual({DAMAGED: 1, HEALTHY: 0, TARGET: 1}, {s: n.free for s, n in topology.nodes.items()})
        with self.assertRaises(model.RepairError):
            model.parse_volume_list("nothing here\n")
        self.assertEqual(("      DataNode odd line",), model.parse_volume_list("Topology volumeSizeLimit:5000 MB\n      DataNode odd line\n").unrecognized)

    def test_check_disk_simulation_and_apply_output(self) -> None:
        copy = model.parse_check_disk(fixture("check-disk-simulation-copy.txt"))
        self.assertEqual(((31, DAMAGED),), copy.skipped_read_only)
        self.assertEqual(((31, HEALTHY, 1, DAMAGED),), copy.not_resurrecting)
        self.assertEqual(("one-sided", DAMAGED, 1), (copy.divergence[0].kind, copy.divergence[0].lagging, copy.divergence[0].missing))
        self.assertEqual([], copy.problems())

        fixed = model.parse_check_disk(fixture("check-disk-fix.txt"))
        self.assertEqual(((31, DAMAGED),), fixed.now_writable)
        self.assertEqual(((31, DAMAGED),), fixed.synced_writable)
        self.assertEqual([3, 2], [t.key for t in fixed.deletes])
        self.assertEqual({(HEALTHY, DAMAGED)}, {(t.source, t.target) for t in fixed.deletes})
        converge = model.parse_check_disk(fixture("check-disk-converge.txt"))
        self.assertEqual([(5, DAMAGED, HEALTHY)], [(t.key, t.source, t.target) for t in converge.deletes])
        self.assertEqual(((31, HEALTHY, DAMAGED),), converge.synced_pairs)

        noisy = model.parse_check_disk("error: lock is lost\nsomething new\nvolume 31 sync reached maximum iterations (5)\n")
        self.assertEqual(3, len(noisy.problems()))

    def test_fsck_orphans_per_copy(self) -> None:
        report = model.parse_fsck(fixture("fsck.txt"))
        self.assertEqual([], report.problems())
        self.assertEqual({(DAMAGED, 31), (HEALTHY, 31)}, set(report.collected))
        self.assertEqual({5}, report.orphans_on(HEALTHY, 31))
        self.assertEqual({2, 3}, report.orphans_on(DAMAGED, 31))
        self.assertEqual(frozenset(), report.orphans_on(TARGET, 31))

    def test_fsck_default_collection_warnings_and_count_mismatch(self) -> None:
        report = model.parse_fsck(
            f"dataNode:{HEALTHY}\tvolume:9\tentries:3\torphan:2\t66.67%\t20B\n"
            ":9,1a00000000\n"
            "WARNING: ResolveChunkManifest failed for /topics/x: boom — recording top-level chunk fids only; purging will be disabled\n"
            ":8,1b00000000\n"
        )
        self.assertEqual({0x1A}, report.orphans_on(HEALTHY, 9))
        self.assertEqual(1, report.unresolved_manifests)
        self.assertTrue(any("orphan without a matching summary" in p for p in report.problems()))
        self.assertTrue(any("expected 2" in p for p in report.problems()))

    def test_cross_check_flags_a_simulation_that_disagrees_with_the_indexes(self) -> None:
        healthy, damaged = scenario(trailing_referenced=False)
        states = {HEALTHY: index_state(healthy), DAMAGED: index_state(damaged)}
        self.assertEqual([], model.cross_check(model.parse_check_disk(fixture("check-disk-simulation-sync.txt")), states, 31))
        mismatches = model.cross_check(model.parse_check_disk(fixture("check-disk-simulation-copy.txt")), states, 31)
        self.assertEqual(1, len(mismatches))
        self.assertIn("(6, 2, 1)", mismatches[0])


class DecisionTests(unittest.TestCase):
    def decide(self, healthy: Volume, damaged: Volume, *, simulation="check-disk-simulation-sync.txt", fsck="fsck.txt", free=(1, 0, 1), **overrides) -> model.Decision:
        arguments = dict(
            volume_id=31,
            replica_placement="001",
            copies=[facts(damaged, DAMAGED, True), facts(healthy, HEALTHY, False)],
            nodes=nodes(free),
            simulation=model.parse_check_disk(fixture(simulation)) if isinstance(simulation, str) else simulation,
            fsck=model.parse_fsck(fixture(fsck)) if isinstance(fsck, str) else fsck,
            stable=True,
            leftovers={},
        )
        arguments.update(overrides)
        return model.decide(**arguments)

    def test_unreferenced_tail_is_repaired_in_place_and_deletions_converge(self) -> None:
        healthy, damaged = scenario(trailing_referenced=False)
        decision = self.decide(healthy, damaged, simulation="check-disk-simulation-sync.txt")
        self.assertEqual("check-disk", decision.action, decision.reasons)
        self.assertEqual(
            ["volume.check.disk -volumeId=31 -fixReadOnly -syncDeleted -apply -v", "volume.check.disk -volumeId=31 -slow -syncDeleted -apply -v"],
            [step.command for step in decision.steps],
        )
        self.assertEqual([[HEALTHY, DAMAGED, 2]], decision.steps[0].expect["deletes"])
        self.assertEqual([[DAMAGED, HEALTHY, 1], [HEALTHY, DAMAGED, 0]], decision.steps[1].expect["deletes"])
        self.assertEqual({1, 4}, decision.referenced)
        self.assertEqual((DAMAGED, HEALTHY), decision.final_copies)

    def test_referenced_tail_needs_a_whole_volume_copy(self) -> None:
        healthy, damaged = scenario(trailing_referenced=True)
        decision = self.decide(healthy, damaged, simulation="check-disk-simulation-copy.txt")
        self.assertEqual("copy", decision.action, decision.reasons)
        self.assertEqual(TARGET, decision.target)
        self.assertEqual(["copy", "read-check", "delete-damaged"], [step.name for step in decision.steps])
        self.assertEqual(f"volume.copy -source {HEALTHY} -target {TARGET} -volumeId 31", decision.steps[0].command)
        self.assertEqual(f"volume.delete -node {DAMAGED} -volumeId 31", decision.steps[2].command)
        self.assertIn("1 referenced needle(s) are missing", decision.reasons[0])
        self.assertEqual({1, 4, 7}, decision.referenced)

    def test_copy_without_a_free_slot_stops(self) -> None:
        healthy, damaged = scenario(trailing_referenced=True)
        decision = self.decide(healthy, damaged, simulation="check-disk-simulation-copy.txt", free=(1, 0, 0))
        self.assertEqual("stop", decision.action)
        self.assertIn("no third server has a free slot", decision.summary)
        leftover = self.decide(healthy, damaged, simulation="check-disk-simulation-copy.txt", leftovers={TARGET: ["loki_31.dat"]})
        self.assertEqual("stop", leftover.action)

    def test_without_missed_deletions_check_disk_cannot_make_the_copy_writable(self) -> None:
        common = Volume().put(1).put(2)
        healthy, damaged = common.copy().put(7).delete(7), common.copy().put(7, indexed=False)
        decision = self.decide(
            healthy,
            damaged,
            simulation=model.CheckDiskReport(sync=(model.SyncLine(31, HEALTHY, 3, DAMAGED, 0, 0),)),
            fsck=model.FsckReport(collected=frozenset({(DAMAGED, 31), (HEALTHY, 31)})),
        )
        self.assertEqual("copy", decision.action, decision.reasons)
        self.assertIn("no missed deletions", " ".join(decision.reasons))

    def test_a_pair_check_disk_skipped_is_not_repaired_in_place(self) -> None:
        healthy, damaged = scenario(trailing_referenced=False)
        skipped = fixture("check-disk-simulation-sync.txt").rsplit("\n", 2)[0] + "\n"
        decision = self.decide(healthy, damaged, simulation=model.parse_check_disk(skipped))
        self.assertEqual("copy", decision.action)
        self.assertIn("check.disk skipped the pair", " ".join(decision.reasons))

    def test_unsafe_or_unproven_states_stop(self) -> None:
        healthy, damaged = scenario(trailing_referenced=False)
        cases = {
            "changed": dict(stable=False),
            "mismatch": dict(simulation=model.parse_check_disk(fixture("check-disk-simulation-copy.txt"))),
            "manifests": dict(fsck=model.parse_fsck(fixture("fsck.txt") + "WARNING: ResolveChunkManifest failed for /x\n")),
            "fsck-missed-copy": dict(fsck=model.parse_fsck(fixture("fsck-after-copy.txt"))),
            "persisted": dict(copies=[
                model.CopyFacts(DAMAGED, True, index_state(damaged), facts(damaged, DAMAGED, True).data,
                                model.SuperBlock(3, "001", 0, 0), model.VolumeInfo(3, "001", 4, True)),
                facts(healthy, HEALTHY, False),
            ]),
            "both-read-only": dict(copies=[facts(damaged, DAMAGED, True), facts(healthy, HEALTHY, True)]),
            "one-copy": dict(copies=[facts(damaged, DAMAGED, True)]),
        }
        for name, override in cases.items():
            with self.subTest(name):
                self.assertEqual("stop", self.decide(healthy, damaged, **override).action)

    def test_referenced_needle_unique_to_the_damaged_copy_stops(self) -> None:
        common = Volume().put(1).put(2)
        healthy, damaged = common.copy().delete(2), common.copy().put(8).put(9, indexed=False)
        decision = model.decide(
            volume_id=31, replica_placement="001", copies=[facts(damaged, DAMAGED, True), facts(healthy, HEALTHY, False)],
            nodes=nodes(), simulation=model.CheckDiskReport(), stable=True, leftovers={},
            fsck=model.FsckReport(collected=frozenset({(DAMAGED, 31), (HEALTHY, 31)})),
        )
        self.assertEqual("stop", decision.action)
        self.assertIn("referenced needles its peer lacks", decision.summary)

    def test_healthy_volume_needs_nothing(self) -> None:
        healthy, _ = scenario(trailing_referenced=False)
        decision = self.decide(healthy, healthy, simulation="check-disk-simulation-sync.txt", copies=[facts(healthy, DAMAGED, False), facts(healthy, HEALTHY, False)])
        self.assertEqual("none", decision.action)

    def test_plans_are_checked_against_the_allowed_commands(self) -> None:
        healthy, damaged = scenario(trailing_referenced=True)
        decision = self.decide(healthy, damaged, simulation="check-disk-simulation-copy.txt")
        document = {"action": "copy", "healthy": HEALTHY, "damaged": DAMAGED, "target": TARGET, "steps": [s.to_json() for s in decision.steps]}
        self.assertEqual([], model.validate_steps(document, 31))
        document["steps"][2]["command"] = f"volume.delete -node {HEALTHY} -volumeId 31"
        self.assertTrue(model.validate_steps(document, 31))
        self.assertTrue(model.validate_steps({"action": "none", "steps": []}, 31))

    def test_weed_mutation(self) -> None:
        for command in ("lock", "unlock", "volume.list", "volume.check.disk -volumeId=1 -slow -v", "volume.fsck -volumeId 1 -v"):
            self.assertFalse(model.weed_mutation(command), command)
        for command in (
            "volume.check.disk -volumeId=1 -apply", "volume.check.disk -force", "volume.fsck -reallyDeleteFromVolume",
            "volume.copy -source a -target b -volumeId 1", "volume.delete -node a -volumeId 1", "volume.mark -writable",
        ):
            self.assertTrue(model.weed_mutation(command), command)


class GuardTests(unittest.TestCase):
    def kube(self, preflight_results=((),)) -> tuple[CLI.Kube, list, list, io.StringIO]:
        calls, checks, stream = [], [], io.StringIO()
        results = list(preflight_results)

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, b"ok", b"")

        def preflight(command, root):
            checks.append(command)
            return results.pop(0) if results else []

        prefix = ("mise", "exec", "--", "kubectl", "--kubeconfig", "/repo/kubeconfig", "--context", "tailscale-operator.example-tailnet.ts.net")
        return CLI.Kube(prefix, Path("/repo"), CLI.CommandLog(stream=stream), runner=runner, preflight=preflight), calls, checks, stream

    def test_exec_runs_the_shared_target_preflight_once_and_logs_redacted_commands(self) -> None:
        kube, calls, checks, stream = self.kube()
        kube.run(["-n", "storage", "exec", "pod", "-c", "volume", "--", "sh", "-c", CLI.READ_SCRIPT], mutation=True)
        kube.run(["-n", "storage", "exec", "pod", "-c", "volume", "--", "cat", "/data0/x"], mutation=True)
        kube.run(["-n", "storage", "get", "pods"])
        self.assertEqual(1, len(checks))
        self.assertEqual(subprocess.DEVNULL, calls[0][1]["stdin"])
        log = stream.getvalue()
        self.assertIn("--context tailscale-operator.<tailnet-name>.ts.net", log)
        self.assertNotIn("example-tailnet", log)
        self.assertIn("$READ_SCRIPT", log)

    def test_weed_shell_sessions_log_the_commands_they_send(self) -> None:
        kube, _, _, stream = self.kube()
        store = MemoryStore({})
        cluster = CLI.Cluster(kube)
        cluster._runtime = CLI.parse_runtime(VOLUME_PODS, MASTER_PODS)
        cluster.weed_shell(["lock", "volume.fsck -collection loki -volumeId 31 -v", "unlock"])
        self.assertIn("# weed shell: lock; volume.fsck -collection loki -volumeId 31 -v; unlock", stream.getvalue())

    def test_failed_preflight_and_policy_violations_block_before_running(self) -> None:
        violation = type("Violation", (), {"message": "current context does not match the Anton target"})()
        kube, calls, _, _ = self.kube(preflight_results=([violation],))
        with self.assertRaisesRegex(model.RepairError, "target preflight"):
            kube.run(["-n", "storage", "exec", "pod", "--", "true"], mutation=True)
        with self.assertRaisesRegex(model.RepairError, "command.destructive"):
            kube.run(["-n", "storage", "delete", "pvc", "mount0-seaweedfs-volume-0"])
        with self.assertRaisesRegex(model.RepairError, "command.secret-output"):
            kube.run(["-n", "storage", "get", "secret", "x", "-o", "yaml"])
        self.assertEqual([], calls)

    def test_cluster_refuses_unapproved_weed_mutations(self) -> None:
        cluster = CLI.Cluster(FakeKube(MemoryStore({}), SeaweedShell(MemoryStore({}), {}, simulation="", slow="")))
        with self.assertRaisesRegex(model.RepairError, "unapproved"):
            cluster.weed_shell(["lock", f"volume.delete -node {DAMAGED} -volumeId 31", "unlock"])

    def test_runtime_comes_from_the_live_pod_specs(self) -> None:
        runtime = CLI.parse_runtime(VOLUME_PODS, MASTER_PODS)
        self.assertEqual("seaweedfs-master-1", runtime.master_pod)
        self.assertEqual("seaweedfs-master-1.seaweedfs-master-peer.storage", runtime.master_host)
        self.assertEqual(set(SERVERS), set(runtime.servers))
        self.assertEqual(("seaweedfs-volume-2", "k8s-3", "/data0"), (runtime.servers[TARGET].pod, runtime.servers[TARGET].node, runtime.servers[TARGET].data_dir))
        self.assertEqual((IMAGE, 8444, 24, 5000, "001"), (runtime.image, runtime.volume_port, runtime.max_volumes, runtime.volume_size_limit_mb, runtime.default_replication))
        mixed = {"items": [*VOLUME_PODS["items"][:2], pod("seaweedfs-volume-2", "volume", VOLUME_COMMAND, "k8s-3", image=IMAGE[:-1] + "b")]}
        with self.assertRaisesRegex(model.RepairError, "different images"):
            CLI.parse_runtime(mixed, MASTER_PODS)

    def test_rehearsal_containers_reuse_production_names_flags_and_image(self) -> None:
        commands = []
        runner = lambda argv, **kwargs: commands.append(argv) or subprocess.CompletedProcess(argv, 0, b"", b"")  # noqa: E731
        runtime = CLI.parse_runtime(VOLUME_PODS, MASTER_PODS)
        CLI.DockerCluster(runtime, Path("/work"), "v31", CLI.CommandLog(stream=io.StringIO()), runner=runner).start()
        volume = next(c for c in commands if "seaweedfs-volume-0.seaweedfs-volume-peer.storage" in c and "run" in c)
        for expected in ("--network-alias", "-ip=seaweedfs-volume-0.seaweedfs-volume-peer.storage", "-port=8444", "-max=24", "/work/seaweedfs-volume-0:/data0", IMAGE):
            self.assertIn(expected, volume)
        master = next(c for c in commands if "master" in c and "run" in c)
        for expected in ("-volumeSizeLimitMB=5000", "-defaultReplication=001", "-ip=seaweedfs-master-1.seaweedfs-master-peer.storage"):
            self.assertIn(expected, master)


class StepCheckTests(unittest.TestCase):
    def test_shell_steps_must_show_their_planned_effects(self) -> None:
        step = model.Step("fix-read-only", "volume.check.disk -volumeId=31 -fixReadOnly -syncDeleted -apply -v",
                          {"writable": DAMAGED, "deletes": [[HEALTHY, DAMAGED, 2]]})
        applied = CLI.ShellResult(0, fixture("check-disk-fix.txt"), "")
        self.assertEqual([], CLI.evaluate_shell_step(step, applied, 31))

        more = model.Step(step.name, step.command, {"writable": DAMAGED, "deletes": [[HEALTHY, DAMAGED, 3]]})
        self.assertEqual([f"deletions {HEALTHY} -> {DAMAGED}: 2, planned 3"], CLI.evaluate_shell_step(more, applied, 31))

        reverted = CLI.ShellResult(0, fixture("check-disk-fix.txt").rsplit("\n", 2)[0] + f"\nvolume 31 on {DAMAGED} is now read-only\n", "")
        failures = CLI.evaluate_shell_step(step, reverted, 31)
        self.assertIn(f"check.disk did not report {DAMAGED} synced and writable", failures)
        self.assertIn(f"check.disk returned {DAMAGED} to read-only", failures)

        broken = CLI.ShellResult(1, "", "error: lock is lost\n")
        failures = CLI.evaluate_shell_step(model.Step("delete-damaged", "volume.delete -node x -volumeId 31"), broken, 31)
        self.assertEqual(["error: lock is lost", "error: weed shell exited 1"], failures[1:])

    def test_reads_must_agree_across_copies_and_with_the_bytes_before_the_repair(self) -> None:
        class Reads:
            def __init__(self, hashes):
                self.hashes = hashes

            def read_needles(self, reads):
                return {pair: self.hashes.get(pair) for pair in reads}

        fids = {1: "31,100010001", 4: "31,400010004"}
        same = {(server, fid): f"sha-{fid}" for server in (HEALTHY, DAMAGED) for fid in fids.values()}
        baseline = {fid: f"sha-{fid}" for fid in fids.values()}
        self.assertEqual(0, CLI.check_reads(Reads(same), [HEALTHY, DAMAGED], fids, baseline)["failed"])

        changed = {fid: "older" for fid in fids.values()}
        self.assertIn("differs from its bytes before the repair", CLI.check_reads(Reads(same), [HEALTHY, DAMAGED], fids, changed)["failures"][0])
        split = {**same, (DAMAGED, fids[4]): "other"}
        self.assertEqual([f"{fids[4]} differs between copies"], CLI.check_reads(Reads(split), [HEALTHY, DAMAGED], fids)["failures"])
        missing = {**same, (DAMAGED, fids[1]): None}
        self.assertEqual([f"{fids[1]} unreadable on ['{DAMAGED}']"], CLI.check_reads(Reads(missing), [HEALTHY, DAMAGED], fids)["failures"])

    def test_needle_read_output_treats_empty_bodies_as_failures(self) -> None:
        parsed = CLI.parse_needle_reads(f"OK {HEALTHY} 31,1 {'b' * 64}\nOK {DAMAGED} 31,1 {CLI.EMPTY_SHA256}\nFAIL {DAMAGED} 31,4\n")
        self.assertEqual({(HEALTHY, "31,1"): "b" * 64, (DAMAGED, "31,1"): None, (DAMAGED, "31,4"): None}, parsed)
        with self.assertRaises(model.RepairError):
            CLI.parse_needle_reads("garbage\n")


class CommandFlowTests(unittest.TestCase):
    def test_plan_reports_the_in_place_repair_without_mutating(self) -> None:
        flow = Flow(self, trailing_referenced=False)
        code, output = flow.run("plan", "31")
        self.assertEqual(0, code, output)
        plan = flow.plan()
        self.assertEqual("check-disk", plan["decision"]["action"])
        self.assertEqual("unindexed-tail", plan["copies"][DAMAGED]["data"]["status"])
        self.assertEqual(f"31,7{cookie(7):08x}", plan["copies"][DAMAGED]["data"]["trailing"][0]["fid"])
        self.assertEqual(["1", "4"], plan["decision"]["referenced"])
        self.assertTrue(plan["snapshot"]["stable"])
        self.assertEqual(hashlib.sha256(flow.store.get(HEALTHY, f"{BASE}.dat")).hexdigest(), plan["snapshot"]["files"][HEALTHY][f"{BASE}.dat"]["sha256"])
        self.assertEqual([], plan["simulation"]["cross_check"])
        self.assertEqual([INTEGRITY_LOG], plan["copies"][DAMAGED]["log_evidence"])
        self.assertFalse(any(model.weed_mutation(c) for session in flow.shell.sessions for c in session))
        self.assertIn(["lock", "volume.check.disk -volumeId=31 -fixReadOnly -syncDeleted -v", "unlock"], flow.shell.sessions)
        self.assertIn(["lock", "volume.fsck -collection loki -volumeId 31 -v", "unlock"], flow.shell.sessions)
        self.assertIn("Action: check-disk", output)
        self.assertEqual({DAMAGED: 2, HEALTHY: 2}, plan["fsck"]["referenced"])
        self.assertEqual({"partially_deleted": 2, "absent": 0}, plan["differences"][f"{HEALTHY} -> {DAMAGED}"])
        self.assertIn("seaweedfs-volume-0 missed 2 deletion(s)", output)

    def test_plan_stops_when_a_copy_has_nowhere_to_go(self) -> None:
        flow = Flow(self, trailing_referenced=True, free=(1, 0, 0))
        code, output = flow.run("plan", "31")
        self.assertEqual(1, code)
        self.assertEqual("stop", flow.plan()["decision"]["action"])
        self.assertIn("free slot", output)

    def test_check_disk_repair_flows_from_plan_to_verify(self) -> None:
        flow = Flow(self, trailing_referenced=False)
        self.assertEqual(0, flow.run("plan", "31")[0])
        self.assertEqual(0, flow.run("preserve", "31")[0])
        sums = (flow.state().dir / "snapshots").glob("*/SHA256SUMS")
        self.assertIn("seaweedfs-volume-0/loki_31.dat", next(sums).read_text())

        code, output = flow.run("rehearse", "31")
        self.assertEqual(0, code, output)
        rehearsal = json.loads(flow.state().path("rehearsal.json").read_text())
        self.assertTrue(rehearsal["pass"])
        self.assertEqual(["fix-read-only", "converge-deletions"], [s["name"] for s in rehearsal["steps"]])
        self.assertEqual({DAMAGED: 0, HEALTHY: 0}, rehearsal["checks"]["integrity_failures_after_restart"])
        self.assertEqual(4, rehearsal["checks"]["reads"]["reads"])
        self.assertFalse(any(flow.docker.data_dir(s).exists() for s in SERVERS), "work directories are removed")

        with patch.dict(os.environ, {CLI.APPROVAL: "0"}):
            code, output = flow.run("apply", "31")
        self.assertEqual(3, code, output)
        self.assertIn("Preview only", output)
        self.assertFalse(any(model.weed_mutation(c) for session in flow.shell.sessions for c in session))

        with patch.dict(os.environ, {CLI.APPROVAL: "1"}):
            code, output = flow.run("apply", "31")
        self.assertEqual(0, code, output)
        mutations = [session for session in flow.shell.sessions if any(model.weed_mutation(c) for c in session)]
        self.assertEqual(
            [
                ["lock", "volume.check.disk -volumeId=31 -fixReadOnly -syncDeleted -apply -v", "unlock"],
                ["lock", "volume.check.disk -volumeId=31 -slow -syncDeleted -apply -v", "unlock"],
            ],
            mutations,
        )

        flow.kube.gauge = {"seaweedfs-volume-0": 0.0, "seaweedfs-volume-1": 0.0}
        code, output = flow.run("verify", "31")
        self.assertEqual(0, code, output)
        verify = json.loads(flow.state().path("verify.json").read_text())
        self.assertEqual({"consistent"}, {tail["status"] for tail in verify["tails"].values()})
        self.assertEqual(2, verify["fsck"]["referenced"])

    def test_copy_repair_flows_from_plan_to_verify(self) -> None:
        flow = Flow(self, trailing_referenced=True)
        for subcommand in ("plan", "preserve", "rehearse"):
            code, output = flow.run(subcommand, "31")
            self.assertEqual(0, code, f"{subcommand}: {output}")
        with patch.dict(os.environ, {CLI.APPROVAL: "1"}):
            code, output = flow.run("apply", "31")
        self.assertEqual(0, code, output)
        mutations = [session[1] for session in flow.shell.sessions if any(model.weed_mutation(c) for c in session)]
        self.assertEqual([f"volume.copy -source {HEALTHY} -target {TARGET} -volumeId 31", f"volume.delete -node {DAMAGED} -volumeId 31"], mutations)
        self.assertEqual({}, flow.store.files[DAMAGED])
        flow.shell.fsck = flow.fsck_after
        flow.kube.gauge = {"seaweedfs-volume-1": 0.0, "seaweedfs-volume-2": 0.0}
        code, output = flow.run("verify", "31")
        self.assertEqual(0, code, output)

    def test_apply_refuses_when_live_files_moved_after_the_rehearsal(self) -> None:
        flow = Flow(self, trailing_referenced=False)
        for subcommand in ("plan", "preserve", "rehearse"):
            self.assertEqual(0, flow.run(subcommand, "31")[0])
        flow.shell.tombstone(HEALTHY, 4)
        with patch.dict(os.environ, {CLI.APPROVAL: "1"}):
            code, output = flow.run("apply", "31")
        self.assertEqual(1, code)
        self.assertIn("changed since plan", output)
        self.assertFalse(any(model.weed_mutation(c) for session in flow.shell.sessions for c in session))

    def test_apply_refuses_without_a_rehearsal_for_this_plan(self) -> None:
        flow = Flow(self, trailing_referenced=False)
        for subcommand in ("plan", "preserve"):
            self.assertEqual(0, flow.run(subcommand, "31")[0])
        with patch.dict(os.environ, {CLI.APPROVAL: "1"}):
            self.assertEqual(1, flow.run("apply", "31")[0])
        self.assertEqual(0, flow.run("rehearse", "31")[0])
        with patch.object(CLI, "utc_now", lambda: "2026-10-24T00:00:00Z"):
            self.assertEqual(0, flow.run("plan", "31")[0])
        with patch.dict(os.environ, {CLI.APPROVAL: "1"}):
            code, _ = flow.run("apply", "31")
        self.assertEqual(1, code, "a different plan.json invalidates the earlier preserve and rehearsal")
        self.assertFalse(any(model.weed_mutation(c) for session in flow.shell.sessions for c in session))

    def test_preserve_refuses_files_that_changed_since_the_plan(self) -> None:
        flow = Flow(self, trailing_referenced=False)
        self.assertEqual(0, flow.run("plan", "31")[0])
        flow.shell.tombstone(HEALTHY, 4)
        code, output = flow.run("preserve", "31")
        self.assertEqual(1, code)
        self.assertFalse(json.loads(flow.state().path("preserve.json").read_text())["matches_plan"])
        self.assertIn("changed since the plan", output)

    def test_rehearsal_fails_when_the_snapshot_does_not_reproduce_the_failure(self) -> None:
        flow = Flow(self, trailing_referenced=False)
        for subcommand in ("plan", "preserve"):
            self.assertEqual(0, flow.run(subcommand, "31")[0])
        flow.read_only_reproduced = False
        code, output = flow.run("rehearse", "31")
        self.assertEqual(1, code)
        self.assertIn("did not reproduce", output)
        self.assertFalse(json.loads(flow.state().path("rehearsal.json").read_text())["pass"])

    def test_verify_fails_before_the_repair(self) -> None:
        flow = Flow(self, trailing_referenced=False)
        flow.kube.gauge = {"seaweedfs-volume-0": 1.0, "seaweedfs-volume-1": 0.0}
        code, output = flow.run("verify", "31", "--settle-seconds", "0")
        self.assertEqual(1, code)
        for expected in ("read-only copies", "read-only gauge", "index does not end at its data size", "missed 2 deletion(s)"):
            self.assertIn(expected, output)


if __name__ == "__main__":
    unittest.main()
