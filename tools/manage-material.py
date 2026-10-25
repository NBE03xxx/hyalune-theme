#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Transactional material and blur installation; common entry: manage-desktop.py."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

# In the package, the unchanged transaction engine sits beside this adapter.
core_path = Path(__file__).with_name('manage-theme.py')
spec = importlib.util.spec_from_file_location('glass50_transactions', core_path)
core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
UUID = 'glass50-blur@myglass.local'
THEME = '.local/share/themes/Glass50-Material-Preview/'
EXT = '.local/share/gnome-shell/extensions/' + UUID + '/'
THEME_FILES = ('gnome-shell/gnome-shell.css', 'gtk-3.0/gtk.css', 'gtk-3.0/gtk-dark.css', 'gtk-4.0/material.css')
EFFECTS = ('rounded-background-blur', 'rounded-mask', 'refresh-gate', 'quick-settings-blur',
           'runtime-context', 'window-backdrop-source', 'window-material', 'window-material-commit')
EXT_FILES = ('extension.js', 'schemas/gschemas.compiled',
             'schemas/org.gnome.shell.extensions.glass50-blur.gschema.xml', *('effects/' + n + '.js' for n in EFFECTS), 'metadata.json')
TARGETS = tuple(THEME + n for n in THEME_FILES) + tuple(EXT + n for n in EXT_FILES)
STATE = '.local/state/glass50/installer-material-v1'
BEGIN = b'/* Glass50 managed: material preview begin */'
END = b'/* Glass50 managed: material preview end */'
core.THEME = ''; core.FILES = TARGETS; core.STATE = STATE; core.ACTIVE = STATE + '/active.json'
core.KEYS = {
 'gtk-theme': ('org.gnome.desktop.interface', 'gtk-theme', "'Glass50-Material-Preview'"),
 'color-scheme': ('org.gnome.desktop.interface', 'color-scheme', "'prefer-dark'"),
 'shell-theme': ('org.gnome.shell.extensions.user-theme', 'name', "'Glass50-Material-Preview'"),
 'effect-enabled': ('org.gnome.shell.extensions.glass50-blur', 'effect-enabled', None),
 'window-material-enabled': ('org.gnome.shell.extensions.glass50-blur', 'window-material-enabled', None),
 'enabled-extensions': ('org.gnome.shell', 'enabled-extensions', None),
}
LEGACY_SUPPORT = {'manage-material.py', 'manage-theme.py', 'INSTALL.md', 'LICENSE', 'LICENSES.md'}
PREVIOUS_SUPPORT = LEGACY_SUPPORT | {'INSTALLER-ROADMAP.md'}
FLATPAK_SUPPORT = PREVIOUS_SUPPORT | {'flatpak-discovery.py'}
TRIAL_SUPPORT = FLATPAK_SUPPORT | {'manage-t16.py'}
SUPPORT = TRIAL_SUPPORT | {'manage-desktop.py', 'desktop-context.py'}
INSTALL_LAYERS = [1, 2, 3]
LAYERS = [
    {'id': 1, 'component': 'gnome-shell', 'scope': 'user-session', 'status': 'included'},
    {'id': 2, 'component': 'gtk3-gtk4-libadwaita', 'scope': 'user-session', 'status': 'included'},
    {'id': 3, 'component': 'shell-extension', 'scope': 'user-session', 'status': 'included'},
    {'id': 4, 'component': 'gdm', 'scope': 'system-login', 'status': 'planned'},
]
ARGS = None


def layer_info():
    # Metadata only. A planned system-login component has no payload or handler.
    return {'layers': LAYERS, 'install_layers': INSTALL_LAYERS}


def load_package(path):
    core.safe(path / 'manifest.json'); m = json.loads((path / 'manifest.json').read_text())
    if m.get('format') != 2 or m.get('component') != 'material-preview' or set(m.get('files', {})) != set(TARGETS):
        core.fail('Unknown material package format/targets.')
    # Accept earlier format-2 packages without this metadata. Explicit layer
    # declarations must match the supported profile; GDM cannot be selected.
    if any(k in m for k in layer_info()) and any(m.get(k) != v for k, v in layer_info().items()):
        core.fail('Unsupported layer declaration: layers 1-3 only; GDM is planned.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', m.get('version', '')) or set(m.get('support_files', {})) not in (SUPPORT, TRIAL_SUPPORT, FLATPAK_SUPPORT, PREVIOUS_SUPPORT, LEGACY_SUPPORT):
        core.fail('Invalid material version/support list.')
    for n, digest in m['support_files'].items():
        core.safe(path / n)
        if core.digest((path / n).read_bytes()) != digest: core.fail('Support hash mismatch: ' + n)
    payload = {}
    for n in TARGETS:
        p = path / 'payload' / n; core.safe(p); data = p.read_bytes()
        if core.digest(data) != m['files'][n]: core.fail('Payload hash mismatch: ' + n)
        payload[n] = core.image(data)
    meta = json.loads(core.contents(payload[EXT + 'metadata.json']))
    if meta.get('uuid') != UUID or meta.get('shell-version') != ['50'] or meta.get('version') not in (3, 4, 5, 6, 7) or m.get('extension_version') != meta.get('version'):
        core.fail('Unexpected extension identity/version.')
    return m, payload


class Settings(core.Settings):
    def __init__(self, real_home):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        source = Gio.SettingsSchemaSource.get_default()
        dirs = [real_home / '.local/share/gnome-shell/extensions' / core.USER_THEMES / 'schemas',
                Path(ARGS.package) / 'payload' / EXT / 'schemas']
        dirs.append(Path('/usr/share/gnome-shell/extensions') / core.USER_THEMES / 'schemas')
        for p in dirs:
            if p.is_dir(): source = Gio.SettingsSchemaSource.new_from_directory(str(p), source, False)
        self.items = {}
        for alias, (sid, key, _) in core.KEYS.items():
            schema = source.lookup(sid, True)
            if schema is None: core.fail('Missing schema: ' + sid)
            self.items[alias] = (Gio.Settings.new_full(schema, None, None), key)

    def effective(self, alias):
        s, key = self.items[alias]; return s.get_value(key).unpack()

    def array(self, items):
        return self.GLib.Variant('as', items).print_(True)

    def put(self, alias, value):
        super().put(alias, value)
        if alias != 'enabled-extensions' or ARGS.test_root: return
        enabled = UUID in self.effective(alias)
        if enabled: return  # Code activation is verified after the VM re-login.
        bus = self.Gio.bus_get_sync(self.Gio.BusType.SESSION, None)
        owner = bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus',
            'org.freedesktop.DBus','NameHasOwner',self.GLib.Variant('(s)',('org.gnome.Shell.Extensions',)),
            None,self.Gio.DBusCallFlags.NONE,3000,None).unpack()[0]
        if not owner: return  # Restore saved dconf values even outside a running Shell.
        for _ in range(80):
            result = bus.call_sync('org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions',
                'org.gnome.Shell.Extensions', 'GetExtensionInfo', self.GLib.Variant('(s)', (UUID,)), None,
                self.Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
            if (result.get('state') == 1) == enabled: return
            time.sleep(.1)
        core.fail('Extension activation/deactivation did not complete; transaction retained/rolled back.')


core.Settings = Settings
core.load_package = load_package


def hashes(root):
    for node in (root, *root.parents):
        if node.is_symlink(): core.fail('Symlink preview root: ' + str(node))
    if not root.exists(): return {}
    result = {}
    for p in sorted(root.rglob('*')):
        core.safe(p) if not p.is_dir() else None
        if p.is_symlink(): core.fail('Symlink in preview tree: ' + str(p))
        if p.is_file(): result[str(p.relative_to(root))] = core.digest(p.read_bytes())
    return result


def adoption(home):
    state = Path(ARGS.adopt_preview).absolute()
    if state.parent != home / '.local/state/glass50' or not re.fullmatch(r'material-deploy-[a-z0-9-]+', state.name):
        core.fail('Adoption requires this HOME material-deploy- record.')
    for n in ['before.json', 'staged.json']: core.safe(state / n)
    before = json.loads((state / 'before.json').read_text()); staged = json.loads((state / 'staged.json').read_text())
    if hashes(home / THEME) != staged['theme_sha256'] or hashes(home / EXT) != staged['extension_sha256']:
        core.fail('Preview files differ from saved deployment; preserve them before adoption.')
    for n in ['extension-before', 'extension-retired']:
        if hashes(state / n) != before['extension_sha256']: core.fail('Historical extension backup changed.')
    legacy = home / '.local/state/glass50/installer-v1/active.json'; core.safe(legacy)
    if not legacy.is_file() or core.digest(legacy.read_bytes()) != before['stable_installer_sha256']:
        core.fail('Legacy ownership state changed; adoption stopped.')
    return str(state)


def make_plan(home, settings, action, package):
    if action == 'remove':
        flatpak_state = home / '.local/state/glass50/installer-flatpak-v1'
        if flatpak_state.is_symlink(): core.fail('Flatpak state is a symlink.')
        for pattern in ['*/active.json', '*/pending.json']:
            for state in flatpak_state.glob(pattern):
                core.safe(state)
                if state.name == 'pending.json' or state.parent.name not in getattr(core, 'composite_flatpak_removals', ()):
                    core.fail('Use ./install.sh remove to scan and restore managed Flatpak themes: ' + state.parent.name)
    legacy_pending = home / '.local/state/glass50/installer-v1/pending.json'; core.safe(legacy_pending)
    if legacy_pending.exists(): core.fail('Legacy installation is pending; recover it before material changes.')
    old_state = core.snapshot(home / core.ACTIVE)
    active = json.loads(core.contents(old_state)) if old_state else None
    if active:
        if active.get('format') != 1 or active.get('component') != 'material-preview' or set(active.get('originals', {})) != set(TARGETS) or set(active.get('installed', {})) != set(TARGETS) or set(active.get('settings_before', {})) != set(core.KEYS):
            core.fail('Invalid material ownership manifest.')
    if action == 'apply' and active: core.fail('Already managed: use update.')
    if action in ['update', 'remove'] and not active: core.fail('No managed material installation.')
    if ARGS.adopt_preview and (action != 'apply' or active): core.fail('Adoption is only for initial apply.')
    record = adoption(home) if ARGS.adopt_preview else None
    if action != 'remove': manifest, payload = load_package(package)
    operations, notes = [], []
    def file_op(n, a, b):
        if a != b: operations.append({'kind': 'file', 'name': n, 'before': a, 'after': b})
    current_values = {k: settings.get(k) for k in core.KEYS}
    enabled_before = settings.effective('enabled-extensions')
    disabled = settings.array([n for n in enabled_before if n != UUID])
    # Removal stops only our UUID before deleting/restoring code. Updates stage
    # complete files with metadata last; a new login loads the new code.
    extension_current = current_values['enabled-extensions']
    if action == 'remove' and UUID in enabled_before:
        operations.append({'kind': 'setting', 'name': 'enabled-extensions', 'before': extension_current, 'after': disabled})
        extension_current = disabled
    for n in TARGETS:
        now = core.snapshot(home / n)
        if active and now != active['installed'][n]: core.fail('User modification: ' + n)
        if not active and now is not None and now != payload[n] and not record:
            if core.contents(now) != core.contents(payload[n]): core.fail('Unmanaged different file: ' + n)
        if action != 'remove' and now is not None: payload[n]['mode'] = now['mode']
        file_op(n, now, active['originals'][n] if action == 'remove' else payload[n])
    css_before = core.snapshot(home / core.CSS); data = core.contents(css_before)
    desired = BEGIN + b'\n@import url("' + (home / THEME / 'gtk-4.0/material.css').as_uri().encode() + b'");\n' + END
    original_begin, original_end = core.BEGIN, core.END
    core.BEGIN, core.END = BEGIN, END
    try: found = core.locate(data)
    finally: core.BEGIN, core.END = original_begin, original_end
    if found is not None and found != desired: core.fail('Modified/unknown material CSS block.')
    if active and found != desired: core.fail('Owned material CSS block missing.')
    if action != 'remove':
        new_data = data if found else desired + b'\n' + data
        css_after = core.image(new_data, css_before['mode'] if css_before else 0o644)
    elif css_before == active['css_installed']:
        css_after = active['css_original']
    else:
        original = core.contents(active['css_original'])
        if BEGIN in original:
            # Initial preview adoption retains that exact preexisting import.
            replacement = desired
        else: replacement = b''
        new_data = data.replace(desired, replacement, 1)
        if not replacement and data.startswith(desired + b'\n'): new_data = data[len(desired) + 1:]
        css_after = core.image(new_data, css_before['mode'])
        notes.append('Independent GTK4 CSS edits preserved.')
    file_op(core.CSS, css_before, css_after)
    targets = {}
    for k, (_, _, value) in core.KEYS.items():
        if k == 'enabled-extensions': continue
        now = current_values[k]
        if action == 'remove':
            if k in ['effect-enabled', 'window-material-enabled'] and getattr(ARGS, 'settings', 'discard') == 'keep':
                notes.append('Glass50 effect preference retained: ' + k)
                continue
            if now != active['settings_installed'][k]: notes.append('User setting preserved: ' + k); continue
            value = active['settings_before'][k]
        elif k in ['effect-enabled', 'window-material-enabled']:
            value = ('true' if ARGS.blur == 'on' else 'false') if ARGS.blur != 'keep' else (active['settings_installed'][k] if active else now)
        elif active and now != active['settings_installed'][k]:
            core.fail('User setting changed: ' + k)
        if action != 'remove' and active and k in ['effect-enabled', 'window-material-enabled'] and now != active['settings_installed'][k]:
            core.fail('User effect setting changed; remove preserves it.')
        targets[k] = value
        if now != value: operations.append({'kind': 'setting', 'name': k, 'before': now, 'after': value})
    if action == 'remove':
        original_list = active['enabled_before_effective']
        final_list = list(enabled_before)
        # Restore only our membership; preserve independent changes to other UUIDs.
        current_member = UUID in final_list
        installed_member = UUID in active['enabled_installed_effective']
        if current_member != installed_member:
            notes.append('User changed preview extension membership; preserved.')
        elif UUID in original_list and not current_member:
            final_list.insert(min(original_list.index(UUID), len(final_list)), UUID)
        elif UUID not in original_list:
            final_list = [n for n in final_list if n != UUID]
        if final_list == original_list and current_values['enabled-extensions'] == active['settings_installed']['enabled-extensions']:
            final_enabled = active['settings_before']['enabled-extensions']
        else: final_enabled = settings.array(final_list)
    else:
        final_list = list(enabled_before)
        if ARGS.blur == 'on' and UUID not in final_list: final_list.append(UUID)
        if ARGS.blur == 'off': final_list = [n for n in final_list if n != UUID]
        final_enabled = current_values['enabled-extensions'] if final_list == enabled_before else settings.array(final_list)
    if extension_current != final_enabled:
        operations.append({'kind': 'setting', 'name': 'enabled-extensions', 'before': extension_current, 'after': final_enabled})
    if action == 'remove': after_state = None
    else:
        targets['enabled-extensions'] = final_enabled
        originals = active['originals'] if active else {n: core.snapshot(home / n) for n in TARGETS}
        extension_changed = any(n.startswith(EXT) and core.snapshot(home / n) != payload[n] for n in TARGETS)
        new_state = {'format': 1, 'component': 'material-preview', 'version': manifest['version'], 'package_files': manifest['files'],
            'originals': originals, 'installed': payload, 'settings_before': active['settings_before'] if active else current_values,
            'settings_installed': targets, 'enabled_before_effective': active['enabled_before_effective'] if active else enabled_before,
            'enabled_installed_effective': final_list, 'css_original': active['css_original'] if active else css_before,
            'css_installed': active['css_installed'] if active else css_after, 'adopted_preview': active.get('adopted_preview') if active else record,
            'relogin_from_pid': (subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip() if not ARGS.test_root else 'private')
                if extension_changed else (active.get('relogin_from_pid') if active else None)}
        if active and 'flatpak_auto' in active: new_state['flatpak_auto'] = active['flatpak_auto']
        after_state = core.image(core.canonical(new_state), 0o600)
    file_op(core.ACTIVE, old_state, after_state)
    notes.append('Wayland: log out and log in after extension code changes; disk state is not proof of loaded code.')
    notes.append('Layers 1-3 are bundled; layer 4 (GDM) is planned and is not installed.')
    return operations, notes


core.make_plan = make_plan


def status_extra(home, active):
    result = {'component': 'material-preview', 'expected_extension_version': 7,
              'runtime_note': 'Extension info is metadata; verify code after logging out and in.', **layer_info()}
    if active and 'flatpak_auto' in active: result['flatpak_auto_at_install'] = active['flatpak_auto']
    disk = home / EXT / 'metadata.json'; core.safe(disk)
    result['disk_extension_version'] = json.loads(disk.read_text()).get('version') if disk.exists() else None
    if not ARGS.test_root:
        pid = subprocess.run(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],capture_output=True,text=True).stdout.strip()
        result['shell_pid'] = pid if pid.isdecimal() else None
        result['relogin_required'] = bool(active and active.get('relogin_from_pid') == pid)
    return result


core.status_extra = status_extra


def main():
    global ARGS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['layers','plan','apply','update','remove','recover','status'])
    p.add_argument('--package', default=str(Path(__file__).resolve().parent))
    p.add_argument('--operation', choices=['apply','update','remove'], default='apply')
    p.add_argument('--blur', choices=['keep','on','off'], default='keep')
    p.add_argument('--adopt-preview')
    p.add_argument('--settings', choices=['keep', 'discard'], default='discard',
                   help='remove: keep effect preferences, or discard by restoring their pre-install values; backups are retained')
    p.add_argument('--test-root')
    p.add_argument('--fail-after', type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument('--crash-after', type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument('--crash-after-commit', action='store_true', help=argparse.SUPPRESS)
    ARGS = p.parse_args(); ARGS.package = str(Path(ARGS.package).absolute())
    if ARGS.settings != 'discard' and (ARGS.operation if ARGS.action == 'plan' else ARGS.action) != 'remove':
        p.error('--settings keep is only available for removal')
    try:
        if ARGS.action != 'layers' and globals().get('configure_adapter'): configure_adapter()
        elif ARGS.action != 'layers' and not getattr(core,'explicit_adapter',False):
            # A saved public snapshot must recover its own complete journal,
            # including GTK entries/markers, even when invoked by the old name.
            home = Path(ARGS.test_root) if ARGS.test_root else Path(__import__('pwd').getpwuid(os.getuid()).pw_dir)
            records=[]
            for name in ['active.json','pending.json']:
                value=core.snapshot(home/core.STATE/name)
                if value: records.append(json.loads(core.contents(value)))
            owners=[]
            for record in records:
                owners.append(record)
                for op in record.get('operations',[]):
                    if op.get('kind')=='file' and op.get('name')==core.ACTIVE:
                        for stage in ['before','after']:
                            if op.get(stage): owners.append(json.loads(core.contents(op[stage])))
            if any('desktop' in owner or owner.get('target')=='t16-trial' for owner in owners):
                helper=Path(__file__).with_name('manage-desktop.py')
                spec=importlib.util.spec_from_file_location('owned_desktop',helper)
                adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
                operation=ARGS.operation if ARGS.action=='plan' else ARGS.action
                real=adapter.context().guard(restoring=operation in ('remove','recover','status'))
                from types import SimpleNamespace
                adapter.configure(SimpleNamespace(core=core,ARGS=ARGS,TARGETS=TARGETS,UUID=UUID,
                    make_plan=make_plan,status_extra=status_extra),real)
        if ARGS.action == 'layers':
            # Safe to inspect on any machine: no package, GI, VM or settings access.
            print(core.canonical(layer_info()).decode(), end='')
            return 0
        core.guard()
        if not ARGS.test_root and (ARGS.operation if ARGS.action=='plan' else ARGS.action) not in ('remove','recover','status') and not subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip().isdecimal():
            core.fail('Normal Shell must be unique; finish private Shell probes first.')
        load_package(Path(ARGS.package))
        if ARGS.action == 'recover':
            home = Path(ARGS.test_root) if ARGS.test_root else Path(__import__('pwd').getpwuid(os.getuid()).pw_dir)
            pending = home / core.STATE / 'pending.json'; core.safe(pending)
            helper = Path(__file__).with_name('flatpak-discovery.py')
            if pending.exists() and helper.is_file():
                spec = importlib.util.spec_from_file_location('composite_recovery', helper)
                discovery = importlib.util.module_from_spec(spec); spec.loader.exec_module(discovery)
                journal = json.loads(pending.read_text())
                core.FILES = tuple(discovery.recovery_paths(journal['operations'], set(core.FILES) | {core.CSS, core.ACTIVE}, core.KEYS))
        core.run(ARGS)
        return 0
    except Exception as e:
        print('Glass50 material: ' + str(e), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
