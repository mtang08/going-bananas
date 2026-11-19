#!/usr/bin/env python3
"""Fail when a relative markdown link or a path named in an AGENTS.md points at a missing file.

Checked: README.md, docs/*.md (not docs/archive/), and the four AGENTS.md files. In an AGENTS.md, every
backticked token that contains a slash is a path (brace groups like `a/{b,c}.py` are expanded) and must exist
relative to that file's directory or to the repo root.
"""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
AGENTS = {'AGENTS.md': root, 'backend/AGENTS.md': root / 'backend',
          'frontend/AGENTS.md': root / 'frontend', 'running_coach_kb/AGENTS.md': root / 'running_coach_kb'}
LINK = re.compile(r'\]\(([^)\s]+)\)')
TOKEN = re.compile(r'`([A-Za-z0-9_.][A-Za-z0-9_./{},-]*/[A-Za-z0-9_./{},-]*)`')
errors: list[str] = []


def expand(text: str) -> list[str]:
    match = re.search(r'\{([^{}]*)\}', text)
    if not match:
        return [text]
    return [item for option in match.group(1).split(',')
            for item in expand(text[:match.start()] + option + text[match.end():])]


files = [root / 'README.md', *(root / name for name in AGENTS),
         *sorted(p for p in (root / 'docs').glob('*.md'))]
for path in files:
    for target in LINK.findall(path.read_text()):
        if target.startswith(('http://', 'https://', 'mailto:', '#')):
            continue
        if not (path.parent / target.split('#')[0]).exists():
            errors.append(f'{path.relative_to(root)}: broken link {target}')
for name, base in AGENTS.items():
    for token in TOKEN.findall((root / name).read_text()):
        for option in expand(token):
            if not (base / option).exists() and not (root / option).exists():
                errors.append(f'{name}: missing path {option}')
print('\n'.join(errors) if errors else 'docs ok')
sys.exit(1 if errors else 0)
