#!/usr/bin/env python3
"""Local-only SeaweedFS durability comparison through Harbor Registry and Loki."""

import argparse, datetime, hashlib, importlib.util, json, math, re, statistics, subprocess, time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "swlab", ROOT / "scripts/fixtures/seaweedfs-qualification/run.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ORIGINAL_DOCKER = m.docker
HARBOR = "goharbor/registry-photon@sha256:c4ebef61ceb50a3d8bc21d149bc280422db20a1e69df317b64b74098c3615855"
LOKI = "sha256:fff3104ee2effa83031d1bb75363f346e4af0af5202036e590648da680fdb082"
IMAGES = {
    "baseline": "localhost/anton/seaweedfs:durability-baseline",
    "candidate": "localhost/anton/seaweedfs:durability-candidate",
}
CASES = {
    "baseline": ("baseline", False, False),
    "data-only": ("baseline", True, False),
    "data-index": ("candidate", True, False),
    "full": ("candidate", True, True),
}
opener = build_opener(ProxyHandler({}))


def http(method, url, data=None, headers=None, timeout=90):
    try:
        with opener.open(
            Request(url, data=data, headers=headers or {}, method=method),
            timeout=timeout,
        ) as r:
            return r.status, r.read(), dict(r.headers)
    except HTTPError as r:
        return r.code, r.read(), dict(r.headers)


def elapsed(fn):
    start = time.perf_counter()
    value = fn()
    return time.perf_counter() - start, value


def percentile(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(p * len(s)) - 1)]


def metric(text, name):
    return sum(
        float(line.split()[-1])
        for line in text.splitlines()
        if line.startswith(name + "{") or line.startswith(name + " ")
    )


class Comparison(m.Lab):
    def __init__(self, directory, case, profile=False):
        version, self.fsync, self.metadata = CASES[case]
        m.IMAGES.update(IMAGES)
        super().__init__(directory, version, "dns")
        self.roles = ["master", "volume", "volume-b", "volume-c", "filer", "s3"]
        self.versions = {r: version for r in self.roles}
        self.named = []
        self.profile = profile
        self.apps = {}

    def record(self, event, **values):
        if event == "identity":
            values.update(
                architecture="linux/arm64",
                harbor_architecture="linux/amd64 emulated",
                storage="Docker named volumes; no Longhorn",
            )
        return super().record(event, **values)

    def wrapped_docker(self, *args, **kwargs):
        a = list(args)
        if (
            a
            and a[0] == "run"
            and "--name" in a
            and a[a.index("--name") + 1].startswith(self.name)
        ):
            a[a.index("--platform") + 1] = "linux/arm64"
            a = [
                x.replace("-defaultReplication=000", "-defaultReplication=001").replace(
                    "-volumeSizeLimitMB=64", "-volumeSizeLimitMB=512"
                )
                for x in a
            ]
            idx = a.index("--entrypoint")
            a[idx:idx] = ["-e", "WEED_MASTER_VOLUME_GROWTH_COPY_2=1"]
            role = a[a.index("--name") + 1][len(self.name) + 1 :]
            if role.startswith("volume") or role == "filer":
                vi = a.index("-v")
                volume = self.name + "-" + role + "-data"
                ORIGINAL_DOCKER(
                    "volume", "create", "--label", "anton.durability=true", volume
                )
                self.named.append(volume)
                a[vi + 1] = volume + ":/data"
            if role == "filer":
                cfg = self.directory / "filer.toml"
                cfg.write_text(
                    '[leveldb2]\nenabled = true\ndir = "/data/filerldb2"\nsync = '
                    + str(self.metadata).lower()
                    + "\n"
                )
                idx = a.index("--entrypoint")
                a[idx:idx] = ["-v", str(cfg) + ":/etc/seaweedfs/filer.toml:ro"]
            if self.profile and (role.startswith("volume") or role == "filer"):
                idx = a.index("--entrypoint")
                a[idx + 1] = "/usr/bin/strace"
                a[idx:idx] = [
                    "--cap-add=SYS_PTRACE",
                    "--security-opt",
                    "seccomp=unconfined",
                ]
                imageidx = a.index(IMAGES[self.version])
                a[imageidx + 1 : imageidx + 1] = [
                    "-f",
                    "-tt",
                    "-T",
                    "-e",
                    "trace=fsync,fdatasync",
                    "-o",
                    "/data/fsync.trace",
                    "/usr/local/bin/weed",
                ]
        return ORIGINAL_DOCKER(*a, **kwargs)

    def start(self):
        m.docker = self.wrapped_docker
        super().start()
        for bucket in ["harbor", "loki"]:
            assert self.request("PUT", "/" + bucket)[0] == 200
        if self.fsync:
            commands = "".join(
                f"fs.configure -locationPrefix=/buckets/{b}/ -fsync -replication=001 -apply\n"
                for b in ["harbor", "loki"]
            )
            r = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    self.name + "-master",
                    "weed",
                    "shell",
                    "-master=master:9333",
                    "-filer=filer:8888",
                ],
                input=commands,
                capture_output=True,
                text=True,
                timeout=60,
            )
            (self.directory / "policy.log").write_text(r.stdout + r.stderr)
            assert r.returncode == 0
            decoder = json.JSONDecoder()
            text = r.stdout.strip()
            docs = []
            while text:
                doc, end = decoder.raw_decode(text)
                docs.append(doc)
                text = text[end:].strip()
            assert {
                x["locationPrefix"]
                for x in docs[-1]["locations"]
                if x["fsync"] and x["replication"] == "001"
            } == {"/buckets/harbor/", "/buckets/loki/"}
        for bucket in ["harbor", "loki"]:
            for i in range(2):
                payload = hashlib.shake_256(str(i).encode()).digest(65536)
                assert self.request("PUT", f"/{bucket}/warm-{i}", payload)[0] == 200
                assert self.request("GET", f"/{bucket}/warm-{i}")[1] == payload

    def app(
        self,
        name,
        image,
        args,
        config,
        configpath,
        port,
        entrypoint=None,
        platform="linux/arm64",
    ):
        cfg = self.directory / (name + ".config")
        cfg.write_text(config)
        a = [
            "run",
            "-d",
            "--platform",
            platform,
            "--name",
            self.name + "-" + name,
            "--network",
            self.name,
            "--network-alias",
            name,
            "--label",
            "anton.durability=true",
            "--cpus",
            "2",
            "--memory",
            "768m",
            "-p",
            f"127.0.0.1::{port}",
            "-v",
            str(cfg) + ":" + configpath + ":ro",
        ]
        if name == "loki":
            a += ["--user", "0"]
        if entrypoint:
            a += ["--entrypoint", entrypoint]
        ORIGINAL_DOCKER(*a, image, *args)
        self.active.add(name)
        binding = ORIGINAL_DOCKER("port", self.name + "-" + name, str(port) + "/tcp")
        assert binding.startswith("127.0.0.1:")
        self.apps[name] = "http://" + binding

    def start_registry(self):
        config = """version: 0.1
log:
  level: error
storage:
  s3:
    accesskey: qualification
    secretkey: local-test-only
    region: us-east-1
    regionendpoint: http://s3:8333
    bucket: harbor
    secure: false
    v4auth: true
    chunksize: 5242880
  redirect:
    disable: true
  delete:
    enabled: true
http:
  addr: :5000
"""
        self.app(
            "registry",
            HARBOR,
            ["serve", "/etc/registry/config.yml"],
            config,
            "/etc/registry/config.yml",
            5000,
            "/usr/bin/registry_DO_NOT_USE_GC",
            "linux/amd64",
        )
        self.wait(lambda: http("GET", self.apps["registry"] + "/v2/")[0] == 200)

    def start_loki(self):
        config = """auth_enabled: false
server:
  http_listen_port: 3100
  grpc_listen_port: 9095
  log_level: warn
common:
  instance_addr: 127.0.0.1
  path_prefix: /tmp/loki
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: s3
      schema: v13
      index:
        prefix: loki_index_
        period: 24h
storage_config:
  aws:
    endpoint: s3:8333
    region: us-east-1
    bucketnames: loki
    access_key_id: qualification
    secret_access_key: local-test-only
    s3forcepathstyle: true
    insecure: true
  tsdb_shipper:
    active_index_directory: /tmp/loki/tsdb-active
    cache_location: /tmp/loki/tsdb-cache
    resync_interval: 5s
ingester:
  wal:
    enabled: true
    dir: /tmp/loki/wal
  chunk_idle_period: 5s
  max_chunk_age: 10s
  flush_check_period: 1s
  chunk_target_size: 262144
  chunk_encoding: snappy
limits_config:
  ingestion_rate_mb: 64
  ingestion_burst_size_mb: 128
  allow_structured_metadata: true
analytics:
  reporting_enabled: false
"""
        self.app(
            "loki",
            LOKI,
            ["-config.file=/etc/loki/local.yaml"],
            config,
            "/etc/loki/local.yaml",
            3100,
        )
        self.wait(lambda: http("GET", self.apps["loki"] + "/ready")[0] == 200)

    def trace_snapshot(self):
        if not self.profile:
            return {}
        result = {}
        for role in ["volume", "volume-b", "volume-c", "filer"]:
            raw = ORIGINAL_DOCKER(
                "exec",
                self.name + "-" + role,
                "python3",
                "-c",
                'from pathlib import Path; p=Path("/data/fsync.trace"); print(p.read_text() if p.exists() else "")',
            )
            result[role] = raw
        return result

    def cleanup(self):
        try:
            self.final_traces = self.trace_snapshot()
            super().cleanup()
        finally:
            for volume in self.named:
                ORIGINAL_DOCKER("volume", "rm", volume)
            m.docker = ORIGINAL_DOCKER


def registry_work(lab):
    url = lab.apps["registry"]
    repo = "/v2/qualification/image"
    samples = []
    get_samples = []
    bytes_total = 0
    hashes = []
    sizes = []
    for i in range(6):
        payload = hashlib.shake_256(f"harbor-layer-{i}".encode()).digest(
            (48 if i == 0 else 4) * 1024 * 1024
        )
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()

        def upload():
            status, _, h = http("POST", url + repo + "/blobs/uploads/", b"")
            assert status == 202, (status, h)
            loc = h.get("Location") or h.get("location")
            target = url + urlsplit(loc).path
            if urlsplit(loc).query:
                target += "?" + urlsplit(loc).query
            target += ("&" if "?" in target else "?") + urlencode({"digest": digest})
            status, body, _ = http(
                "PUT", target, payload, {"Content-Type": "application/octet-stream"}
            )
            assert status == 201, (status, body[:500])

        duration, _ = elapsed(upload)
        samples.append(duration)
        duration, r = elapsed(lambda: http("GET", url + repo + "/blobs/" + digest))
        assert r[0] == 200 and hashlib.sha256(r[1]).hexdigest() == digest[7:]
        get_samples.append(duration)
        bytes_total += len(payload)
        hashes.append(digest)
        sizes.append(len(payload))
    # Exercise the manifest path independently of blob bodies.
    config = b"{}"
    digest = "sha256:" + hashlib.sha256(config).hexdigest()
    status, _, h = http("POST", url + repo + "/blobs/uploads/", b"")
    assert status == 202
    loc = urlsplit(h.get("Location") or h.get("location"))
    target = (
        url
        + loc.path
        + "?"
        + loc.query
        + ("&" if loc.query else "")
        + urlencode({"digest": digest})
    )
    status, body, _ = http(
        "PUT", target, config, {"Content-Type": "application/octet-stream"}
    )
    assert status == 201, (status, body[:500])
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": digest,
            "size": 2,
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": h,
                "size": n,
            }
            for h, n in zip(hashes, sizes)
        ],
    }
    body = json.dumps(manifest).encode()
    status, r, _ = http(
        "PUT",
        url + repo + "/manifests/test",
        body,
        {"Content-Type": manifest["mediaType"]},
    )
    assert status == 201, (status, r)
    status, r, _ = http(
        "GET", url + repo + "/manifests/test", headers={"Accept": manifest["mediaType"]}
    )
    assert status == 200 and json.loads(r) == manifest
    return {
        "put_seconds": samples,
        "get_seconds": get_samples,
        "verified_layer_bytes": bytes_total,
        "layer_hashes": hashes,
        "manifest_verified": True,
    }


def loki_work(lab):
    url = lab.apps["loki"]
    push = []
    start = time.time_ns() - 10_000_000_000
    expected = {}
    batch_size = 1000
    payload_lines = 20
    # Multiple streams produce multiple independently flushed chunks.
    for stream in range(8):
        values = []
        for seq in range(batch_size):
            line = json.dumps(
                {
                    "stream": stream,
                    "seq": seq,
                    "payload": hashlib.shake_256(f"{stream}-{seq}".encode()).hexdigest(
                        payload_lines * 16
                    ),
                }
            )
            values.append([str(start + seq * 1000000), line])
            expected[(stream, seq)] = line
        body = json.dumps(
            {
                "streams": [
                    {
                        "stream": {
                            "qualification": "durability",
                            "stream_id": str(stream),
                        },
                        "values": values,
                    }
                ]
            }
        ).encode()
        duration, r = elapsed(
            lambda: http(
                "POST",
                url + "/loki/api/v1/push",
                body,
                {"Content-Type": "application/json"},
            )
        )
        assert r[0] == 204, (r[0], r[1][:500])
        push.append(duration)
    t = time.perf_counter()
    assert http("POST", url + "/flush", b"")[0] in [200, 204]

    def flushed():
        status, body, _ = http("GET", url + "/metrics")
        assert status == 200
        text = body.decode()
        return (
            metric(text, "loki_ingester_chunks_stored_total")
            >= metric(text, "loki_ingester_chunks_created_total")
            >= 8
            and metric(text, "loki_ingester_flush_queue_length") == 0
        )

    deadline = time.monotonic() + 90
    while not flushed():
        assert time.monotonic() < deadline, "Loki flush exceeded 90 seconds"
        time.sleep(0.02)
    flush = time.perf_counter() - t
    rows = []
    received = {}
    query_stats = []
    for stream in range(8):
        params = urlencode(
            {
                "query": '{qualification="durability",stream_id="' + str(stream) + '"}',
                "start": start - 1,
                "end": start + batch_size * 1000000,
                "limit": 2000,
                "direction": "forward",
            }
        )
        status, body, _ = http("GET", url + "/loki/api/v1/query_range?" + params)
        assert status == 200, body[:500]
        r = json.loads(body)
        values = [v[1] for s in r["data"]["result"] for v in s["values"]]
        rows.extend(values)
        query_stats.append(r["data"].get("stats"))
        for line in values:
            value = json.loads(line)
            key = (value["stream"], value["seq"])
            assert key not in received
            received[key] = line
    assert received == expected
    metrics = http("GET", url + "/metrics")[1].decode()
    assert metric(metrics, "loki_ingester_chunks_flush_failures_total") == 0
    # Both chunks and TSDB index writes must be represented in S3, not only memory queries.
    status, objects, _ = lab.request("GET", "/loki?list-type=2")
    assert status == 200
    (lab.directory / "loki-object-list.xml").write_bytes(objects)
    (lab.directory / "loki-metrics.txt").write_text(metrics)
    s3_time = sum(
        float(line.split()[-1])
        for line in metrics.splitlines()
        if line.startswith("loki_s3_request_duration_seconds_sum{")
        and 'operation="S3.PutObject"' in line
    )
    s3_count = sum(
        float(line.split()[-1])
        for line in metrics.splitlines()
        if line.startswith("loki_s3_request_duration_seconds_count{")
        and 'operation="S3.PutObject"' in line
    )
    return {
        "start_ns": start,
        "end_ns": start + batch_size * 1000000,
        "s3_put_seconds_sum": s3_time,
        "s3_put_count": s3_count,
        "push_seconds": push,
        "flush_seconds": flush,
        "verified_records": len(rows),
        "chunks_stored": metric(metrics, "loki_ingester_chunks_stored_total"),
        "store_bytes": metric(metrics, "loki_ingester_chunk_stored_bytes_total"),
        "query_stats": query_stats,
    }


def verify_native_copies(lab):
    copies = {}
    for role in ["volume", "volume-b", "volume-c"]:
        status = json.loads(
            ORIGINAL_DOCKER(
                "exec",
                lab.name + "-" + role,
                "python3",
                "-c",
                "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/status').read().decode())",
            )
        )
        for volume in status["Volumes"] or []:
            assert 1 + sum(volume["ReplicaPlacement"].values()) == 2
            copies.setdefault(str(volume["Id"]), []).append(role)
    assert copies and all(
        len(owners) == len(set(owners)) == 2 for owners in copies.values()
    )
    return copies


def cold_loki(lab, state):
    lab.start_loki()
    lab.record("cold_loki_reader_started", empty_container_filesystem=True)
    received = {}
    stats = []
    for stream in range(8):
        params = urlencode(
            {
                "query": '{qualification="durability",stream_id="' + str(stream) + '"}',
                "start": state["start_ns"] - 1,
                "end": state["end_ns"],
                "limit": 2000,
                "direction": "forward",
            }
        )
        status, body, _ = http(
            "GET", lab.apps["loki"] + "/loki/api/v1/query_range?" + params
        )
        assert status == 200, body[:500]
        result = json.loads(body)
        stats.append(result["data"].get("stats"))
        for series in result["data"]["result"]:
            for _, line in series["values"]:
                value = json.loads(line)
                key = (value["stream"], value["seq"])
                assert key not in received
                assert value["payload"] == hashlib.shake_256(
                    f"{key[0]}-{key[1]}".encode()
                ).hexdigest(320)
                received[key] = line
    assert set(received) == {
        (stream, seq) for stream in range(8) for seq in range(1000)
    }
    downloaded = sum(
        x.get("querier", {}).get("store", {}).get("totalChunksDownloaded", 0)
        + x.get("ingester", {}).get("store", {}).get("totalChunksDownloaded", 0)
        for x in stats
    )
    assert downloaded > 0
    return {"records": len(received), "chunks_downloaded": downloaded, "stats": stats}


def run_one(output, case, profile=False, cold=False):
    lab = Comparison(output, case, profile)
    before = {}
    report = {}
    try:
        lab.start()
        lab.start_registry()
        lab.start_loki()
        before = lab.trace_snapshot()
        report["harbor"] = registry_work(lab)
        report["loki"] = loki_work(lab)
        report["docker_stats"] = ORIGINAL_DOCKER(
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *[lab.name + "-" + r for r in lab.roles + ["registry", "loki"]],
        )
        report.update(
            case=case,
            profile=profile,
            images={
                r: json.loads(ORIGINAL_DOCKER("inspect", lab.name + "-" + r))[0][
                    "Image"
                ]
                for r in lab.roles + ["registry", "loki"]
            },
        )
        duration, _ = elapsed(lambda: lab.stop("loki"))
        report["loki"]["shutdown_seconds"] = duration
        state = json.loads(next(lab.directory.glob("*-loki-exit.json")).read_text())
        assert state["exitCode"] == 0 and not state["oomKilled"], state
        import xml.etree.ElementTree as ET

        status, objects, _ = lab.request("GET", "/loki?list-type=2")
        assert status == 200
        keys = [e.text for e in ET.fromstring(objects).iter() if e.tag.endswith("}Key")]
        index_keys = [k for k in keys if k.startswith("index/")]
        assert index_keys, keys
        report["loki"]["index_objects_verified"] = []
        for key in index_keys:
            status, data, _ = lab.request("GET", "/loki/" + key)
            assert status == 200 and len(data) > 0
            report["loki"]["index_objects_verified"].append(
                {
                    "key": key,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        (lab.directory / "loki-final-object-list.xml").write_bytes(objects)
        report["native_two_copy_placement"] = verify_native_copies(lab)
        if cold:
            report["cold_loki"] = cold_loki(lab, report["loki"])
    finally:
        lab.cleanup()
    if profile:
        report["sync_profile"] = {}
        for role, trace in lab.final_traces.items():
            new = trace[len(before.get(role, "")) :]
            (output / (role + "-sync.trace")).write_text(new)
            times = [float(t) for t in re.findall(r"<([\d.]+)>", new)]
            report["sync_profile"][role] = {
                "calls": len(times),
                "seconds": sum(times),
                "max_seconds": max(times, default=0),
            }
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--case", choices=CASES)
    p.add_argument("--profile", action="store_true")
    p.add_argument("--cold", action="store_true")
    a = p.parse_args()
    assert not a.output.exists()
    a.output.mkdir(parents=True)
    results = []
    cases = list(CASES) if a.case is None else [a.case]
    for round_no in range(a.rounds):
        for case in cases if round_no % 2 == 0 else list(reversed(cases)):
            r = run_one(a.output / f"{round_no:02d}-{case}", case, a.profile, a.cold)
            results.append(r)
            (a.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "round": round_no,
                        "case": case,
                        "harbor_put_p50": statistics.median(r["harbor"]["put_seconds"]),
                        "loki_flush": r["loki"]["flush_seconds"],
                        "records": r["loki"]["verified_records"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
