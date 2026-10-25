#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy only an explicit public allowlist, without Git history or local records."""
import argparse
import hashlib
import json
from pathlib import Path
import stat


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    project = Path(__file__).resolve().parent.parent
    target = a.output.absolute()
    # Reject before any writes. Never merge with or replace an existing tree.
    if target.exists() or target.is_symlink():
        p.error('Output exists; choose a new directory')
    if target == project or target in project.parents:
        p.error('Output must not contain the source project')
    for node in (target, *target.parents):
        if node.is_symlink(): p.error('Output parent is a symlink')
    names = (project / 'tools/public-files.txt').read_text().splitlines()
    names = [n for n in names if n and not n.startswith('#')]
    if len(names) != len(set(names)): p.error('Duplicate public file')
    data = []
    for name in names:
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            p.error('Unsafe public file path')
        if rel.parts[0] not in ('docs', 'src', 'build', 'tools', 'data') and name not in ('README.md', 'LICENSE', '.gitignore', 'install.sh'):
            p.error('Local/development record requested: ' + name)
        source = project / rel
        for node in (source, *source.parents):
            if node.is_symlink(): p.error('Source symlink: ' + name)
        if not source.is_file(): p.error('Missing public file: ' + name)
        data.append((name, source.read_bytes(), stat.S_IMODE(source.stat().st_mode)))
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, content, mode in data:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as f: f.write(content)
        dest.chmod(mode)
    print(json.dumps({'output': str(target), 'files': len(data), 'git_history_included': False,
                      'sha256': {n: hashlib.sha256(b).hexdigest() for n, b, _ in data}}, indent=2))


if __name__ == '__main__': main()
