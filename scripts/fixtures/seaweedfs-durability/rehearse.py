#!/usr/bin/env python3
"""Local amd64 mixed-version upgrade, rollback, and re-upgrade qualification."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("durability", Path(__file__).with_name("benchmark.py"))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
m = b.m
STOCK = "chrislusf/seaweedfs:4.48@sha256:aba492e2a4e4c90bff795745e8e660affa1f09e7650f5981bd7bccd1a06cd931"


class Rehearsal(b.Comparison):
    def __init__(self, directory, image):
        super().__init__(directory, "full")
        self.roles = ["master", "master-b", "master-c", "volume", "volume-b",
                      "volume-c", "filer", "filer-b", "s3", "s3-b"]
        self.ha = True
        self.versions = dict.fromkeys(self.roles, "stock")
        self.named = set()
        m.IMAGES.update(stock=STOCK, durable=image)

    def record(self, event, **values):
        if event == "identity":
            values.update(architecture="SeaweedFS linux/amd64 under local emulation",
                          storage="disposable Docker named volumes", production=False)
        return m.Lab.record(self, event, **values)

    def wrapped_docker(self, *args, **kwargs):
        a = list(args)
        if a and a[0] == "run" and "--name" in a:
            name = a[a.index("--name") + 1]
            role = name.removeprefix(self.name + "-")
            if role in self.roles:
                a = [v.replace("-defaultReplication=000", "-defaultReplication=001")
                     .replace("-volumeSizeLimitMB=64", "-volumeSizeLimitMB=512") for v in a]
                index = a.index("--entrypoint")
                a[index:index] = ["-e", "WEED_MASTER_VOLUME_GROWTH_COPY_2=1"]
                if not role.startswith("s3"):
                    vi = a.index("-v")
                    volume = name + "-data"
                    if volume not in self.named:
                        b.ORIGINAL_DOCKER("volume", "create", "--label", "anton.durability=true", volume)
                        self.named.add(volume)
                    a[vi + 1] = volume + ":/data"
                if role.startswith("volume"):
                    a[index:index] = ["-p", "127.0.0.1::8080"]
                if role.startswith("filer"):
                    cfg = self.directory / (role + ".toml")
                    cfg.write_text('[leveldb2]\nenabled=true\ndir="/data/filerldb2"\nsync=true\n')
                    index = a.index("--entrypoint")
                    a[index:index] = ["-v", str(cfg) + ":/etc/seaweedfs/filer.toml:ro"]
        return b.ORIGINAL_DOCKER(*a, **kwargs)

    def placement(self):
        copies = {}
        for role in [r for r in self.roles if r.startswith("volume")]:
            port = b.ORIGINAL_DOCKER("port", self.name + "-" + role, "8080/tcp")
            status, body, _ = b.http("GET", "http://" + port + "/status")
            assert status == 200
            for volume in json.loads(body)["Volumes"] or []:
                assert 1 + sum(volume["ReplicaPlacement"].values()) == 2
                assert not volume["ReadOnly"]
                copies.setdefault(str(volume["Id"]), []).append(role)
        assert copies and all(len(set(v)) == 2 for v in copies.values()), copies
        self.record("two_copy_placement_verified", copies=copies)
        return copies

    def transition(self, version):
        for role in [r for prefix in ["volume", "filer", "s3", "master"]
                     for r in self.roles if r.startswith(prefix)]:
            self.verify_quorum()
            self.record("transition", role=role, target=version)
            self.stop(role)
            self.versions[role] = version
            self.launch(role)
            self.verify()
            self.put("written-" + version + "-" + role,
                     hashlib.shake_256((version + role).encode()).digest(131072))
        self.multipart("multipart-" + version)
        self.verify()
        self.placement()


def application_check(lab, name):
    lab.start_loki()
    report = {"harbor": b.registry_work(lab), "loki": b.loki_work(lab)}
    lab.stop("loki")
    status, body, _ = lab.request("GET", "/loki?list-type=2")
    assert status == 200
    keys = [e.text for e in ET.fromstring(body).iter() if e.tag.endswith("}Key")]
    assert any(k.startswith("index/") for k in keys)
    report["cold_loki"] = b.cold_loki(lab, report["loki"])
    lab.stop("loki")
    report["placement"] = lab.placement()
    (lab.directory / (name + "-applications.json")).write_text(json.dumps(report, indent=2) + "\n")
    lab.record("applications_verified", stage=name, records=8000,
               cold_records=report["cold_loki"]["records"], registry_bytes=68 * 1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", required=True, help="immutable local amd64 image ID")
    args = parser.parse_args()
    assert args.image.startswith("sha256:") and len(args.image) == 71
    info = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image]))[0]
    assert info["Architecture"] == "amd64" and info["Os"] == "linux"
    assert not args.output.exists(), "refuse existing evidence"
    lab = Rehearsal(args.output.resolve(), args.image)
    try:
        lab.start()
        lab.seed()
        lab.start_registry()
        application_check(lab, "baseline")
        for name, version in [("upgrade", "durable"), ("rollback", "stock"), ("reupgrade", "durable")]:
            lab.transition(version)
            application_check(lab, name)
        lab.record("qualification_passed", stages=["baseline", "upgrade", "rollback", "reupgrade"])
    finally:
        lab.cleanup()


if __name__ == "__main__":
    main()
