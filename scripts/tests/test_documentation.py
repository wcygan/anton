"""Behavioral checks for migrated discovery and publication boundaries."""
import importlib.util
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/lib'))
from agent_policy_contract import plan_status_violation

spec = importlib.util.spec_from_file_location('documentation_validator', ROOT / 'scripts/validate-documentation.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class DocumentationTests(unittest.TestCase):
    def test_public_catalog_links_and_identifiers(self):
        self.assertEqual(validator.validate(ROOT), [])

    def test_future_decision_is_allowed_without_migration_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'docs/docs', root / 'docs/docs')
            (root / 'docs/docs/decisions/0041-example.md').write_text('---\ndate: 2026-10-21\nstatus: Accepted\naffects: all\nintent: concrete-need\nsupersedes: []\nsuperseded-by: null\n---\n# Future choice\n')
            self.assertEqual(validator.validate(root), [])

    def test_missing_private_records_reports_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'anton'
            (root / '.agents').mkdir(parents=True)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/documentation-index.py'), 'plans', '--root', str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('do not infer there is no active work', result.stderr)
            self.assertNotIn('active work', result.stdout)

    def test_private_plan_status_and_active_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'anton'
            (root / '.agents').mkdir(parents=True)
            plans = root.parent / 'anton-private/docs/operations/platform-work/plans'
            plans.mkdir(parents=True)
            active = plans / '0001-example.md'
            active.write_text('---\nstatus: mystery\n---\n# Investigation\n')
            self.assertIsNotNone(plan_status_violation(active, root))
            active.write_text('---\nstatus: In-progress\n---\n# Investigation\n')
            (plans / '0002-complete.md').write_text('---\nstatus: Done\n---\n# Finished\n')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/documentation-index.py'), 'plans', '--root', str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('Investigation', result.stdout)
            self.assertNotIn('Finished', result.stdout)
            self.assertIsNone(plan_status_violation(active, root))

    def test_new_page_rejects_private_address_and_dangling_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guides = root / 'docs/docs/guides'
            guides.mkdir(parents=True)
            (guides / 'unsafe.md').write_text('# Example\nNode 10.20.30.40\n[Missing](absent.md)\n')
            errors = '\n'.join(validator.validate(root))
            self.assertIn('literal infrastructure address', errors)
            self.assertIn('broken relative link absent.md', errors)


if __name__ == '__main__':
    unittest.main()
