#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a deterministic user-session material package; no installation/network."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--version', default='0.3.0')
output = p.add_mutually_exclusive_group(required=True)
output.add_argument('--output', type=Path, help='Optional ZIP for offline transfer')
output.add_argument('--directory', type=Path, help='Prepare a source-install snapshot without a ZIP')
a = p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', a.version): p.error('Invalid version')
destination = a.output or a.directory
if destination.exists() or destination.is_symlink(): p.error('Output exists; use a new filename')
root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('material_spec', root / 'tools/manage-material.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
files = {}
for n in m.THEME_FILES:
    source = root / 'build/Glass50-Material-Preview' / n
    if source.is_symlink(): p.error('Symlink theme payload: ' + str(source))
    files['payload/' + m.theme_target(n)] = source.read_bytes()
for n in m.EXT_FILES:
    if n == 'schemas/gschemas.compiled': continue
    source = root / ('src/' + n if n.startswith('effects/') else 'src/extension/' + n)
    if source.is_symlink(): p.error('Symlink payload: ' + str(source))
    files['payload/' + m.EXT + n] = source.read_bytes()
with tempfile.TemporaryDirectory(prefix='glass50-schema-') as directory:
    schema = Path(directory) / 'org.gnome.shell.extensions.glass50-blur.gschema.xml'
    schema.write_bytes(files['payload/' + m.EXT + 'schemas/' + schema.name])
    subprocess.run(['glib-compile-schemas', '--strict', directory], check=True)
    files['payload/' + m.EXT + 'schemas/gschemas.compiled'] = (Path(directory) / 'gschemas.compiled').read_bytes()
for n, source in {'manage-material.py': 'tools/manage-material.py', 'manage-theme.py': 'tools/manage-theme.py',
                  'flatpak-discovery.py': 'tools/flatpak-discovery.py', 'manage-t16.py': 'tools/manage-t16.py',
                  'manage-desktop.py':'tools/manage-desktop.py', 'desktop-context.py':'tools/desktop-context.py',
                  'INSTALL.md': 'docs/INSTALL.md', 'ARCHITECTURE.md': 'docs/ARCHITECTURE.md',
                  'LICENSE': 'LICENSE', 'LICENSES.md': 'docs/LICENSES.md'}.items():
    files[n] = (root / source).read_bytes()
revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, capture_output=True)
source_commit = revision.stdout.strip() if revision.returncode == 0 else None
source_dirty = (bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip())
                if source_commit else None)
manifest = {'format': 2, 'component': 'material-preview', 'version': a.version,
    **m.layer_info(),
    'source_commit': source_commit, 'source_tree_dirty': source_dirty,
    'scope': 'Ubuntu 26.04 / GNOME Shell 50.x / Wayland; user-session installation', 'extension_version': 10,
    'files': {n.removeprefix('payload/'):hashlib.sha256(b).hexdigest() for n,b in files.items() if n.startswith('payload/')},
    'support_files': {n:hashlib.sha256(b).hexdigest() for n,b in files.items() if not n.startswith('payload/')}}
files['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()
result = {'path': str(destination), 'manifest': manifest}
if a.directory:
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for n, b in sorted(files.items()):
        target = destination / n
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f:
            f.write(b)
else:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as f:
        with zipfile.ZipFile(f, 'w', compression=zipfile.ZIP_STORED) as z:
            for n,b in sorted(files.items()):
                i = zipfile.ZipInfo('Glass50-Material-Preview/'+n, date_time=(2026,1,1,0,0,0)); i.create_system=3; i.external_attr=0o100644<<16
                z.writestr(i,b)
    result['sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
print(json.dumps(result, indent=2))
