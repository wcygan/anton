#!/usr/bin/env python3
"""Reject reintroduced private application identifiers in tracked public files.

Only fingerprints are stored here. The private repo maintains the identifier list.
Shared public platform utility hostnames are intentionally outside that list.
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINTS = set(['1820225782cc5be72b7d64a1a4cf85f73e794eeb824ee38b60851459268e3d23', '2a91af5acf7e3785df5b4dd6ef11e460c68721020e13189440cd70757859b71b', '3c543a1acdba50f0bdf3b719ff154391413567103be8385d1ada37cf7aab6d79', '7767620acc528991f8767185d56467c7fd82094c31344e743629fbaf96446c3d', '77b5742761cb19fca9c8543a68598f9b3542650fac56b28f2896edf9b4dce12a', '88b1d5adc6f2c9d72b9021c3b46709ca882d92da84ae3bff86ae59611cfd1d4f', '9b92efa1c0b4bb3adbe3f66c7842979ad73781a90bafea270fb83360ae23b64b', 'a5c5a15eec449ca189f1bdd67808dc2e3738a6851e85a931ba2ce43100195927', 'ab173140111e0f3bbe36a7dca86105d6e9a391def814860235f2843600988d98', 'b73d5b4600dd903006edf4e563a984f7a33106590b46027a5a5768758392de59', 'c46bfd7a653b2652419ba5dea1c4f6b676ca86857cd8850bd150166d3904ac08', 'ca00b399a45b6da79853f32960927ab905d2e67de88a39f2682eb7925973f7a3', 'd650e37a8c92a48e6d92e18d1de4d343000e03c370b1a3376aaab9e41d325fb1', 'd80e298a05cb98eb59d2e3fb1a257508f2860f1e5db5b58ce9da16242209c753', 'e0d699d80c184796999dddbf34a487e924a22d3f24c0b9a517ebce27eed6e3fb', 'ec99b77a8c1e6dc0461fd76ade1b853bd4131b0d5a26670ac62d0b2ba96c9a85', 'f2c3d0d1af134ae877eb54a97ca39f2eba092c90177043c56887d334cfd9a609'])


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
