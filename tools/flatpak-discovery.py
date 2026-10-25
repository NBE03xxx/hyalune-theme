#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only Flatpak discovery. Inspect ELF dependencies; never run an application."""
import configparser
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
from types import SimpleNamespace

APP_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*){2,}')


def valid_id(value):
    return len(value) <= 255 and APP_ID.fullmatch(value) is not None


def app_paths(app):
    if not valid_id(app): raise ValueError('Invalid Flatpak app ID')
    return (f'.var/app/{app}/config/gtk-3.0/gtk.css', f'.var/app/{app}/config/gtk-4.0/gtk.css',
            f'.local/share/flatpak/overrides/{app}', f'.local/state/glass50/installer-flatpak-v1/{app}/active.json')


def recovery_paths(operations, native_paths, native_settings=()):
    """Only recognize our exact app-local paths, even if applications were removed."""
    allowed = set(native_paths)
    for op in operations:
        if op['kind'] == 'setting':
            if op['name'] not in native_settings: raise ValueError('Unexpected recovery setting')
            continue
        if op['kind'] != 'file': raise ValueError('Unexpected recovery operation')
        if op['name'] in allowed: continue
        name = op['name']
        patterns = [r'\.var/app/([^/]+)/config/gtk-[34]\.0/gtk\.css',
                    r'\.local/share/flatpak/overrides/([^/]+)',
                    r'\.local/state/glass50/installer-flatpak-v1/([^/]+)/active\.json']
        match = next((m for p in patterns if (m := re.fullmatch(p, name))), None)
        if op['kind'] != 'file' or not match or not valid_id(match[1]):
            raise ValueError('Unexpected composite recovery target: ' + name)
        allowed.update(app_paths(match[1]))
    return allowed


def elf_needed(path):
    """Bounded ELF32/64 dynamic string reading; no extra packages or execution."""
    with path.open('rb') as f:
        size = path.stat().st_size
        def read(offset, count):
            if offset < 0 or count < 0 or offset + count > size: raise ValueError('ELF bounds')
            f.seek(offset); data = f.read(count)
            if len(data) != count: raise ValueError('Short ELF')
            return data
        header = read(0, min(size, 64))
        if header[:4] != b'\x7fELF' or len(header) < 52: return []
        if header[4] not in (1, 2) or header[5] not in (1, 2): raise ValueError('Unknown ELF encoding')
        endian = '<' if header[5] == 1 else '>'
        wide = header[4] == 2
        phoff = struct.unpack_from(endian + ('Q' if wide else 'I'), header, 32 if wide else 28)[0]
        entry, count = struct.unpack_from(endian + 'HH', header, 54 if wide else 42)
        fmt = endian + ('IIQQQQQQ' if wide else 'IIIIIIII')
        if count > 1024 or not struct.calcsize(fmt) <= entry <= 256: raise ValueError('ELF program headers')
        loads = []; dynamic = None
        for i in range(count):
            p = struct.unpack(fmt, read(phoff + i * entry, struct.calcsize(fmt)))
            kind, offset, address, length = (p[0], p[2], p[3], p[5]) if wide else (p[0], p[1], p[2], p[4])
            if kind == 1: loads.append((address, offset, length))
            if kind == 2: dynamic = (offset, length)
        if dynamic is None: return []
        if dynamic[1] > 1024 * 1024: raise ValueError('ELF dynamic section too large')
        data = read(*dynamic); fmt = endian + ('QQ' if wide else 'II'); width = struct.calcsize(fmt)
        table = limit = None; wanted = []
        for offset in range(0, len(data) - width + 1, width):
            tag, value = struct.unpack_from(fmt, data, offset)
            if tag == 0: break
            if tag == 1: wanted.append(value)
            elif tag == 5: table = value
            elif tag == 10: limit = value
        if not wanted: return []
        if table is None or limit is None or limit > 4 * 1024 * 1024 or len(wanted) > 256: raise ValueError('ELF string table')
        match = next(((address, offset, length) for address, offset, length in loads if address <= table < address + length), None)
        if match is None or table - match[0] + limit > match[2]: raise ValueError('ELF string mapping')
        data = read(match[1] + table - match[0], limit)
        result = []
        for offset in wanted:
            end = data.find(b'\0', offset, min(offset + 4096, len(data)))
            if end < 0: raise ValueError('ELF dependency string')
            result.append(data[offset:end].decode('utf-8'))
        return result


def classify(location, runtime, command):
    if runtime.startswith('org.kde.Platform/'): return 'unsupported', 'KDE/Qt runtime'
    if not command or '/' in command or not re.fullmatch(r'[A-Za-z0-9_.+-]+', command):
        return 'unknown', 'Cannot resolve a simple app command'
    if any(n in command.lower() for n in ['electron', 'chromium', 'chrome', 'brave']):
        return 'unsupported', 'Browser/Electron-style executable'
    files = (location / 'files').resolve(); binary = (files / 'bin' / command).resolve()
    if not binary.is_relative_to(files) or not binary.is_file(): return 'unknown', 'Command is outside the app files'
    # Do not infer toolkit use from wrapper script names or runtime availability.
    if binary.stat().st_size > 64 * 1024 * 1024: return 'unknown', 'Large executable needs manual classification'
    needed = set(elf_needed(binary))
    if not needed: return 'unknown', 'Script/static executable: GTK use not established'
    # Some launchers link an app-owned shared library rather than GTK directly.
    candidates = []
    for folder in ['lib', 'lib64']:
        root = files / folder
        if root.exists():
            for i, path in enumerate(root.rglob('*.so*')):
                if i >= 2048: return 'unknown', 'Too many app libraries for bounded inspection'
                resolved = path.resolve()
                if resolved.is_relative_to(files) and resolved.is_file(): candidates.append((path.name, resolved))
    libraries = dict(candidates); seen = set()
    for _ in range(16):
        names = needed - seen
        if not names: break
        seen.update(names)
        for name in names:
            if name in libraries: needed.update(elf_needed(libraries[name]))
    if any(re.match(r'libQt[56]', n) for n in needed): return 'unsupported', 'Qt library dependency'
    if any(n.startswith(('libgtk-4.so.', 'libadwaita-1.so.')) for n in needed): return 'gtk4', 'GTK4/libadwaita library dependency'
    if any(n.startswith(('libgtk-3.so.', 'libhandy-1.so.')) for n in needed): return 'gtk3', 'GTK3 library dependency'
    return 'unknown', 'No GTK dependency established'


def scan(home, env=None):
    if shutil.which('flatpak', path=(env or {}).get('PATH')) is None:
        return {'available': False, 'apps': [], 'note': 'Flatpak is not installed'}
    def query(*args):
        p = subprocess.run(['flatpak', *args], env=env, capture_output=True, text=True, timeout=20)
        if p.returncode: raise ValueError(p.stderr.strip() or 'Flatpak discovery failed')
        return p.stdout.strip()
    raw = [line.split('\t') for line in query('list', '--app', '--columns=application,runtime,installation').splitlines()]
    running = set(query('ps', '--columns=application').splitlines()); counts = {}
    for row in raw:
        if len(row) != 3 or not valid_id(row[0]): raise ValueError('Unexpected Flatpak inventory')
        counts[row[0]] = counts.get(row[0], 0) + 1
    result = []
    for app, runtime, installation in raw:
        row = {'app': app, 'runtime': runtime, 'installation': installation, 'toolkit': 'unknown'}
        paths = app_paths(app); state = home / paths[-1]; pending = state.with_name('pending.json')
        if counts[app] > 1:
            row.update(status='skipped', reason='Multiple installations share this app ID'); result.append(row); continue
        try:
            location = Path(query('info', '--show-location', app))
            metadata = configparser.ConfigParser(interpolation=None, strict=True); metadata.read(location / 'metadata')
            toolkit, reason = classify(location, runtime, metadata.get('Application', 'command', fallback=''))
            row.update(toolkit=toolkit, reason=reason)
            row['info'] = {k: query('info', flag, app) for k, flag in [('ref','--show-ref'),('origin','--show-origin'),('runtime','--show-runtime'),('commit','--show-commit')]}
            if pending.exists() or state.is_symlink(): row.update(status='conflict', reason='Pending or linked management record')
            elif state.exists(): row.update(status='already-managed', reason='Existing per-app profile is preserved')
            elif toolkit not in ['gtk3','gtk4']: row['status'] = 'skipped'
            elif app in running: row.update(status='deferred', reason='App is running; it will not be stopped')
            else: row['status'] = 'candidate'
        except (OSError, ValueError, configparser.Error, struct.error) as error:
            row.update(status='skipped', reason='Inspection failed: ' + str(error))
        result.append(row)
    return {'available': True, 'apps': result}


def app_module():
    spec = importlib.util.spec_from_file_location('flatpak_app_plan', Path(__file__).with_name('manage-flatpak.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def prepare(home, source, inventory):
    """Return plans only. Caller commits them together with the base transaction."""
    m = app_module(); m.ARGS = SimpleNamespace(source=str(source))
    frozen = m.sources()  # Missing/invalid common assets abort before any install writes.
    operations = []; report = json.loads(json.dumps(inventory))
    for row in report['apps']:
        if row['status'] != 'candidate': continue
        child = app_module(); child.configure_targets(row['app'])
        child.ARGS = SimpleNamespace(app=row['app'], source=str(source)); child.APP_INFO = row['info']
        child.sources = lambda: frozen
        try:
            ops, _ = child.make_plan(home, None, 'apply', Path(source))
        except ValueError as error:
            row.update(status='conflict', reason=str(error)); continue
        operations.extend(ops); row.update(status='planned', reason='App-local GTK profile will be installed')
    report['summary'] = {name: sum(row['status'] == name for row in report['apps'])
                         for name in ['planned','already-managed','skipped','deferred','conflict']}
    return operations, report


def prepare_removal(home, env=None):
    """Scan ownership, not toolkit guesses: restore every managed app or none."""
    root = home / '.local/state/glass50/installer-flatpak-v1'
    # An uninstalled application can still have owned CSS/overrides to restore.
    if root.is_symlink(): raise ValueError('Flatpak management root is linked')
    if not root.exists(): return [], {'apps': [], 'summary': {'planned': 0}}
    if not root.is_dir(): raise ValueError('Invalid Flatpak management root')
    managed = []
    for folder in sorted(root.iterdir()):
        if folder.is_symlink() or not folder.is_dir() or not valid_id(folder.name):
            raise ValueError('Invalid Flatpak management entry: ' + folder.name)
        child = app_module()
        child.core.safe(folder / 'active.json'); child.core.safe(folder / 'pending.json')
        if (folder / 'pending.json').exists():
            raise ValueError('Recover interrupted Flatpak operation first: ' + folder.name)
        if (folder / 'active.json').exists(): managed.append(folder.name)
    if not managed: return [], {'apps': [], 'summary': {'planned': 0}}
    # Running apps are never killed. Failure to query their state stops planning.
    result = subprocess.run(['flatpak', 'ps', '--columns=application'], env=env,
                            capture_output=True, text=True, timeout=20)
    if result.returncode: raise ValueError(result.stderr.strip() or 'Cannot check running Flatpak apps')
    running = set(result.stdout.splitlines())
    operations, rows = [], []
    for app in managed:
        row = {'app': app, 'status': 'planned'}
        if app in running:
            row.update(status='blocked', reason='App is running; close it and retry')
        else:
            child = app_module(); child.configure_targets(app)
            child.ARGS = SimpleNamespace(app=app)
            try:
                ops, _ = child.make_plan(home, None, 'remove', Path('.'))
                operations.extend(ops)
            except (OSError, ValueError, KeyError, TypeError) as error:
                row.update(status='blocked', reason=str(error))
        rows.append(row)
    report = {'apps': rows, 'summary': {s: sum(r['status'] == s for r in rows) for s in ['planned', 'blocked']}}
    if report['summary']['blocked']:
        raise ValueError('Flatpak batch removal stopped before changes: ' + json.dumps(report, ensure_ascii=False))
    return operations, report


if __name__ == '__main__':
    print(json.dumps(scan(Path.home()), ensure_ascii=False, indent=2))
