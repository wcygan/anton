"""Render the real ESO Go template with Sprig and synthetic inputs only."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SECRET = ROOT / 'kubernetes/apps/storage/seaweedfs-config/app/externalsecret.yaml'


class AuxiliaryIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret = json.loads(subprocess.check_output(['yq', '-o=json', '.', str(SECRET)], text=True))
        cls.data = {d['secretKey']: 'synthetic-' + d['secretKey'] for d in cls.secret['spec']['data']}
        cls.template = cls.secret['spec']['target']['template']['data']['s3.json']

    def render(self, value, json_result=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'templates').mkdir()
            (root / 'Chart.yaml').write_text('apiVersion: v2\nname: fixture\nversion: 0.0.1\n')
            (root / 'templates/result.yaml').write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: fixture\ndata:\n  result: {{ tpl .Values.template .Values.secretData | toJson }}\n')
            data = dict(self.data, auxiliaryIdentities=value)
            values = root / 'values.json'
            values.write_text(json.dumps({'template': self.template, 'secretData': data}))
            result = subprocess.run(['helm', 'template', 'fixture', str(root), '-f', str(values)], capture_output=True, text=True, timeout=20)
            if result.returncode:
                return result, None
            rendered = subprocess.check_output(['yq', '-r', '.data.result'], input=result.stdout, text=True)
            return result, json.loads(rendered) if json_result else rendered.strip()

    def fixture(self, **changes):
        return dict({'name': 'private-fixture', 'bucket': 'private-fixture', 'accessKey': 'fixture-access', 'secretKey': 'quote"slash\\unicode☃'}, **changes)

    def test_extension_preserves_every_existing_identity(self):
        before, baseline = self.render('[]')
        after, extended = self.render(json.dumps([self.fixture()]))
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(len(baseline['identities']), 9)
        self.assertEqual(extended['identities'][:9], baseline['identities'])
        self.assertEqual(extended['identities'][9], {'name': 'private-fixture', 'actions': ['Read:private-fixture', 'Write:private-fixture', 'List:private-fixture'], 'credentials': [{'accessKey': 'fixture-access', 'secretKey': self.fixture()['secretKey']}]})

    def test_invalid_bundle_fails_rendering(self):
        cases = ['not json', 'null', '{}', '[null]', json.dumps([self.fixture(bucket='bad/name')]), json.dumps([self.fixture(secretKey='')]), json.dumps([self.fixture(name='admin')]), json.dumps([self.fixture(accessKey=self.data['harborAccessKey'])]), json.dumps([self.fixture(), self.fixture()]), json.dumps([self.fixture(actions=['Admin'])]), json.dumps([self.fixture(accessKey=42)])]
        for value in cases:
            with self.subTest(case=value):
                result, output = self.render(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(output)

    def test_bucket_intent_comes_from_the_same_bundle(self):
        self.template = self.secret['spec']['target']['template']['data']['AUXILIARY_ORDINARY_BUCKETS']
        result, output = self.render(json.dumps([self.fixture()]), json_result=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'private-fixture')



if __name__ == '__main__':
    unittest.main()
