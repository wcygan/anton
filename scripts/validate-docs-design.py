#!/usr/bin/env python3
"""Guard Anton's diagram authoring contract and paired theme tokens."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('processing', 'storage', 'flow', 'control')
COLOR = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|color)\s*\(')
NODE = re.compile(r'\b([A-Za-z]\w*)\s*(\[\(.*?\)\]|\[.*?\]|\(\(.*?\)\)|\(.*?\)|\{.*?\})(:::\w+)?')


def source_errors(text, name):
    errors = []
    prose = re.sub(r'```.*?```', '', text, flags=re.S)
    if re.search(r'<(?:svg|canvas|iframe)\b|\bstyle\s*=', prose, re.I):
        errors.append(f'{name}: use shared Diagram components; no raw SVG or local styles in pages')
    if re.search(r'\b(?:fill|stroke|color|bgcolor)\s*=', prose, re.I) or COLOR.search(prose):
        errors.append(f'{name}: page colors belong in tokens.css')
    for diagram in re.findall(r'```mermaid\s*\n(.*?)```', text, re.S):
        lines = [line.strip() for line in diagram.splitlines() if line.strip() and not line.strip().startswith('%% ')]
        if not lines or not re.match(r'^(?:flowchart|graph)\s+(?:TB|TD|BT|LR|RL)\s*$', lines[0]):
            errors.append(f'{name}: use a themed flowchart; other diagram types need a shared adapter')
        if re.search(r'%%\{|\b(?:classDef|style|linkStyle|click|class)\b', diagram) or COLOR.search(diagram):
            errors.append(f'{name}: Mermaid styling overrides are forbidden; use semantic roles')
        declared = set()
        references = set()
        for line in lines[1:]:
            if line.startswith(('subgraph ', 'end', '%%')):
                continue
            for node in NODE.finditer(line):
                declared.add(node[1])
                if (node[3] or '')[3:] not in ROLES:
                    errors.append(f'{name}: node {node[1]} needs one inline semantic role')
            remaining = NODE.sub(lambda match: match[1], line)
            remaining = re.sub(r'\|[^|]*\||"[^"]*"', '', remaining)
            references.update(re.findall(r'\b[A-Za-z]\w*\b', remaining))
        for missing in sorted(references - declared):
            errors.append(f'{name}: node {missing} must be declared with a semantic role')
    return errors


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))


def contrast(a, b):
    low, high = sorted((luminance(a), luminance(b)))
    return (high + .05) / (low + .05)


def palette_errors(css):
    themes = {'light': {}, 'dark': {}}
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        theme = 'dark' if "[data-theme='dark']" in selector else 'light'
        themes[theme].update(re.findall(r'(--[\w-]+):\s*([^;]+);', body))
    errors = []
    for theme in themes:
        values = themes['light'] | themes[theme]
        def color(role):
            value = values.get('--diagram-' + role, '')
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError(f'{theme}: --diagram-{role} must be an explicit six-digit color token')
            return value
        def check(a, b, minimum):
            if contrast(color(a), color(b)) < minimum:
                errors.append(f'{theme}: {a} against {b} needs {minimum}:1 contrast')
        try:
            for surface in ('panel-background', 'group-background'):
                check('text', surface, 4.5)
                check('muted-text', surface, 4.5)
                check('connector', surface, 3)
                for role in ROLES:
                    check('node-text', role + '-fill', 4.5)
                    # A bright fill OR a dark outline can define the shape boundary.
                    if max(contrast(color(role + '-fill'), color(surface)), contrast(color(role + '-stroke'), color(surface))) < 3:
                        errors.append(f'{theme}: {role} shape must separate from {surface} at 3:1')
        except ValueError as error:
            errors.append(str(error))
    return errors


def validate(root):
    errors = []
    for pattern in ('*.md', '*.mdx'):
        for page in (root / 'docs/docs').rglob(pattern):
            errors.extend(source_errors(page.read_text(), str(page.relative_to(root))))
    tokens = root / 'docs/src/css/tokens.css'
    if not tokens.exists():
        errors.append('Missing authoritative docs/src/css/tokens.css')
    else:
        errors.extend(palette_errors(tokens.read_text()))
    for path in (root / 'docs/src').rglob('*'):
        if path.suffix not in ('.css', '.tsx', '.ts') or path == tokens:
            continue
        source = path.read_text()
        if path.suffix in ('.tsx', '.ts') and path.parent.name != 'Diagram' and re.search(r'<(?:svg|canvas|rect|ellipse|polygon)\b|\bstyle\s*=', source):
            errors.append(f'{path.relative_to(root)}: compose the shared Diagram primitives instead of raw shapes or styles')
        if path.suffix == '.css':
            for value in re.findall(r'(?<![-\w])(?:fill|stroke|color|background(?:-color)?|border(?:-color)?)\s*:\s*([^;}]+)', source):
                if 'var(' not in value and value.strip() not in ('none', 'inherit', 'transparent', 'currentColor'):
                    errors.append(f'{path.relative_to(root)}: CSS colors must reference tokens')
        if COLOR.search(source):
            errors.append(f'{path.relative_to(root)}: color literals belong in tokens.css')
        if path.suffix in ('.tsx', '.ts') and re.search(r'\b(?:fill|stroke|color|backgroundColor)\s*[:=]\s*[\'\"](?!none\b|currentColor\b|var\()', source):
            errors.append(f'{path.relative_to(root)}: use shared token classes instead of color attributes')
    return errors


if __name__ == '__main__':
    problems = validate(ROOT)
    print('\n'.join(problems) if problems else 'Anton design contract: PASS')
    sys.exit(bool(problems))
