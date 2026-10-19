#!/usr/bin/env python3
"""Run real OTel/Loki restart checks locally; never accesses Kubernetes.

mise exec -- python3 scripts/verify-log-durability.py [--baseline-ref d6ffc31b]
Requires Docker and yq. Evidence is written to --output, outside the temp fixture.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[1]
MANIFEST = "kubernetes/apps/observability/otel-collector/app/helmrelease.yaml"
LOKI = "grafana/loki:3.7.8"
PYTHON = "docker.io/library/python:3.14-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72"


def run(*args: str) -> str:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stdout}")
    return result.stdout.strip()


def document(path: Path) -> dict:
    return json.loads(run("yq", "-o=json", ".", str(path)))


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value).replace("$${env:", "${env:"))


def get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode()


def eventually(check, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = check()
            if last:
                return last
        except (OSError, urllib.error.URLError) as exc:
            last = str(exc)
        time.sleep(0.25)
    raise AssertionError(f"Timed out waiting for condition; last result: {last}")


def local_config(values: dict, root: Path, loki_name: str) -> dict:
    config = copy.deepcopy(values["alternateConfig"])
    config["extensions"]["file_storage"]["directory"] = "/state"
    if "compaction" in config["extensions"]["file_storage"]:
        config["extensions"]["file_storage"]["compaction"]["directory"] = "/state"
    for receiver in config["receivers"].values():
        for field in ("include", "exclude"):
            if field in receiver:
                receiver[field] = [p.replace("/var/log/pods", "/fixture/pods") for p in receiver[field]]
    config["exporters"]["otlp_http/loki"]["endpoint"] = f"http://{loki_name}:3100/otlp"
    return config


def seed_config(values: dict, directory="/state", pods="/fixture/pods") -> dict:
    """Seed only the previously stateless general reader, using its exact ID."""
    general = copy.deepcopy(values["alternateConfig"]["receivers"]["file_log"])
    general.update(start_at="end", storage="file_storage")
    for field in ("include", "exclude"):
        general[field] = [p.replace("/var/log/pods", pods) for p in general.get(field, [])]
    return {
        "extensions": {"file_storage": {"directory": directory, "fsync": True}},
        "receivers": {"file_log": general},
        "exporters": {"debug": {"verbosity": "basic"}},
        "service": {"telemetry": {"logs": {"level": "debug"}}, "extensions": ["file_storage"], "pipelines": {"logs": {
            "receivers": ["file_log"], "exporters": ["debug"]}}},
    }


def seed_manifest(values: dict) -> dict:
    """Render a temporary, node-local migration; the caller owns preflight/apply/cleanup."""
    name = "otel-log-checkpoint-seed"
    config = seed_config(values, directory="/var/lib/otelcol", pods="/var/log/pods")
    labels = {"app.kubernetes.io/name": name}
    return {"apiVersion": "v1", "kind": "List", "items": [
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name, "namespace": "observability"},
         "data": {"config.json": json.dumps(config)}},
        {"apiVersion": "apps/v1", "kind": "DaemonSet", "metadata": {"name": name, "namespace": "observability"},
         "spec": {"selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": {
             "automountServiceAccountToken": False,
             "tolerations": values["tolerations"],
             "securityContext": {"runAsUser": 0, "runAsGroup": 0, "seccompProfile": {"type": "RuntimeDefault"}},
             "containers": [{"name": "seed", "image": values["image"]["repository"] + ":" + values["image"]["tag"],
                 "args": ["--config=/etc/seed/config.json", *values.get("command", {}).get("extraArgs", [])],
                 "resources": {"requests": {"cpu": "10m", "memory": "64Mi"}, "limits": {"cpu": "100m", "memory": "128Mi"}},
                 "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                 "volumeMounts": [{"name": "config", "mountPath": "/etc/seed", "readOnly": True},
                     {"name": "logs", "mountPath": "/var/log/pods", "readOnly": True},
                     {"name": "state", "mountPath": "/var/lib/otelcol"}]}],
             "volumes": [{"name": "config", "configMap": {"name": name}},
                         {"name": "logs", "hostPath": {"path": "/var/log/pods", "type": "Directory"}},
                         {"name": "state", "hostPath": {"path": "/var/lib/otelcol", "type": "Directory"}}],
         }}}},
    ]}


def exercise(values: dict, *, label: str, expect_loss: bool, backend_failure="disconnect", loki_image=LOKI) -> dict:
    nonce = uuid.uuid4().hex
    network, loki_name = f"anton-logs-{nonce}", f"loki-{nonce}"
    image = values["image"]["repository"] + ":" + values["image"]["tag"]
    containers = []
    writer_stop = threading.Event()
    ledger = []
    lock = threading.Lock()
    writer = None
    with tempfile.TemporaryDirectory(prefix="anton-log-durability-") as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        for name in ("state", "loki-data", "pods"):
            (root / name).mkdir(mode=0o777)
            (root / name).chmod(0o777)
        pod = root / "pods" / f"observability_ledger_{uuid.uuid4()}" / "ledger"
        pod.mkdir(parents=True)
        log = pod / "0.log"
        log.write_text("".join(
            f"{datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')} stdout F historical {n}\n"
            for n in range(30)))
        config = local_config(values, root, loki_name)
        save(root / "otel.json", config)
        save(root / "seed.json", seed_config(values))
        loki = {
            "auth_enabled": False,
            "server": {"http_listen_port": 3100},
            "common": {"path_prefix": "/data", "replication_factor": 1,
                       "ring": {"kvstore": {"store": "inmemory"}},
                       "storage": {"filesystem": {"chunks_directory": "/data/chunks", "rules_directory": "/data/rules"}}},
            "schema_config": {"configs": [{"from": "2024-01-01", "store": "tsdb", "object_store": "filesystem",
                "schema": "v13", "index": {"prefix": "index_", "period": "24h"}}]},
            "ingester": {"wal": {"enabled": True, "dir": "/data/wal", "flush_on_shutdown": True}},
            "limits_config": {"allow_structured_metadata": True},
        }
        save(root / "loki.json", loki)

        def append(seq: int, path: Path = log):
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            body = f"ledger run={nonce} seq={seq:06d}"
            with path.open("a") as stream:
                stream.write(f"{timestamp} stdout F {body}\n")
                stream.flush()
                os.fsync(stream.fileno())
            with lock:
                ledger.append(body)

        def write():
            seq = 0
            while not writer_stop.is_set():
                append(seq)
                seq += 1
                writer_stop.wait(0.04)

        def collected(needle=f"ledger run={nonce}") -> set[str]:
            query = '{k8s_namespace_name="observability",k8s_container_name="ledger"} |= ' + json.dumps(needle)
            params = urllib.parse.urlencode({"query": query, "since": "1h", "limit": 5000, "direction": "forward"})
            data = json.loads(get(loki_url + "/loki/api/v1/query_range?" + params))
            return {entry[1] for stream in data["data"]["result"] for entry in stream["values"]}

        def start_collector():
            ident = run("docker", "run", "-d", "--network", network, "--user", "0",
                        "--memory", "512m", "-e", "MY_POD_IP=0.0.0.0",
                        "-v", f"{root}:/fixture:ro", "-v", f"{root / 'state'}:/state",
                        "-p", "127.0.0.1::8888", image, "--config=/fixture/otel.json", *values.get("command", {}).get("extraArgs", []))
            containers.append(ident)
            port = run("docker", "port", ident, "8888/tcp").rsplit(":", 1)[1]
            def ready():
                if run("docker", "inspect", "-f", "{{.State.Running}}", ident) != "true":
                    raise RuntimeError(run("docker", "logs", ident))
                return get(f"http://127.0.0.1:{port}/metrics")
            eventually(ready)
            return ident, f"http://127.0.0.1:{port}/metrics"

        try:
            run("docker", "network", "create", network)
            platform = ["--platform", "linux/" + run("docker", "image", "inspect", loki_image, "--format", "{{.Architecture}}") ] if loki_image != LOKI else []
            lid = run("docker", "run", "-d", "--name", loki_name, "--network", network,
                      "-v", f"{root}:/fixture:ro", "-v", f"{root / 'loki-data'}:/data",
                      "-p", "127.0.0.1::3100", *platform, loki_image, "-config.file=/fixture/loki.json")
            containers.append(lid)
            port = run("docker", "port", lid, "3100/tcp").rsplit(":", 1)[1]
            loki_url = f"http://127.0.0.1:{port}"
            eventually(lambda: get(loki_url + "/ready"))
            if not expect_loss:
                # Rehearse both a fresh checkpoint and resuming a stale database.
                # Ready alone does not prove the first discovery poll has finished.
                for bootstrap in range(2):
                    if bootstrap:
                        with log.open("a") as stream:
                            stream.writelines(
                                f"{datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')} stdout F historical stale {n}\n"
                                for n in range(500))
                    seed = run("docker", "run", "-d", "--user", "0", "-v", f"{root}:/fixture:ro",
                               "-v", f"{root / 'state'}:/state", image, "--config=/fixture/seed.json", *values.get("command", {}).get("extraArgs", []))
                    containers.append(seed)
                    eventually(lambda: run("docker", "logs", seed).count('\tmatched files\t') >= 3)
                    run("docker", "stop", "--time", "10", seed)
            writer = threading.Thread(target=write)
            writer.start()
            cid, metrics_url = start_collector()
            eventually(lambda: len(collected()) >= 25)
            assert not collected("historical "), "Bootstrap replayed pre-seed history"
            print(f"{label}: collecting; stopping Loki while the ledger continues", flush=True)
            print(f"{label}: before Loki stop, written={len(ledger)}", flush=True)
            run("docker", "stop", "--time", "30", lid)
            assert run("docker", "inspect", "-f", "{{.State.ExitCode}}", lid) == "0", "Loki did not stop gracefully"
            print(f"{label}: Loki stopped, written={len(ledger)}", flush=True)
            unavailable = None
            if backend_failure == "http503":
                server = "from http.server import HTTPServer,BaseHTTPRequestHandler\nclass Handler(BaseHTTPRequestHandler):\n def do_POST(self):\n  self.rfile.read(int(self.headers.get('Content-Length',0)))\n  self.send_response(503);self.end_headers();self.wfile.write(b'at least 1 live replicas required, could only find 0')\n def log_message(self,*args):pass\nHTTPServer(('0.0.0.0',3100),Handler).serve_forever()"
                unavailable = run("docker", "run", "-d", "--network", network, "--network-alias", loki_name,
                                  PYTHON, "python3", "-u", "-c", server).splitlines()[-1]
                containers.append(unavailable)
                time.sleep(1)

            eventually(lambda: any(
                line.startswith("otelcol_exporter_queue_size{") and float(line.rsplit(" ", 1)[1]) > 0
                for line in get(metrics_url).splitlines()))
            time.sleep(1)
            run("docker", "kill", cid)
            time.sleep(1)
            # A new file appears while no reader exists: it must start at beginning.
            newfile = pod / "1.log"
            for seq in range(100000, 100010):
                append(seq, newfile)
            cid, metrics_url = start_collector()
            time.sleep(1)
            run("docker", "kill", cid)
            time.sleep(1)
            cid, metrics_url = start_collector()
            time.sleep(1)
            run("docker", "stop", "--time", "30", cid)
            assert run("docker", "inspect", "-f", "{{.State.ExitCode}}", cid) == "0", "Collector did not stop gracefully"
            cid, metrics_url = start_collector()
            if unavailable:
                run("docker", "stop", "--time", "5", unavailable)
            run("docker", "start", lid)
            port = run("docker", "port", lid, "3100/tcp").rsplit(":", 1)[1]
            loki_url = f"http://127.0.0.1:{port}"
            eventually(lambda: get(loki_url + "/ready"))
            time.sleep(1)
            writer_stop.set()
            writer.join()
            expected = set(ledger)
            if expect_loss:
                time.sleep(5)
            else:
                try:
                    eventually(lambda: expected <= collected())
                except AssertionError:
                    print(json.dumps({"written": len(expected), "missing": sorted(expected - collected())}), flush=True)
                    print(get(metrics_url), flush=True)
                    raise
            actual = collected()
            shutdown_reports = []
            for ident in containers:
                for line in run("docker", "logs", ident).splitlines():
                    if "Exporting failed. Dropping data." in line:
                        fields = json.loads(line[line.find("{"):])
                        shutdown_reports.append({"error": fields.get("error"), "dropped_items": fields.get("dropped_items")})
            if backend_failure == "http503" and not expect_loss:
                assert shutdown_reports, "HTTP503 shutdown reproduction emitted no drop messages"
                assert all("interrupted due to shutdown" in item["error"] and "503" in item["error"]
                           for item in shutdown_reports), shutdown_reports
            missing = sorted(expected - actual)
            if expect_loss:
                assert missing, "Baseline unexpectedly preserved everything; reproduction is not discriminating"
            else:
                assert not missing, missing
            result = {"case": label, "written_records": len(expected), "queryable_records": len(expected & actual),
                      "missing_records": len(missing), "missing_record_ids": missing,
                      "collector_sigkills": 2, "collector_graceful_restarts": 1, "loki_graceful_restarts": 1,
                      "loki_image": loki_image, "backend_failure": backend_failure, "shutdown_reports": shutdown_reports, "new_file_during_outage": True, "bootstrap_offsets_seeded": not expect_loss, "stale_bootstrap_rehearsed": not expect_loss}
            print(json.dumps({k: v for k, v in result.items() if k != "missing_record_ids"}), flush=True)
            return result
        except Exception:
            for ident in containers:
                print(run("docker", "logs", "--tail", "15", ident), flush=True)
            raise
        finally:
            writer_stop.set()
            if writer is not None:
                writer.join()
            for ident in reversed(containers):
                run("docker", "rm", "-f", ident)
            run("docker", "network", "rm", network)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--loki-image", help="Immutable local candidate image ID or published digest")
    parser.add_argument("--backend-failure", choices=["disconnect", "http503"], default="disconnect")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--render-seed", type=Path, help="Only render the temporary first-rollout seed manifest; never apply it")
    args = parser.parse_args()
    if args.loki_image and not re.fullmatch(r"(?:sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64})", args.loki_image):
        parser.error("--loki-image requires an immutable image ID or digest")
    if args.render_seed:
        args.render_seed.write_text(json.dumps(seed_manifest(document(REPO / MANIFEST)["spec"]["values"]), indent=2) + "\n")
        return
    results = []
    if args.baseline_ref:
        baseline = run("git", "-C", str(REPO), "show", f"{args.baseline_ref}:{MANIFEST}")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.yaml"
            path.write_text(baseline)
            results.append(exercise(document(path)["spec"]["values"], label="baseline", expect_loss=True, backend_failure=args.backend_failure, loki_image=args.loki_image or LOKI))
    results.append(exercise(document(REPO / MANIFEST)["spec"]["values"], label="persistent", expect_loss=False, backend_failure=args.backend_failure, loki_image=args.loki_image or LOKI))
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + "\n")
    print("Log durability checks passed; local containers and network removed")


if __name__ == "__main__":
    main()
