#!/usr/bin/env python3
"""Validate the public documentation layout, decision identities, links, and privacy."""
import ipaddress
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = {'overview', 'guides', 'reference', 'decisions', 'records'}
STALE = ('context/adrs/', 'context/plans/', 'context/notes/', 'context/hardware.md', 'context/software.md', '.claude/skills/', 'docs/docs/notes/', 'docs/docs/runbooks/', 'docs/docs/playground/')


def validate(root):
    errors = []
    public = root / 'docs/docs'
    pages = sorted(public.rglob('*.md'))
    ids = []
    for path in pages:
        relative = path.relative_to(public)
        text = path.read_text()
        if path.name != 'intro.md' and relative.parts[0] not in SECTIONS:
            errors.append(f'{relative}: outside canonical sections')
        for stale in STALE:
            if stale in text:
                errors.append(f'{relative}: obsolete documentation reference {stale}')
        if re.search(r'anton-private|/Users/|(?:[a-z0-9-]+\.)?tail[a-z0-9-]+\.ts\.net|cfargotunnel\.com', text, re.I):
            errors.append(f'{relative}: private location or endpoint')
        for token in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', text):
            try:
                address = ipaddress.ip_address(token)
            except ValueError:
                continue
            if not address.is_loopback:
                errors.append(f'{relative}: literal infrastructure address')
        if relative.parts[0] == 'decisions' and re.match(r'^\d{4}-', path.name):
            ids.append(path.name[:4])
            if not text.startswith('---\n') or len(text.split('---', 2)) < 3:
                errors.append(f'{relative}: missing frontmatter')
            else:
                fields = dict(re.findall(r'^([a-z-]+):\s*(.*)$', text.split('---', 2)[1], re.M))
                for field in ('date', 'status', 'affects', 'intent', 'supersedes', 'superseded-by'):
                    if field not in fields:
                        errors.append(f'{relative}: missing {field}')
                if int(path.name[:4]) <= 40 and fields.get('edition') != 'condensed-public':
                    errors.append(f'{relative}: unmarked public edition')
                target = re.search(r'Superseded-by (\d{4})', fields.get('status', ''))
                if target and not list((public / 'decisions').glob(target[1]+'-*.md')):
                    errors.append(f'{relative}: missing successor')
            if int(path.name[:4]) <= 40 and 'Public edition condensed on 2026-10-21' not in text:
                errors.append(f'{relative}: missing editorial provenance')
        for diagram in re.findall(r'```mermaid\n(.*?)```', text, re.S):
            if re.search(r'classDef[^\n]*var\(', diagram):
                errors.append(f'{relative}: Mermaid palette must use CSS classes, not CSS var() in classDef')
            if re.search(r'\)\s+\]', diagram):
                errors.append(f'{relative}: malformed Mermaid cylinder closing delimiter')
        prose = re.sub(r'```.*?```', '', text, flags=re.S)
        for target in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', prose):
            if re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:|/|#', target):
                continue
            destination = target.split('#', 1)[0]
            if destination and not (path.parent / destination).exists():
                errors.append(f'{relative}: broken relative link {destination}')
    expected = [f'{number:04d}' for number in range(1, 41)]
    if not set(expected).issubset(ids) or len(ids) != len(set(ids)):
        errors.append('Decisions must preserve original IDs 0001–0040 and keep every ID unique')
    redirects_path = root / 'docs/redirects.json'
    if redirects_path.is_file():
        seen = set()
        for rule in json.loads(redirects_path.read_text()):
            if rule['from'] in seen:
                errors.append('Duplicate redirect source: '+rule['from'])
            seen.add(rule['from'])
            target = rule['to']
            if target != '/' and not (public / (target.lstrip('/')+'.md')).exists():
                errors.append('Missing redirect destination: '+target)
    return errors


def main():
    errors = validate(ROOT)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Public documentation contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
