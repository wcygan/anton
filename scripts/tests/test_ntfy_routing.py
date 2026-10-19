"""Exercise rendered ntfy routes with Alertmanager's real matcher engine.

Set AMTOOL_BIN to a matching amtool binary, or install amtool on PATH.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
AMTOOL = os.environ.get('AMTOOL_BIN') or shutil.which('amtool')


@unittest.skipUnless(AMTOOL, 'ntfy route behavior requires amtool (AMTOOL_BIN or PATH)')
class NtfyRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.check_output([
            'kustomize', 'build', str(ROOT / 'kubernetes/apps/observability/ntfy/app')], text=True)
        objects = json.loads(subprocess.check_output([
            'yq', '-o=json', '-I=0', 'select(.kind == "AlertmanagerConfig")'],
            input=rendered, text=True))
        policy = objects['spec']

        def route(value):
            keys = {'receiver': 'receiver', 'groupBy': 'group_by', 'groupWait': 'group_wait',
                    'groupInterval': 'group_interval', 'repeatInterval': 'repeat_interval',
                    'continue': 'continue'}
            result = {target: value[source] for source, target in keys.items() if source in value}
            if 'matchers' in value:
                result['matchers'] = [m['name'] + m['matchType'] + json.dumps(m['value'])
                                      for m in value['matchers']]
            if 'routes' in value:
                result['routes'] = [route(child) for child in value['routes']]
            return result

        cls.temporary = tempfile.TemporaryDirectory()
        cls.config = Path(cls.temporary.name) / 'alertmanager.json'
        cls.config.write_text(json.dumps({'route': route(policy['route']),
                                         'receivers': [{'name': r['name']} for r in policy['receivers']]}))
        subprocess.run([AMTOOL, 'check-config', str(cls.config)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_receiver_selection(self):
        cases = [
            ('LonghornVolumeDegraded', 'warning', 'storage', 'ntfy'),
            ('OTelCollectorQueueHigh', 'warning', 'observability', 'ntfy'),
            ('KubeNodeNotReady', 'warning', 'kube-system', 'ntfy'),
            ('KubeNodeUnreachable', 'warning', 'kube-system', 'ntfy'),
            ('KubeNodeReadinessFlapping', 'warning', 'kube-system', 'ntfy'),
            ('AnyCriticalAlert', 'critical', 'default', 'ntfy'),
            ('CPUThrottlingHigh', 'warning', 'observability', 'drop'),
            ('KubeJobFailed', 'warning', 'registries', 'drop'),
            ('OtherWarning', 'warning', 'default', 'drop'),
            ('LonghornVolumeDegraded', 'info', 'storage', 'drop'),
            ('OTelCollectorQueueHigh', 'info', 'observability', 'drop'),
            ('PrefixLonghornVolumeDegraded', 'warning', 'storage', 'drop'),
            ('OTelCollectorQueueHighSuffix', 'warning', 'observability', 'drop'),
        ]
        for name, severity, namespace, expected in cases:
            with self.subTest(alertname=name, severity=severity):
                result = subprocess.run([
                    AMTOOL, 'config', 'routes', 'test', '--config.file=' + str(self.config),
                    '--verify.receivers=' + expected, 'alertname=' + name,
                    'severity=' + severity, 'namespace=' + namespace], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
