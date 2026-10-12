import hashlib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('privacy',Path(__file__).resolve().parents[1]/'validate-public-privacy.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PrivacyContractTests(unittest.TestCase):
    def test_exact_identifier_and_filename(self):
        with patch.object(m,'FINGERPRINTS',{hashlib.sha256(b'private-fixture').hexdigest()}):
            self.assertTrue(m.private_reference('apps/private-fixture/app'))
            self.assertTrue(m.private_reference('0010-migrate-private-fixture.md'))
            self.assertFalse(m.private_reference('apps/public-fixture/app'))
    def test_shared_subdomain_is_not_an_apex_match(self):
        with patch.object(m,'FINGERPRINTS',{hashlib.sha256(b'example.com').hexdigest()}):
            self.assertTrue(m.private_reference('https://example.com/'))
            self.assertFalse(m.private_reference('https://utility.example.com/'))
