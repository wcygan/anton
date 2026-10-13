#!/usr/bin/env python3
"""Reject reintroduced private application identifiers in tracked public files.

Only fingerprints are stored publicly. The private repo generates the digest file
from its identifier list; this check runs independently with no private Git access.
Shared public platform utility hostnames are intentionally outside that list.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT_FILE = ROOT / 'scripts/data/public-privacy-fingerprints.json'


def load_fingerprints(path=FINGERPRINT_FILE):
    values = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(values, list) or not values or any(
        not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
        for value in values
    ):
        raise ValueError('Public privacy data must contain only SHA-256 fingerprints')
    if values != sorted(set(values)):
        raise ValueError('Public privacy fingerprints must be sorted and unique')
    return set(values)


FINGERPRINTS = load_fingerprints()


def candidates(text):
    for token in re.findall(r'[a-z0-9][a-z0-9._/-]*', text.lower()):
        token = token.strip('/.')
        yield token
        yield from token.split('/')
        # Detect identifiers embedded in filenames without matching domain suffixes.
        for segment in token.split('/'):
            parts = segment.split('-')
            for a in range(len(parts)):
                for b in range(a + 1, len(parts) + 1):
                    yield '-'.join(parts[a:b]).removesuffix('.md').removesuffix('.yaml').removesuffix('.py')


def private_reference(text):
    return any(hashlib.sha256(v.encode()).hexdigest() in FINGERPRINTS for v in candidates(text))


def main():
    files = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'], cwd=ROOT, text=True).splitlines()
    failures=[]
    for rel in files:
        path=ROOT/rel
        if not path.is_file():continue
        try:text=path.read_text()
        except UnicodeDecodeError:continue
        if private_reference(rel) or private_reference(text):failures.append(rel)
    if failures:
        print('Private application details found in public files:',file=sys.stderr)
        for rel in failures:print(rel,file=sys.stderr)
        return 1
    print('Public application privacy contract: PASS')
    return 0


if __name__=='__main__':sys.exit(main())
