"""Source contract: 00-multus.conf is the only CNI config containerd loads.

Talos mounts /etc/cni as tmpfs and Multus deletes 00-multus.conf when it exits.
On 2026-10-22 Cilium's config in /etc/cni/net.d let pods start without Multus
after every boot, and a Longhorn instance manager came up without lhnet1.
"""

import json
from pathlib import Path
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[2]
CILIUM = REPO / "kubernetes/apps/kube-system/cilium/app/helmrelease.yaml"
MULTUS = REPO / "kubernetes/apps/network/multus/app/flux-kustomization.yaml"
CONTAINERD_DIR = "/etc/cni/net.d"


def yaml_to_json(text):
    return json.loads(subprocess.check_output(["yq", "-o=json", "."], input=text, text=True))


def multus_patches(kind, name):
    kustomization = yaml_to_json(MULTUS.read_text())
    return [yaml_to_json(entry["patch"]) for entry in kustomization["spec"]["patches"]
            if entry["target"].get("kind") == kind and entry["target"].get("name") == name]


def daemon_config():
    for patch in multus_patches("ConfigMap", "multus-daemon-config"):
        for op in patch:
            if op["path"] == "/data/daemon-config.json":
                return json.loads(op["value"])
    raise AssertionError("multus-daemon-config patch no longer sets daemon-config.json")


def added_init_containers():
    return {op["value"]["name"]: op["value"]
            for patch in multus_patches("DaemonSet", "kube-multus-ds") if isinstance(patch, list)
            for op in patch if op.get("path") == "/spec/template/spec/initContainers/-"}


class CniLayoutTests(unittest.TestCase):
    def setUp(self):
        self.cilium = yaml_to_json(CILIUM.read_text())["spec"]["values"]["cni"]
        self.multus = daemon_config()

    def test_cilium_config_is_outside_the_containerd_directory(self):
        self.assertFalse(self.cilium["exclusive"])
        self.assertNotEqual(self.cilium["confPath"].rstrip("/"), CONTAINERD_DIR)

    def test_multus_delegates_to_the_cilium_directory_and_owns_net_d(self):
        # multus-conf-dir mounts the host directory at the same path in the
        # container, so Multus's container path must equal Cilium's host path.
        self.assertEqual(self.multus["multusAutoconfigDir"].rstrip("/"), self.cilium["confPath"].rstrip("/"))
        self.assertEqual(self.multus["cniConfigDir"], "/host" + CONTAINERD_DIR)
        self.assertEqual(self.multus["multusConfigFile"], "auto")

    def test_a_cilium_config_left_in_net_d_is_removed_before_multus_starts(self):
        cleanup = added_init_containers()["remove-direct-cilium-config"]
        mounts = {mount["name"]: mount["mountPath"] for mount in cleanup["volumeMounts"]}
        self.assertEqual(mounts["multus-conf-dir"].rstrip("/"), self.cilium["confPath"].rstrip("/"))
        self.assertEqual(mounts["cni"], "/host" + CONTAINERD_DIR)
        script = cleanup["command"][-1]
        self.assertIn("rm -f /host/etc/cni/net.d/05-cilium.conflist", script)
        self.assertIn(self.cilium["confPath"].rstrip("/") + "/05-cilium.conflist", script)


if __name__ == "__main__":
    unittest.main()
