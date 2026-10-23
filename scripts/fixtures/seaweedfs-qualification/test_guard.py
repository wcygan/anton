"""Evidence preservation check; deliberately requires no Docker daemon."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EvidenceGuardTest(unittest.TestCase):
    def test_existing_evidence_is_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            evidence = directory / 'events.json'
            evidence.write_bytes(b'{"retained":"previous failed experiment"}\n')
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name('run.py')),
                '--output', str(directory), '--version', '4.48', '--scenario', 'stale',
            ], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn('refuse to overwrite an existing evidence path', result.stderr)
            self.assertEqual(evidence.read_bytes(), b'{"retained":"previous failed experiment"}\n')
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ['events.json'])


if __name__ == '__main__':
    unittest.main()
