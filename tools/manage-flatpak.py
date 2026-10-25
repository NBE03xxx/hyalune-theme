#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Opt-in GTK CSS for one Flatpak app, with app-local files and exact recovery."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location('flatpak_transactions', Path(__file__).with_name('manage-theme.py'))
core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
VERSION = '0.1.0-vm-preview.5'
BEGIN = b'/* Glass50 managed: flatpak GTK begin */'
END = b'/* Glass50 managed: flatpak GTK end */'
DENY = ('xdg-config/gtk-3.0', 'xdg-config/gtk-4.0')
ARGS = None
CSS_FILES = {}
OVERRIDE = ''
APP_INFO = {}


def command(*args):
    p = subprocess.run(['flatpak', *args], capture_output=True, text=True, timeout=20)
    if p.returncode: core.fail(p.stderr.strip() or 'Flatpak command failed')
    return p.stdout.strip()


def validate_runtime(info):
    if info['runtime'].startswith('org.kde.Platform/'):
        core.fail('KDE/Qt runtime: this GTK profile is not supported; no changes made.')


def read_info(app):
    return {k: command('info', flag, app) for k, flag in
            [('ref', '--show-ref'), ('origin', '--show-origin'), ('runtime', '--show-runtime'), ('commit', '--show-commit')]}


def override_image(before):
    from gi.repository import GLib
    data = core.contents(before)
    k = GLib.KeyFile()
    if data:
        k.load_from_data(data.decode(), len(data), GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    items = k.get_string_list('Context', 'filesystems') if k.has_group('Context') and 'filesystems' in k.get_keys('Context')[0] else []
    result = [v for v in items if v.lstrip('!').split(':', 1)[0] not in DENY]
    result += ['!' + n for n in DENY]
    if list(items) == result: return before
    k.set_string_list('Context', 'filesystems', result)
    return core.image(k.to_data()[0].encode(), before['mode'] if before else 0o600)


def block(data):
    return BEGIN + b'\n' + data.rstrip(b'\n') + b'\n' + END


def locate(data):
    b, e = core.BEGIN, core.END
    core.BEGIN, core.END = BEGIN, END
    try: return core.locate(data)
    finally: core.BEGIN, core.END = b, e


def sources():
    root = Path(ARGS.source).absolute()
    paths = {'gtk3': root / 'gtk-3.0/gtk.css', 'gtk4': root / 'gtk-4.0/flatpak.css'}
    result = {}
    for k, p in paths.items():
        core.safe(p); data = p.read_bytes()
        if not data or BEGIN in data or END in data: core.fail('Invalid source CSS: ' + str(p))
        result[k] = data
    return result


def make_plan(home, settings, action, package):
    old_state = core.snapshot(home / core.ACTIVE)
    active = json.loads(core.contents(old_state)) if old_state else None
    if active and (active.get('component') != 'flatpak-gtk' or active.get('format') != 1 or
                   active.get('app') != ARGS.app or set(active.get('originals', {})) != set(CSS_FILES.values())):
        core.fail('Invalid Flatpak ownership manifest.')
    if action == 'apply' and active: core.fail('Already managed: use update.')
    if action in ['update', 'remove'] and not active: core.fail('No managed Flatpak theme for this app.')
    css = sources() if action != 'remove' else {}
    operations = []; originals = {}; blocks = {}; baseline = {}; separators = {}
    def change(name, before, after):
        if before != after: operations.append({'kind': 'file', 'name': name, 'before': before, 'after': after})
    for toolkit, name in CSS_FILES.items():
        now = core.snapshot(home / name); data = core.contents(now); found = locate(data)
        if active:
            if found != core.contents(active['blocks'][name]): core.fail('Owned CSS block modified or missing: ' + name)
            original = active['originals'][name]; separator = active['separators'][name].encode()
        else:
            if found: core.fail('Unmanaged Glass50 block: ' + name)
            original = now; separator = b'\n' if data and not data.endswith(b'\n') else b''
        originals[name] = original; separators[name] = separator.decode()
        if action == 'remove':
            if now == active['baseline'][name]: after = original
            else:
                owned = separator + found
                after_data = data.replace(owned if owned in data else found, b'', 1)
                after = core.image(after_data, now['mode'])
        else:
            desired = block(css[toolkit]); blocks[name] = core.image(desired)
            after_data = data.replace(found, desired, 1) if found else data + separator + desired
            mode = now['mode'] if now else 0o644
            after = core.image(after_data, mode)
            baseline[name] = core.image(core.contents(original) + separator + desired, original['mode'] if original else 0o644)
        change(name, now, after)
    now = core.snapshot(home / OVERRIDE)
    if active and now != active['override_installed']:
        core.fail('App permissions edited after apply; keep backups and resolve the conflict: ' + OVERRIDE)
    override_before = active['override_original'] if active else now
    override_after = override_before if action == 'remove' else override_image(now)
    change(OVERRIDE, now, override_after)
    state = None if action == 'remove' else core.image(core.canonical({
        'format': 1, 'component': 'flatpak-gtk', 'app': ARGS.app, 'version': VERSION,
        'app_info': APP_INFO, 'originals': originals, 'blocks': blocks, 'baseline': baseline,
        'separators': separators, 'override_original': override_before, 'override_installed': override_after,
        'source_sha256': {k: core.digest(v) for k, v in css.items()}}), 0o600)
    change(core.ACTIVE, old_state, state)
    return operations, [
        'GTK3/GTK4 CSS is app-local; Qt/Electron/custom rendering is not guaranteed.',
        'Only this app denies the two shared host GTK config directories; no new filesystem grants.',
        'Global overrides, GTK_THEME, other app files and the desktop theme are unchanged.',
        'Close and reopen the selected app after applying or restoring.']


class NoSettings:
    def __init__(self, _home): pass


def configure_targets(app):
    global CSS_FILES, OVERRIDE
    CSS_FILES = {k: '.var/app/' + app + '/config/' + n + '/gtk.css' for k, n in [('gtk3','gtk-3.0'),('gtk4','gtk-4.0')]}
    OVERRIDE = '.local/share/flatpak/overrides/' + app
    core.THEME = ''; core.FILES = (*CSS_FILES.values(), OVERRIDE); core.CSS = CSS_FILES['gtk4']
    core.STATE = '.local/state/glass50/installer-flatpak-v1/' + app; core.ACTIVE = core.STATE + '/active.json'
    core.KEYS = {}; core.Settings = NoSettings; core.require_user_themes = False
    core.make_plan = make_plan
    core.status_extra = lambda home, active: {'component':'flatpak-gtk','app':app,'files':list(CSS_FILES.values()),'permissions_override':OVERRIDE,'parent_pending':(home / '.local/state/glass50/installer-material-v1/pending.json').exists()}
    def parent_guard(home, action):
        if action == 'status': return
        pending = home / '.local/state/glass50/installer-material-v1/pending.json'
        core.safe(pending)
        if pending.exists(): core.fail('Base installation is pending; run ./install.sh recover first.')
    core.component_guard = parent_guard


def main():
    global ARGS, CSS_FILES, OVERRIDE, APP_INFO
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', nargs='?', choices=['scan','list','plan','apply','update','remove','recover','status'])
    p.add_argument('--target', choices=['desktop', 'vm', 't16-trial'], default='desktop', help=argparse.SUPPRESS)
    p.add_argument('--app', help='One explicit installed Flatpak app ID')
    p.add_argument('--operation', choices=['apply','update','remove'], default='apply')
    p.add_argument('--source', default=str(Path(__file__).resolve().parent.parent / 'build/Glass50-Material-Preview'))
    p.add_argument('--test-root', help=argparse.SUPPRESS)
    p.add_argument('--fail-after', type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument('--crash-after', type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument('--crash-after-commit', action='store_true', help=argparse.SUPPRESS)
    ARGS = p.parse_args()
    if ARGS.action is None: p.print_help(); return 0
    if ARGS.action == 'scan':
        spec = importlib.util.spec_from_file_location('flatpak_discovery', Path(__file__).with_name('flatpak-discovery.py'))
        discovery = importlib.util.module_from_spec(spec); spec.loader.exec_module(discovery)
        print(json.dumps(discovery.scan(Path(ARGS.test_root) if ARGS.test_root else Path.home()), ensure_ascii=False, indent=2))
        return 0
    if ARGS.target == 't16-trial':
        spec=importlib.util.spec_from_file_location('t16_guard',Path(__file__).with_name('manage-t16.py'))
        t16=importlib.util.module_from_spec(spec);spec.loader.exec_module(t16);core.guard=t16.guard
    spec=importlib.util.spec_from_file_location('desktop_context',Path(__file__).with_name('desktop-context.py'))
    desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)
    operation=ARGS.operation if ARGS.action=='plan' else ARGS.action
    common=lambda: desktop.guard(restoring=operation in ('remove','recover','status'))
    common()
    if ARGS.target != 't16-trial': core.guard=common
    core.guard()
    if ARGS.action == 'list':
        print(command('list','--app','--columns=application,origin,runtime,installation')); return 0
    if not ARGS.app or len(ARGS.app) > 255 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*){2,}', ARGS.app):
        core.fail('Choose one explicit app ID with --app; no all-app/global mode.')
    action = ARGS.operation if ARGS.action == 'plan' else ARGS.action
    if action in ['apply','update']:
        APP_INFO = read_info(ARGS.app)
        validate_runtime(APP_INFO)
    if ARGS.action in ['apply','update','remove','recover'] and not ARGS.test_root:
        # Flatpak can retain instance metadata briefly after its child exits.
        for _ in range(20):
            if ARGS.app not in command('ps','--columns=application').splitlines(): break
            time.sleep(.1)
        else: core.fail('Close the selected app before changing or recovering its theme.')
    configure_targets(ARGS.app)
    ARGS.package = ARGS.source
    core.run(ARGS)
    return 0


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as e:
        print('Glass50 Flatpak: ' + str(e), file=sys.stderr); sys.exit(1)
