"""Model SeaweedFS 4.48 volume files and plan a read-only copy repair.

Everything here is pure: callers pass index bytes, needle headers and weed
shell output. The semantics follow the deployed 4.48 sources:
weed/storage/volume_checking.go (startup integrity check),
weed/shell/command_volume_check_disk.go and weed/shell/command_volume_fsck.go.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal, Mapping, Sequence

INDEX_ENTRY_SIZE = 16
NEEDLE_HEADER_SIZE = 16
SUPERBLOCK_SIZE = 8
TOMBSTONE_SIZE = -1
VOLUME_FILE_EXTENSIONS = (".dat", ".idx", ".sdx", ".vif")
REQUIRED_EXTENSIONS = (".dat", ".idx", ".vif")
COMPACTION_EXTENSIONS = (".cpd", ".cpx", ".cpldb")
MAX_TRAILING_NEEDLES = 64

Action = Literal["none", "check-disk", "copy", "stop"]
HeaderReader = Callable[[int], bytes]


class RepairError(ValueError):
    """Input the repair model refuses to interpret."""


def volume_base_name(collection: str, volume_id: int) -> str:
    return f"{collection}_{volume_id}" if collection else str(volume_id)


def file_id(volume_id: int, key: int, cookie: int) -> str:
    return f"{volume_id},{key:x}{cookie:08x}"


def key_hex(key: int) -> str:
    return f"{key:x}"


def copy_count(replica_placement: str) -> int:
    if not re.fullmatch(r"\d{3}", replica_placement):
        raise RepairError(f"unsupported replica placement {replica_placement!r}")
    return 1 + sum(int(digit) for digit in replica_placement)


def normalize_server(address: str) -> str:
    """Drop the `.grpcPort` suffix weed shell prints in raw server addresses."""
    match = re.fullmatch(r"(.+:\d+)\.\d+", address)
    return match.group(1) if match else address


# --- Volume file formats ---------------------------------------------------


@dataclass(frozen=True)
class IndexEntry:
    key: int
    offset: int  # byte offset in .dat: the stored 4-byte value times 8
    size: int  # signed size field; negative marks a deletion


def parse_index(data: bytes) -> tuple[IndexEntry, ...]:
    if len(data) % INDEX_ENTRY_SIZE:
        raise RepairError(f"index length {len(data)} is not a multiple of {INDEX_ENTRY_SIZE}")
    return tuple(
        IndexEntry(key, stored * 8, size)
        for key, stored, size in struct.iter_unpack(">QIi", data)
    )


@dataclass(frozen=True)
class IndexState:
    """Replayed .idx: `present` is check.disk's view of the last entry per key."""

    entries: tuple[IndexEntry, ...]
    present: Mapping[int, IndexEntry]

    @classmethod
    def parse(cls, data: bytes) -> IndexState:
        return cls.from_entries(parse_index(data))

    @classmethod
    def from_entries(cls, entries: Sequence[IndexEntry]) -> IndexState:
        present: dict[int, IndexEntry] = {}
        for entry in entries:
            if entry.offset == 0:
                present.pop(entry.key, None)
            else:
                present[entry.key] = entry
        return cls(tuple(entries), present)

    @property
    def live(self) -> frozenset[int]:
        return frozenset(key for key, entry in self.present.items() if entry.size > 0)

    @property
    def tombstoned(self) -> frozenset[int]:
        return frozenset(key for key, entry in self.present.items() if entry.size < 0)

    @property
    def empty(self) -> frozenset[int]:
        return frozenset(key for key, entry in self.present.items() if entry.size == 0)

    @property
    def zero_offset_entries(self) -> int:
        return sum(1 for entry in self.entries if entry.offset == 0)


def needle_disk_size(size: int, version: int = 3) -> int:
    """needle.GetActualSize: header, body, checksum, v3 timestamp, 1-8 bytes of padding."""
    raw = 0 if size == TOMBSTONE_SIZE else abs(size)
    unpadded = NEEDLE_HEADER_SIZE + raw + 4 + (8 if version == 3 else 0)
    return unpadded + 8 - unpadded % 8


def dat_tail_entry(entries: Sequence[IndexEntry], dat_size: int, version: int = 3) -> IndexEntry | None:
    """The entry 4.48 checks at startup: the last one if it ends the .dat, else the max offset."""
    if entries and dat_size > 0:
        last = entries[-1]
        if last.offset and last.offset + needle_disk_size(last.size, version) == dat_size:
            return last
    tail: IndexEntry | None = None
    for entry in entries:
        if entry.offset and (tail is None or entry.offset > tail.offset):
            tail = entry
    return tail


@dataclass(frozen=True)
class NeedleHeader:
    cookie: int
    key: int
    size: int

    @classmethod
    def parse(cls, data: bytes) -> NeedleHeader:
        if len(data) != NEEDLE_HEADER_SIZE:
            raise RepairError(f"needle header must be {NEEDLE_HEADER_SIZE} bytes, got {len(data)}")
        cookie, key, size = struct.unpack(">IQi", data)
        return cls(cookie, key, size)


@dataclass(frozen=True)
class SuperBlock:
    version: int
    replica_placement: str
    compaction_revision: int
    extra_size: int

    @classmethod
    def parse(cls, data: bytes) -> SuperBlock:
        if len(data) < SUPERBLOCK_SIZE:
            raise RepairError("superblock is shorter than 8 bytes")
        version, placement = data[0], data[1]
        revision, extra = struct.unpack(">HH", data[4:8])
        return cls(version, f"{placement // 100}{placement // 10 % 10}{placement % 10}", revision, extra)

    @property
    def data_start(self) -> int:
        return SUPERBLOCK_SIZE + (self.extra_size if self.version in (2, 3) else 0)


@dataclass(frozen=True)
class VolumeInfo:
    """The .vif document; a persisted readOnly flag is not the integrity failure class."""

    version: int
    replication: str
    bytes_offset: int
    read_only: bool

    @classmethod
    def parse(cls, data: bytes) -> VolumeInfo:
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RepairError(f"volume info is not JSON: {error}") from None
        if not isinstance(document, dict):
            raise RepairError("volume info is not a JSON object")
        return cls(
            int(document.get("version", 0)),
            str(document.get("replication", "")),
            int(document.get("bytesOffset", 0)),
            document.get("readOnly") is True,
        )


@dataclass(frozen=True)
class TrailingNeedle:
    offset: int
    key: int
    cookie: int
    size: int


@dataclass(frozen=True)
class DataCheck:
    """Whether the .dat ends where the startup check expects, and what lies beyond."""

    status: Literal["consistent", "unindexed-tail", "short-data", "header-mismatch"]
    dat_size: int
    expected_size: int
    tail_key: int | None
    trailing: tuple[TrailingNeedle, ...] = ()
    trailing_complete: bool = True

    @property
    def consistent(self) -> bool:
        return self.status == "consistent"


def check_data(
    index: IndexState,
    dat_size: int,
    read_header: HeaderReader,
    *,
    data_start: int = SUPERBLOCK_SIZE,
    version: int = 3,
) -> DataCheck:
    tail = dat_tail_entry(index.entries, dat_size, version)
    if tail is None:
        expected, tail_key = data_start, None
    else:
        expected, tail_key = tail.offset + needle_disk_size(tail.size, version), tail.key
    if dat_size < expected:
        return DataCheck("short-data", dat_size, expected, tail_key)
    if tail is not None:
        header = NeedleHeader.parse(read_header(tail.offset))
        header_size = 0 if tail.size < 0 else tail.size
        if header.key != tail.key or header.size != header_size:
            return DataCheck("header-mismatch", dat_size, expected, tail_key)
    if dat_size == expected:
        return DataCheck("consistent", dat_size, expected, tail_key)
    trailing: list[TrailingNeedle] = []
    offset = expected
    while offset < dat_size and len(trailing) < MAX_TRAILING_NEEDLES:
        raw = read_header(offset)
        if len(raw) < NEEDLE_HEADER_SIZE:
            break
        header = NeedleHeader.parse(raw)
        end = offset + needle_disk_size(header.size, version)
        if header.key == 0 or header.size < 0 or end > dat_size:
            break
        trailing.append(TrailingNeedle(offset, header.key, header.cookie, header.size))
        offset = end
    return DataCheck("unindexed-tail", dat_size, expected, tail_key, tuple(trailing), offset == dat_size)


@dataclass(frozen=True)
class PairDiff:
    """What volume.check.disk computes for one source -> target direction."""

    entries: int
    partially_deleted: frozenset[int]
    absent: frozenset[int]


def check_disk_diff(source: IndexState, target: IndexState) -> PairDiff:
    partially = {
        key
        for key, entry in source.present.items()
        if entry.size < 0 and key in target.present and target.present[key].size >= 0
    }
    absent = {
        key
        for key, entry in source.present.items()
        if entry.size >= 0 and key not in target.present
    }
    return PairDiff(len(source.present), frozenset(partially), frozenset(absent))


# --- weed shell output -----------------------------------------------------


@dataclass(frozen=True)
class VolumeCopy:
    server: str
    volume_id: int
    collection: str
    size: int
    replica_placement: str
    version: int
    file_count: int
    delete_count: int
    read_only: bool


@dataclass(frozen=True)
class DataNode:
    server: str
    data_center: str
    rack: str
    volumes: int
    max_volumes: int
    free: int


@dataclass(frozen=True)
class Topology:
    volume_size_limit_mb: int
    nodes: Mapping[str, DataNode]
    copies: tuple[VolumeCopy, ...]
    ec_volume_ids: frozenset[int] = frozenset()
    unrecognized: tuple[str, ...] = ()

    def copies_of(self, volume_id: int) -> tuple[VolumeCopy, ...]:
        return tuple(copy for copy in self.copies if copy.volume_id == volume_id)


_DISK_INFO = re.compile(r" (\w+)\(volume:(\d+)/(\d+) active:\d+ free:(-?\d+) remote:\d+\)")
_TOPOLOGY_IGNORED = (
    re.compile(r"^\s*$"),
    re.compile(r"^\s+(?:DataCenter|Rack|DataNode) \S+ \{"),
    re.compile(r"^\s+Disk \w+(?:\(| \{)"),
    re.compile(r"^total size:"),
    re.compile(r"^(?:WARNING: |  volume \d+ in collections: )"),
)


def parse_volume_list(text: str) -> Topology:
    limit: int | None = None
    data_center = rack = ""
    node: str | None = None
    nodes: dict[str, DataNode] = {}
    copies: list[VolumeCopy] = []
    ec_ids: set[int] = set()
    unrecognized: list[str] = []
    for line in text.splitlines():
        if match := re.match(r"^Topology volumeSizeLimit:(\d+) MB", line):
            limit = int(match.group(1))
        elif match := re.match(r"^\s+DataCenter (\S+) \w+\(", line):
            data_center = match.group(1)
        elif match := re.match(r"^\s+Rack (\S+) \w+\(", line):
            rack = match.group(1)
        elif match := re.match(r"^\s+DataNode (\S+)((?: \w+\([^)]*\))+)\s*$", line):
            node = match.group(1)
            disks = _DISK_INFO.findall(match.group(2))
            if not disks:
                unrecognized.append(line)
                continue
            nodes[node] = DataNode(
                node,
                data_center,
                rack,
                sum(int(disk[1]) for disk in disks),
                sum(int(disk[2]) for disk in disks),
                sum(int(disk[3]) for disk in disks),
            )
        elif match := re.match(r"^\s+volume (Id:.*?)\s*$", line):
            if node is None:
                unrecognized.append(line)
                continue
            fields = dict(item.partition(":")[::2] for item in match.group(1).split(", "))
            try:
                copies.append(
                    VolumeCopy(
                        node,
                        int(fields["Id"]),
                        fields["Collection"],
                        int(fields["Size"]),
                        fields["ReplicaPlacement"],
                        int(fields["Version"]),
                        int(fields["FileCount"]),
                        int(fields["DeleteCount"]),
                        {"true": True, "false": False}[fields["ReadOnly"]],
                    )
                )
            except (KeyError, ValueError):
                unrecognized.append(line)
        elif match := re.match(r"^\s+ec volume id:(\d+)", line):
            ec_ids.add(int(match.group(1)))
        elif not any(pattern.match(line) for pattern in _TOPOLOGY_IGNORED):
            unrecognized.append(line)
    if limit is None:
        raise RepairError("volume.list output has no Topology line")
    return Topology(limit, nodes, tuple(copies), frozenset(ec_ids), tuple(unrecognized))


@dataclass(frozen=True)
class SyncLine:
    volume_id: int
    source: str
    entries: int
    target: str
    missed: int
    partially_deleted: int


@dataclass(frozen=True)
class Divergence:
    volume_id: int
    kind: Literal["one-sided", "two-sided"]
    text: str
    lagging: str = ""
    missing: int = 0


@dataclass(frozen=True)
class Transfer:
    volume_id: int
    key: int
    source: str
    target: str


@dataclass(frozen=True)
class CheckDiskReport:
    skipped_read_only: tuple[tuple[int, str], ...] = ()
    sync: tuple[SyncLine, ...] = ()
    not_resurrecting: tuple[tuple[int, str, int, str], ...] = ()
    divergence: tuple[Divergence, ...] = ()
    now_writable: tuple[tuple[int, str], ...] = ()
    synced_writable: tuple[tuple[int, str], ...] = ()
    now_read_only: tuple[tuple[int, str], ...] = ()
    deletes: tuple[Transfer, ...] = ()
    resurrected: tuple[Transfer, ...] = ()
    synced_pairs: tuple[tuple[int, str, str], ...] = ()
    no_read_only: tuple[int, ...] = ()
    errors: tuple[str, ...] = ()
    unrecognized: tuple[str, ...] = ()

    def problems(self) -> list[str]:
        return [*self.errors, *(f"unrecognized output: {line}" for line in self.unrecognized)]


_CHECK_DISK_INFO = (
    re.compile(r"^\s*$"),
    re.compile(r"^Running in simulation mode"),
    re.compile(r"^Pass #\d \((?:writable|read-only) volumes\)$"),
    re.compile(r"^sync iteration \d+/\d+ for volume \d+$"),
    re.compile(r"^load collection \S* volume \d+ index size \d+ from \S+ \.\.\.$"),
    re.compile(r"^skipping active volumes \d+ with the same file counts on \S+ and \S+$"),
    re.compile(r"^(?:lock acquired|waiting for lock held by .*)$"),
    re.compile(r"^master: \S+(?: filers: .*)?$"),
    re.compile(r"^-force is deprecated"),
)
_CHECK_DISK_ERRORS = (
    re.compile(r"^error: "),
    re.compile(r"^unknown command: "),
    re.compile(r"^failed to "),
    re.compile(r"^error checking if volume "),
    re.compile(r"^sync read-only volume "),
    re.compile(r"^volume \d+ sync (?:is not making progress|reached maximum iterations)"),
    re.compile(r"^got \d+ read-only replicas for volume \d+ and no writable replicas"),
)


def _key_from_fid(fid: str) -> int:
    if len(fid) <= 8:
        raise RepairError(f"file id {fid!r} has no needle key")
    return int(fid[:-8], 16)


def parse_check_disk(text: str) -> CheckDiskReport:
    fields: dict[str, list] = {name: [] for name in CheckDiskReport.__dataclass_fields__}
    for line in text.splitlines():
        line = line.rstrip()
        if match := re.match(r"^skipping readonly volume (\d+) on (\S+)$", line):
            fields["skipped_read_only"].append((int(match.group(1)), match.group(2)))
        elif match := re.match(
            r"^volume (\d+) (\S+) has (\d+) entries, (\S+) missed (\d+) and partially deleted (\d+) entries$",
            line,
        ):
            vid, source, entries, target, missed, partially = match.groups()
            fields["sync"].append(SyncLine(int(vid), source, int(entries), target, int(missed), int(partially)))
        elif match := re.match(r"^volume (\d+) (\S+): not resurrecting (\d+) needle\(s\) absent on (\S+) \(", line):
            vid, source, count, target = match.groups()
            fields["not_resurrecting"].append((int(vid), source, int(count), target))
        elif match := re.match(r"^volume (\d+): ONE-SIDED divergence \S+ (\S+) is missing (\d+) live needle", line):
            fields["divergence"].append(
                Divergence(int(match.group(1)), "one-sided", line, normalize_server(match.group(2)), int(match.group(3)))
            )
        elif match := re.match(r"^volume (\d+): TWO-SIDED", line):
            fields["divergence"].append(Divergence(int(match.group(1)), "two-sided", line))
        elif match := re.match(r"^volume (\d+) on (\S+) is now writable$", line):
            fields["now_writable"].append((int(match.group(1)), match.group(2)))
        elif match := re.match(r"^volume (\d+) on (\S+) is now synced to .* and writable$", line):
            fields["synced_writable"].append((int(match.group(1)), match.group(2)))
        elif match := re.match(r"^volume (\d+) on (\S+) is now read-only$", line):
            fields["now_read_only"].append((int(match.group(1)), match.group(2)))
        elif match := re.match(r"^(delete|read) (\d+),([0-9a-f]+) (\S+) => (\S+)$", line):
            kind, vid, fid, source, target = match.groups()
            transfer = Transfer(int(vid), _key_from_fid(fid), source, target)
            fields["deletes" if kind == "delete" else "resurrected"].append(transfer)
        elif match := re.match(r"^synced (\S+) and (\S+) for volume (\d+)$", line):
            fields["synced_pairs"].append((int(match.group(3)), match.group(1), match.group(2)))
        elif match := re.match(r"^no read-only replicas for volume (\d+)$", line):
            fields["no_read_only"].append(int(match.group(1)))
        elif any(pattern.match(line) for pattern in _CHECK_DISK_ERRORS):
            fields["errors"].append(line)
        elif not any(pattern.match(line) for pattern in _CHECK_DISK_INFO):
            fields["unrecognized"].append(line)
    return CheckDiskReport(**{name: tuple(values) for name, values in fields.items()})


@dataclass(frozen=True)
class FsckReport:
    collected: frozenset[tuple[str, int]] = frozenset()
    orphans: Mapping[tuple[str, int], frozenset[int]] = field(default_factory=dict)
    unresolved_manifests: int = 0
    errors: tuple[str, ...] = ()
    unrecognized: tuple[str, ...] = ()

    def problems(self) -> list[str]:
        problems = [*self.errors, *(f"unrecognized output: {line}" for line in self.unrecognized)]
        if self.unresolved_manifests:
            problems.append(
                f"{self.unresolved_manifests} filer entr(ies) had unresolvable chunk manifests; "
                "their sub-chunks would look unreferenced"
            )
        return problems

    def orphans_on(self, server: str, volume_id: int) -> frozenset[int]:
        return self.orphans.get((server, volume_id), frozenset())


_FSCK_INFO = (
    re.compile(r"^\s*$"),
    re.compile(r"^working directory: "),
    re.compile(r"^collecting volume id and locations from master \.\.\.$"),
    re.compile(r"^dn \S+ (?:collected \d+ volumes and \d+ ec shards|filtered \d+ volumes and locations)\.$"),
    re.compile(r"^scoping filer walk to "),
    re.compile(r"^checking each file from filer path "),
    re.compile(r"^checking directory "),
    re.compile(r"^total \d+ directories, \d+ files$"),
    re.compile(r"^Total\t+entries:\d+\torphan:\d+\t"),
    re.compile(r"^This could be normal if multiple filers or no filers are used\.$"),
    re.compile(r"^no orphan data$"),
    re.compile(r"^(?:lock acquired|waiting for lock held by .*)$"),
    re.compile(r"^master: \S+(?: filers: .*)?$"),
)
_FSCK_ERRORS = (
    re.compile(r"^(?:error|got error): "),
    re.compile(r"^unknown command: "),
    re.compile(r"^failed to "),
    re.compile(r"^skipping time-based filtering for EC volume "),
    re.compile(r"^skip purging "),
)


def parse_fsck(text: str) -> FsckReport:
    collected: set[tuple[str, int]] = set()
    orphans: dict[tuple[str, int], set[int]] = {}
    expected: dict[tuple[str, int], int] = {}
    current: tuple[str, int] | None = None
    unresolved = 0
    errors: list[str] = []
    unrecognized: list[str] = []
    for line in text.splitlines():
        line = line.rstrip("\r")
        if match := re.match(r"^collecting volume (\d+) file ids from (\S+) \.\.\.$", line):
            collected.add((match.group(2), int(match.group(1))))
        elif match := re.match(r"^dataNode:(\S+)\tvolume:(\d+)\tentries:(\d+)\torphan:(\d+)\t", line):
            current = (match.group(1), int(match.group(2)))
            orphans.setdefault(current, set())
            expected[current] = int(match.group(4))
        elif match := re.match(r"^([^:\s]*):(\d+),([0-9a-f]{9,24})$", line):
            vid = int(match.group(2))
            if current is None or current[1] != vid:
                errors.append(f"orphan without a matching summary: {line}")
                continue
            orphans[current].add(_key_from_fid(match.group(3)))
        elif line.startswith("WARNING: ResolveChunkManifest failed"):
            unresolved += 1
        elif any(pattern.match(line) for pattern in _FSCK_ERRORS):
            errors.append(line)
        elif not any(pattern.match(line) for pattern in _FSCK_INFO):
            unrecognized.append(line)
    for key, count in expected.items():
        if len(orphans[key]) != count:
            errors.append(f"fsck listed {len(orphans[key])} orphan ids for {key[0]} volume {key[1]}, expected {count}")
    return FsckReport(
        frozenset(collected),
        {key: frozenset(values) for key, values in orphans.items()},
        unresolved,
        tuple(errors),
        tuple(unrecognized),
    )


def cross_check(report: CheckDiskReport, states: Mapping[str, IndexState], volume_id: int) -> list[str]:
    """Compare each direction check.disk printed with the same diff computed from the indexes."""
    mismatches: list[str] = []
    printed_absent = {
        (source, target): count
        for vid, source, count, target in report.not_resurrecting
        if vid == volume_id
    }
    for line in report.sync:
        if line.volume_id != volume_id:
            continue
        if line.source not in states or line.target not in states:
            mismatches.append(f"check.disk compared unknown copy {line.source} -> {line.target}")
            continue
        diff = check_disk_diff(states[line.source], states[line.target])
        observed = (line.entries, line.partially_deleted, printed_absent.get((line.source, line.target), 0))
        modeled = (diff.entries, len(diff.partially_deleted), len(diff.absent))
        if observed != modeled:
            mismatches.append(
                f"{line.source} -> {line.target}: check.disk reported entries/partially-deleted/absent "
                f"{observed}, the indexes give {modeled}"
            )
    return mismatches


# --- Repair decision -------------------------------------------------------


@dataclass(frozen=True)
class CopyFacts:
    server: str
    read_only: bool
    index: IndexState
    data: DataCheck
    superblock: SuperBlock
    info: VolumeInfo
    compaction_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    name: Literal["fix-read-only", "converge-deletions", "copy", "read-check", "delete-damaged"]
    command: str = ""
    expect: Mapping[str, object] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"name": self.name, "command": self.command, "expect": dict(self.expect)}

    @classmethod
    def from_json(cls, value: Mapping) -> Step:
        return cls(value["name"], value.get("command", ""), dict(value.get("expect", {})))


@dataclass(frozen=True)
class Decision:
    action: Action
    summary: str
    reasons: tuple[str, ...] = ()
    healthy: str | None = None
    damaged: str | None = None
    target: str | None = None
    steps: tuple[Step, ...] = ()
    referenced: frozenset[int] = frozenset()
    accepted_divergence: frozenset[int] = frozenset()
    final_copies: tuple[str, ...] = ()
    sets: Mapping[str, frozenset[int]] = field(default_factory=dict)


def _stop(summary: str, reasons: Iterable[str], **known) -> Decision:
    return Decision("stop", summary, tuple(reasons), **known)


def weed_mutation(command: str) -> bool:
    """Whether a weed shell command can change volume data or placement."""
    words = command.split()
    if not words or words[0] in {"lock", "unlock", "volume.list"}:
        return False
    flags = words[1:]
    if words[0] == "volume.check.disk":
        return any(flag.split("=", 1)[0] in {"-apply", "-force"} for flag in flags)
    if words[0] == "volume.fsck":
        return any(
            flag.split("=", 1)[0] in {"-reallyDeleteFromVolume", "-reallyDeleteFilerEntries", "-forcePurging"}
            for flag in flags
        )
    return True


def planned_commands(action: str, volume_id: int, healthy: str, damaged: str, target: str | None, converge: bool) -> list[str]:
    """The only commands each action may run; plans are checked against these."""
    if action == "check-disk":
        commands = [f"volume.check.disk -volumeId={volume_id} -fixReadOnly -syncDeleted -apply -v"]
        if converge:
            commands.append(f"volume.check.disk -volumeId={volume_id} -slow -syncDeleted -apply -v")
        return commands
    if action == "copy" and target:
        return [
            f"volume.copy -source {healthy} -target {target} -volumeId {volume_id}",
            "",
            f"volume.delete -node {damaged} -volumeId {volume_id}",
        ]
    return []


def validate_steps(decision: Mapping, volume_id: int) -> list[str]:
    """Reject a plan whose steps differ from what its own decision allows."""
    steps = [Step.from_json(step) for step in decision.get("steps", [])]
    names = [step.name for step in steps]
    action = decision.get("action")
    expected_names = {
        "check-disk": [["fix-read-only"], ["fix-read-only", "converge-deletions"]],
        "copy": [["copy", "read-check", "delete-damaged"]],
    }.get(action)
    if expected_names is None:
        return [f"action {action!r} has no repair steps"]
    if names not in expected_names:
        return [f"steps {names} do not match action {action}"]
    expected = planned_commands(
        action,
        volume_id,
        str(decision.get("healthy")),
        str(decision.get("damaged")),
        decision.get("target"),
        "converge-deletions" in names,
    )
    problems = [
        f"step {step.name} command {step.command!r} differs from {command!r}"
        for step, command in zip(steps, expected)
        if step.command != command
    ]
    return problems


def _unsupported(copies: Sequence[CopyFacts]) -> list[str]:
    problems: list[str] = []
    for copy in copies:
        if copy.superblock.version != 3 or copy.info.version not in (0, 3):
            problems.append(f"{copy.server}: needle version {copy.superblock.version} is not 3")
        if copy.info.bytes_offset != 4:
            problems.append(f"{copy.server}: {copy.info.bytes_offset}-byte offsets are not supported")
        if copy.compaction_files:
            problems.append(f"{copy.server}: compaction in progress ({', '.join(copy.compaction_files)})")
        if copy.index.empty:
            problems.append(f"{copy.server}: {len(copy.index.empty)} zero-size needle entries need manual review")
    return problems


def pick_target(
    nodes: Mapping[str, DataNode],
    healthy: str,
    excluded: Iterable[str],
    leftovers: Mapping[str, Sequence[str]],
) -> str | None:
    anchor = nodes.get(healthy)
    if anchor is None:
        return None
    blocked = set(excluded)
    candidates = [
        node
        for node in nodes.values()
        if node.server not in blocked
        and node.free >= 1
        and not leftovers.get(node.server)
        and (node.data_center, node.rack) == (anchor.data_center, anchor.rack)
    ]
    candidates.sort(key=lambda node: (-node.free, node.server))
    return candidates[0].server if candidates else None


def decide(
    *,
    volume_id: int,
    replica_placement: str,
    copies: Sequence[CopyFacts],
    nodes: Mapping[str, DataNode],
    simulation: CheckDiskReport,
    fsck: FsckReport,
    stable: bool,
    leftovers: Mapping[str, Sequence[str]],
) -> Decision:
    """Choose `none`, `check-disk`, `copy` or `stop` for one volume.

    check-disk is the documented in-place repair; it is chosen only when nothing
    referenced is missing from the read-only copy and the sync has deletions to
    apply (otherwise check.disk flips the copy back to read-only). Anything the
    model cannot prove safe stops instead.
    """
    problems = _unsupported(copies)
    if len(copies) != copy_count(replica_placement):
        problems.append(f"expected {copy_count(replica_placement)} copies for placement {replica_placement}, found {len(copies)}")
    read_only = [copy for copy in copies if copy.read_only]
    writable = [copy for copy in copies if not copy.read_only]
    if not read_only:
        inconsistent = [f"{copy.server}: {copy.data.status}" for copy in copies if not copy.data.consistent]
        if problems or inconsistent:
            return _stop("no copy is read-only, but the volume needs manual review", [*problems, *inconsistent])
        return Decision("none", "every copy is writable and ends where its index says; nothing to repair")
    if len(read_only) != 1 or not writable:
        problems.append("the repair needs exactly one read-only copy and a writable peer")
    if problems:
        return _stop("the volume does not match the single read-only copy case", problems)

    damaged, healthy = read_only[0], writable[0]
    known = {"healthy": healthy.server, "damaged": damaged.server}
    if not stable:
        return _stop(
            "volume files changed while planning",
            ["fence writers and deleters of this collection, then plan again"],
            **known,
        )
    if damaged.info.read_only:
        problems.append(f"{damaged.server}: readOnly is persisted in .vif; this is not the integrity failure class")
    if not healthy.data.consistent:
        problems.append(f"{healthy.server}: the writable copy fails the startup check ({healthy.data.status})")
    if damaged.data.status != "unindexed-tail":
        problems.append(f"{damaged.server}: read-only cause is {damaged.data.status}, not an unindexed tail")
    problems += simulation.problems()
    problems += fsck.problems()
    for copy in (healthy, damaged):
        if (copy.server, volume_id) not in fsck.collected:
            problems.append(f"volume.fsck did not collect {copy.server}")
    states = {healthy.server: healthy.index, damaged.server: damaged.index}
    problems += cross_check(simulation, states, volume_id)
    for copy in (healthy, damaged):
        fsck_live = frozenset(k for k, e in copy.index.present.items() if e.size >= 0)
        stray = fsck.orphans_on(copy.server, volume_id) - fsck_live
        if stray:
            problems.append(f"{copy.server}: {len(stray)} fsck orphans are not live in the captured index")
    if problems:
        return _stop("the read-only copy cannot be repaired automatically", problems, **known)

    to_damaged = check_disk_diff(healthy.index, damaged.index)
    to_healthy = check_disk_diff(damaged.index, healthy.index)
    referenced = healthy.index.live - fsck.orphans_on(healthy.server, volume_id)
    referenced_damaged = damaged.index.live - fsck.orphans_on(damaged.server, volume_id)
    absent = to_damaged.absent
    missed_deletions = to_damaged.partially_deleted
    healthy_missed = to_healthy.partially_deleted
    unique = to_healthy.absent
    sets = {
        "referenced": referenced,
        "absent_on_damaged": absent,
        "damaged_missed_deletions": missed_deletions,
        "healthy_missed_deletions": healthy_missed,
        "unique_on_damaged": unique,
        "trailing": frozenset(needle.key for needle in damaged.data.trailing),
    }
    known["sets"] = sets
    known["referenced"] = referenced
    if unique & referenced_damaged:
        return _stop(
            "the read-only copy holds referenced needles its peer lacks",
            [f"{len(unique & referenced_damaged)} referenced needle(s) exist only on {damaged.server}"],
            **known,
        )

    copy_reasons: list[str] = []
    if absent & referenced:
        copy_reasons.append(f"{len(absent & referenced)} referenced needle(s) are missing from {damaged.server}")
    if healthy_missed & referenced:
        copy_reasons.append(f"{damaged.server} deleted {len(healthy_missed & referenced)} needle(s) the filer still references")
    if unique:
        copy_reasons.append(f"{damaged.server} holds {len(unique)} unreferenced needle(s) absent from {healthy.server}")
    if not missed_deletions:
        copy_reasons.append("no missed deletions to sync, so check.disk would leave the copy read-only")
    if not damaged.data.trailing_complete:
        copy_reasons.append("the unindexed tail is not a run of complete needles")
    if not any(
        (line.volume_id, line.source, line.target) == (volume_id, healthy.server, damaged.server)
        for line in simulation.sync
    ):
        copy_reasons.append("check.disk skipped the pair in simulation, so -fixReadOnly -apply would change nothing")

    if not copy_reasons:
        commands = planned_commands("check-disk", volume_id, healthy.server, damaged.server, None, bool(healthy_missed))
        steps = [
            Step(
                "fix-read-only",
                commands[0],
                {"writable": damaged.server, "deletes": [[healthy.server, damaged.server, len(missed_deletions)]]},
            )
        ]
        if healthy_missed:
            steps.append(
                Step(
                    "converge-deletions",
                    commands[1],
                    {"deletes": [[damaged.server, healthy.server, len(healthy_missed)], [healthy.server, damaged.server, 0]]},
                )
            )
        reasons = [
            "nothing the filer references is missing from the read-only copy",
            f"syncing {len(missed_deletions)} missed deletion(s) appends past the unindexed tail and makes it writable",
        ]
        if healthy_missed:
            reasons.append(
                f"{len(healthy_missed)} unreferenced needle(s) deleted only on {damaged.server} "
                f"are then deleted on {healthy.server}"
            )
        if absent:
            reasons.append(f"{len(absent)} unreferenced needle(s) stay absent on {damaged.server} (accepted divergence)")
        return Decision(
            "check-disk",
            f"repair {damaged.server} in place from {healthy.server}",
            tuple(reasons),
            steps=tuple(steps),
            accepted_divergence=absent,
            final_copies=tuple(sorted((healthy.server, damaged.server))),
            **known,
        )

    target = pick_target(nodes, healthy.server, (healthy.server, damaged.server), leftovers)
    if target is None:
        return _stop(
            "the repair needs a whole-volume copy but no third server has a free slot",
            [*copy_reasons, "free a slot (see the volume slot capacity guide) or raise maxVolumeCounts, then plan again"],
            **known,
        )
    final = tuple(sorted((healthy.server, target)))
    copy_command, _, delete_command = planned_commands("copy", volume_id, healthy.server, damaged.server, target, False)
    return Decision(
        "copy",
        f"copy {healthy.server} to {target}, verify it, then delete the copy on {damaged.server}",
        tuple(copy_reasons),
        target=target,
        steps=(
            Step("copy", copy_command, {"copies": sorted((healthy.server, damaged.server, target))}),
            Step("read-check", "", {"servers": list(final)}),
            Step("delete-damaged", delete_command, {"copies": list(final)}),
        ),
        final_copies=final,
        **known,
    )
