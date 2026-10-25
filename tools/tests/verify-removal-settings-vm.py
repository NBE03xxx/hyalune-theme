#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify removal preference choices and rollback using VM-private keyfile homes."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid

assert socket.gethostname() == 'KVM-PC' and os.environ.get('SSH_CONNECTION')
p = argparse.ArgumentParser(); p.add_argument('--package', type=Path, required=True)
a = p.parse_args(); package = a.package.resolve()
root = Path.home() / '.local/state/glass50/phase5-tests' / ('remove-settings-' + uuid.uuid4().hex)
root.mkdir(parents=True, mode=0o700)
checks = []
state = '.local/state/glass50/installer-material-v1'
keys = ['effect-enabled', 'window-material-enabled']
schema = package / 'payload/.local/share/gnome-shell/extensions/glass50-blur@myglass.local/schemas'


def check(name, value):
    checks.append({'name': name, 'passed': bool(value)}); assert value, name


def env(h):
    return dict(os.environ, HOME=str(h), XDG_CONFIG_HOME=str(h / '.config'),
                XDG_DATA_HOME=str(h / '.local/share'), XDG_STATE_HOME=str(h / '.local/state'),
                GSETTINGS_BACKEND='keyfile', GSETTINGS_SCHEMA_DIR=str(schema))


def prefs(h):
    code = "from gi.repository import Gio;import json;s=Gio.Settings.new('org.gnome.shell.extensions.glass50-blur');print(json.dumps({k:(s.get_user_value(k).print_(True) if s.get_user_value(k) is not None else None) for k in ['effect-enabled','window-material-enabled']}))"
    return json.loads(subprocess.check_output([sys.executable, '-c', code], env=env(h), text=True))


def call(h, action, *extra, expected=0):
    r = subprocess.run([sys.executable, str(package / 'manage-material.py'), action,
                        '--test-root', str(h), '--package', str(package), *extra],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == expected, (action, extra, r.returncode, r.stderr)
    return json.loads(r.stdout) if r.stdout else None


for choice in ['keep', 'discard']:
    h = root / choice; h.mkdir()
    call(h, 'apply', '--blur', 'on')
    check(choice + ': initial explicit effect values', prefs(h) == dict.fromkeys(keys, 'true'))
    planned = call(h, 'plan', '--operation', 'remove', '--settings', choice)
    check(choice + ': plan leaves active state and preferences intact',
          (h / state / 'active.json').exists() and prefs(h) == dict.fromkeys(keys, 'true'))
    call(h, 'remove', '--settings', choice)
    check(choice + ': preferences match choice', prefs(h) == dict.fromkeys(keys, 'true' if choice == 'keep' else None))
    check(choice + ': appearance ownership removed and backups retained',
          not (h / state / 'active.json').exists() and len(list((h / state / 'transactions').glob('*/journal.json'))) == 2)

h = root / 'preexisting'; h.mkdir()
for k in keys:
    subprocess.run(['gsettings', 'set', 'org.gnome.shell.extensions.glass50-blur', k, 'false'], env=env(h), check=True)
call(h, 'apply', '--blur', 'on'); call(h, 'remove', '--settings', 'discard')
check('discard restores preexisting values rather than blindly resetting', prefs(h) == dict.fromkeys(keys, 'false'))

h = root / 'independent'; h.mkdir(); call(h, 'apply', '--blur', 'on')
for k in keys:
    subprocess.run(['gsettings', 'set', 'org.gnome.shell.extensions.glass50-blur', k, 'false'], env=env(h), check=True)
call(h, 'remove', '--settings', 'discard')
check('discard preserves independent user preference edits', prefs(h) == dict.fromkeys(keys, 'false'))

for choice in ['keep', 'discard']:
    h = root / ('crash-' + choice); h.mkdir(); call(h, 'apply', '--blur', 'on')
    before = (h / state / 'active.json').read_bytes()
    call(h, 'remove', '--settings', choice, '--crash-after', '3', expected=86)
    call(h, 'recover')
    check(choice + ': interrupted removal recovers ownership and preferences',
          (h / state / 'active.json').read_bytes() == before and prefs(h) == dict.fromkeys(keys, 'true') and not (h / state / 'pending.json').exists())
    call(h, 'remove', '--settings', choice)

r = subprocess.run([sys.executable, str(package / 'manage-material.py'), 'apply', '--settings', 'keep'], capture_output=True)
check('retention rejected outside removal', r.returncode == 2)
print(json.dumps({'status': 'passed', 'root': str(root), 'checks': checks}, indent=2))
