#!/usr/bin/env python3
"""Replay a private WAL working copy with a prebuilt Loki 3.7.8 test harness.

Build scripts/fixtures/loki-wal/forensic_test.go inside upstream v3.7.8's
pkg/ingester using `go test -c -vet=off -o forensic.test ./pkg/ingester`.
Build dependencies before attaching evidence. This command only runs offline.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

IMAGE = 'golang@sha256:705e964a93a2fd2e75c7d59bb7d781b57e30f12293ffde5175c69229e18fb678'


def hashes(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('WAL evidence must not contain symlinks')
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            result[str(path.relative_to(root))] = digest.hexdigest()
    if not result:
        raise ValueError('WAL evidence is empty')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wal', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline = args.wal.resolve(strict=True)
    binary = args.binary.resolve(strict=True)
    before = hashes(baseline)
    results = []
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix='loki-wal-replay-') as temp:
            copy = Path(temp) / 'wal'
            shutil.copytree(baseline, copy)
            run = subprocess.run([
                'docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--memory', '4g', '--cpus', '2', '--pids-limit', '256',
                '--tmpfs', '/tmp:rw,size=256m', '-e', 'GOPROXY=off',
                '-e', 'GOSUMDB=off', '-e', 'GOTOOLCHAIN=local',
                '-e', 'FORENSIC_WAL=/work/wal',
                '-v', f'{binary}:/forensic.test:ro',
                '-v', f'{copy}:/work/wal', IMAGE,
                '/forensic.test', '-test.run=^TestForensicReplay$',
                '-test.v', '-test.timeout=10m',
            ], capture_output=True, text=True, timeout=620)
            if run.returncode:
                raise RuntimeError('Offline replay failed; preserve private diagnostics: ' + run.stderr[:200])
            records = [line.removeprefix('FORENSIC_RESULT ') for line in run.stdout.splitlines()
                       if line.startswith('FORENSIC_RESULT ')]
            if len(records) != 1:
                raise RuntimeError('Expected exactly one forensic result')
            results.append(json.loads(records[0]))
    assert hashes(baseline) == before, 'Baseline evidence changed'
    report = {'baseline_sha256': before, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'network': 'none', 'runs': results, 'reproduced': results[0] == results[1]}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'runs': len(results), 'baseline_unchanged': True, 'reproduced': report['reproduced']}))


if __name__ == '__main__':
    main()
