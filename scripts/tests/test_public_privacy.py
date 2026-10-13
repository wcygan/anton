import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('privacy',Path(__file__).resolve().parents[1]/'validate-public-privacy.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PrivacyContractTests(unittest.TestCase):
    def test_fingerprint_file_accepts_only_sorted_unique_digests(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fingerprints.json'
            path.write_text(json.dumps(['a' * 64, 'b' * 64]))
            self.assertEqual(m.load_fingerprints(path), {'a' * 64, 'b' * 64})
            for values in [[], {}, ['private-fixture'], ['A' * 64], [7],
                           ['a' * 64, 'a' * 64], ['b' * 64, 'a' * 64]]:
                with self.subTest(values=values):
                    path.write_text(json.dumps(values))
                    with self.assertRaises(ValueError):
                        m.load_fingerprints(path)

    def test_missing_or_invalid_fingerprint_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fingerprints.json'
            with self.assertRaises(FileNotFoundError):
                m.load_fingerprints(path)
            path.write_text('invalid json')
            with self.assertRaises(ValueError):
                m.load_fingerprints(path)

    def test_exact_identifier_and_filename(self):
        with patch.object(m,'FINGERPRINTS',{hashlib.sha256(b'private-fixture').hexdigest()}):
            self.assertTrue(m.private_reference('apps/private-fixture/app'))
            self.assertTrue(m.private_reference('0010-migrate-private-fixture.md'))
            self.assertFalse(m.private_reference('apps/public-fixture/app'))
    def test_shared_subdomain_is_not_an_apex_match(self):
        with patch.object(m,'FINGERPRINTS',{hashlib.sha256(b'example.com').hexdigest()}):
            self.assertTrue(m.private_reference('https://example.com/'))
            self.assertFalse(m.private_reference('https://utility.example.com/'))
