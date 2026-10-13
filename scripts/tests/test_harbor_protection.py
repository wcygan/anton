"""Protect controller history and reject ambiguous runtime/storage evidence."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from harbor_fixture import filer_data

APP = Path(__file__).resolve().parents[2] / 'kubernetes/apps/registries/harbor-config/app'


class HarborProtection(unittest.TestCase):
    def jq(self, script, data):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / script
            p.write_text((APP / script).read_text().replace('$$', '$'))
            return subprocess.run(['jq', '--arg', 'host', 'registry', '-f', str(p)],
                                  input=json.dumps(data), capture_output=True, text=True)

    def inventory(self, items, ingresses=None):
        return self.jq('protected-images.jq', {'workloads': {'items': items},
                                              'ingresses': {'items': ingresses or []}})

    def test_init_scaled_zero_history_and_runtime_are_preserved(self):
        digest = 'sha256:' + 'a' * 64
        items = [
            {'kind': 'Pod', 'spec': {'initContainers': [{'image': 'registry/library/init:v1'}]},
             'status': {'containerStatuses': [{'image': 'registry/library/app:current',
                                              'imageID': 'docker-pullable://registry/library/app@' + digest}]}},
            {'kind': 'Deployment', 'spec': {'replicas': 0, 'template': {'spec': {
                'containers': [{'image': 'registry/library/zero:v1'}]}}}},
            {'kind': 'ReplicaSet', 'spec': {'replicas': 0, 'template': {'spec': {
                'containers': [{'image': 'registry/library/app:rollback'}]}}}},
            {'kind': 'ControllerRevision', 'data': {'spec': {'template': {'spec': {
                'containers': [{'image': 'registry/library/stateful:old'}]}}}}},
            {'kind': 'CronJob', 'spec': {'jobTemplate': {'spec': {'template': {'spec': {
                'containers': [{'image': 'registry/library/job:scheduled'}]}}}}}},
        ]
        result = self.inventory(items)
        self.assertEqual(result.returncode, 0, result.stderr)
        refs = {(r['repository'], r['reference']) for r in json.loads(result.stdout)}
        self.assertEqual(len(refs), 7)
        self.assertIn(('library/app', digest), refs)
        self.assertIn(('library/app', 'rollback'), refs)

    def test_registry_aliases_and_default_ports(self):
        ingress = {'spec': {'rules': [{'host': 'images.example', 'http': {'paths': [
            {'backend': {'service': {'name': 'harbor'}}}]}}]}}
        result = self.inventory([{'spec': {'containers': [
            {'image': 'images.example:443/library/demo:v1'},
            {'image': 'harbor.registries.svc/library/demo:v1'},
            {'image': 'harbor-registry:5000/library/demo:v1'},
            {'image': 'unrelated/library/demo:v1'}]}}], [ingress])
        self.assertEqual(json.loads(result.stdout), [{'repository': 'library/demo', 'reference': 'v1'}])

    def test_ambiguous_runtime_and_unreadable_history_fail_closed(self):
        for data in [
            {'kind': 'Pod', 'status': {'containerStatuses': [
                {'image': 'registry/library/demo:v1', 'imageID': 'containerd://sha256:' + 'a' * 64}]}},
            {'kind': 'ControllerRevision', 'data': 'opaque'},
            {'spec': {'containers': [{'image': 'registry/library/demo@sha256:broken'}]}},
        ]:
            self.assertNotEqual(self.inventory([data]).returncode, 0)
        self.assertNotEqual(self.jq('protected-images.jq', {'workloads': {}, 'ingresses': {'items': []}}).returncode, 0)

    def test_filer_requires_exact_ready_writable_bound_healthy_claim(self):
        self.assertEqual(self.jq('filer-persistence.jq', filer_data()).returncode, 0)
        variants = []
        data = filer_data(); data['pods']['items'][0]['spec']['containers'][0]['volumeMounts'] = []; variants.append(data)
        data = filer_data(); data['pods']['items'][0]['spec']['containers'][0]['volumeMounts'][0]['readOnly'] = True; variants.append(data)
        data = filer_data(); data['pods']['items'][0]['spec']['volumes'][0]['persistentVolumeClaim']['claimName'] = 'wrong'; variants.append(data)
        data = filer_data(); data['claims']['items'][0]['status']['phase'] = 'Pending'; variants.append(data)
        data = filer_data(); data['volumes']['items'][0]['status']['robustness'] = 'degraded'; variants.append(data)
        data = filer_data(); data['pods']['items'][0]['status']['conditions'][0]['status'] = 'False'; variants.append(data)
        for data in variants:
            self.assertNotEqual(self.jq('filer-persistence.jq', data).returncode, 0)
