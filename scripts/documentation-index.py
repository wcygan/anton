#!/usr/bin/env python3
"""Print a bounded decision or active-work index without contacting the cluster."""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from documentation_paths import DECISIONS, plans_directory


def metadata(path):
    text = path.read_text(encoding='utf-8')
    fields = {}
    if text.startswith('---\n'):
        for line in text.split('---', 2)[1].splitlines():
            key, separator, value = line.partition(':')
            if separator:
                fields[key.strip()] = value.strip().strip('\'"')
    title = re.search(r'^#\s+(.*)', text, re.M)
    fields['title'] = title[1] if title else path.stem
    return fields


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['adrs', 'plans', 'conventions'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.kind == 'conventions':
        guidance = args.root / 'AGENTS.md'
        if not guidance.is_file():
            print('Anton AGENTS.md unavailable; load repository guidance before work.', file=sys.stderr)
            return 0
        text = guidance.read_text()
        print('## Anton operating conventions\n')
        for heading in ('## Operational Contract', '## Safety and Secrets'):
            start = text.find(heading)
            if start >= 0:
                end = text.find('\n## ', start+len(heading))
                print(text[start:end if end >= 0 else None])
        return 0
    directory = args.root / DECISIONS if args.kind == 'adrs' else plans_directory(args.root)
    if not directory.is_dir():
        print('Anton documentation index unavailable: ' + ('public decisions are missing.' if args.kind == 'adrs' else 'private work records are not accessible; do not infer there is no active work.'), file=sys.stderr)
        return 0
    statuses_path = args.root / '.agents/skills/planner/references/statuses.txt'
    statuses = {'draft', 'in-progress', 'blocked', 'done', 'abandoned'}
    if statuses_path.is_file():
        loaded = {line.strip().lower() for line in statuses_path.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')}
        if loaded:
            statuses = loaded
        else:
            print('Canonical plan status enum is empty; using built-in statuses.', file=sys.stderr)
    rows = []
    for path in sorted(directory.glob('[0-9][0-9][0-9][0-9]-*.md')):
        try:
            fields = metadata(path)
        except (OSError, UnicodeError) as error:
            print(f'Unreadable documentation record: {path.name} ({type(error).__name__})', file=sys.stderr)
            continue
        status = fields.get('status', '(missing)')
        if args.kind == 'plans':
            if status.lower() not in statuses:
                print(f'Invalid plan status: {path.name}: {status}', file=sys.stderr)
            elif status.lower() in {'done', 'abandoned'}:
                continue
        title = fields['title'].replace('|', '\\|')
        rows.append(f'| {title} | {status} | {fields.get("date", fields.get("review-by", "—"))} |')
    print('## Anton decisions' if args.kind == 'adrs' else '## Anton active work')
    print('\n| Record | Status | Decision date / review by |\n| --- | --- | --- |')
    limit = 40 if args.kind == 'adrs' else 20
    print('\n'.join(rows[-limit:]))
    if len(rows) > limit:
        print(f'\n{len(rows)-limit} older entries omitted; consult the canonical collection.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
