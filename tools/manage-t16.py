#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit T16 trial adapter; preserve old GTK links and extension membership."""
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import socket
import subprocess
import sys
import tempfile

LINKS = ('.config/gtk-4.0/gtk.css', '.config/gtk-4.0/gtk-dark.css')
INCLUDE = '.config/gtk-4.0/glass50-t16-managed.css'
RUNTIME = '.local/state/glass50/installer-material-v1/t16-runtime.json'
CONFLICTS = ('blur-my-shell@aunetx', 'dash-to-dock@micxgx.gmail.com',
             'just-perfection-desktop@just-perfection', 'top-panel-logo@jmpegi.github.com',
             'logomenu@aryan_k')


def guard():
    if os.geteuid() == 0 or os.getuid() != 1000 or socket.gethostname() != 'T16':
        raise ValueError('Explicit T16 trial requires its desktop user (no sudo).')
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'LENOVO' or Path('/sys/class/dmi/id/product_name').read_text().strip() != '21QNCTO1WW':
        raise ValueError('Unrecognized T16 hardware.')
    root = subprocess.check_output(['findmnt', '-no', 'SOURCE', '/'], text=True).strip()
    version = subprocess.check_output(['gnome-shell', '--version'], text=True).strip()
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    expected_home = Path('/home') / pwd.getpwuid(os.getuid()).pw_name
    if root != '/dev/nvme0n1p2' or home != expected_home or not re.fullmatch(r'GNOME Shell 50\.\d+', version):
        raise ValueError('Expected the verified T16 root, desktop HOME and GNOME Shell 50.x.')
    return home


def configure(m):
    core = m.core
    core.explicit_adapter = True
    core.guard = guard
    core.CSS = INCLUDE
    core.FILES = (*m.TARGETS, *LINKS, RUNTIME)
    original_snapshot, original_write = core.snapshot, core.write

    def snapshot(path):
        if any(str(path).endswith('/' + n) for n in LINKS) and path.is_symlink():
            core.safe(path.parent / '.glass50-parent-check')
            return {'symlink': os.readlink(path)}
        return original_snapshot(path)

    def write(path, value):
        # Link replacement is confined to these two known GTK entry points.
        if not any(str(path).endswith('/' + n) for n in LINKS):
            return original_write(path, value)
        core.safe(path.parent / '.glass50-parent-check')
        if path.exists() and not path.is_file() and not path.is_symlink():
            core.fail('Unexpected GTK entry type: ' + str(path))
        if value is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            core.safe(path.parent / '.glass50-parent-check')
            fd, temporary = tempfile.mkstemp(prefix='.glass50-t16-', dir=path.parent)
            try:
                if 'symlink' in value:
                    os.close(fd); os.unlink(temporary)
                    if set(value) != {'symlink'} or not isinstance(value['symlink'], str):
                        core.fail('Invalid saved GTK link')
                    os.symlink(value['symlink'], temporary)
                else:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(core.contents(value)); os.fchmod(f.fileno(), value['mode']); f.flush(); os.fsync(f.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.lexists(temporary): os.unlink(temporary)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    core.snapshot, core.write = snapshot, write
    base_plan, base_status = m.make_plan, m.status_extra

    def make_plan(home, settings, action, package):
        saved = snapshot(home / core.ACTIVE)
        active = json.loads(core.contents(saved)) if saved else None
        if active and active.get('target') != 't16-trial':
            core.fail('This is not a managed T16 trial; do not adopt another target.')
        if not active and action == 'apply' and m.ARGS.blur != 'off':
            core.fail('Begin T16 trial with --blur off, then update --blur on.')
        # Preserve the user's full list before the native planner filters our UUID.
        current_enabled = settings.effective('enabled-extensions')
        current_raw = settings.get('enabled-extensions')
        ops, notes = base_plan(home, settings, action, package)
        owner = next((op for op in ops if op['kind'] == 'file' and op['name'] == core.ACTIVE), None)
        if owner is None: core.fail('Missing ownership operation')
        ops.remove(owner)
        trial = active.get('t16_trial') if active else None
        if action == 'remove':
            for name in [*LINKS, RUNTIME]:
                now = snapshot(home / name)
                if now != trial['installed'][name]: core.fail('T16 trial file edited; backups retained: ' + name)
                ops.append({'kind':'file','name':name,'before':now,'after':trial['originals'][name]})
            installed = active['enabled_installed_effective']
            original = active['enabled_before_effective']
            final = [n for n in current_enabled if n != m.UUID]
            for n in CONFLICTS:
                if n in original and n not in installed and n not in final:
                    final.insert(min(original.index(n), len(final)), n)
            if m.UUID in original and m.UUID not in final: final.append(m.UUID)
            # Preserve independent extension changes; exact original user-value
            # presence returns when no independent membership changed.
            if current_enabled == installed:
                final_value = active['settings_before']['enabled-extensions']
            else: final_value = settings.array(final)
            previous = current_raw
            for op in ops:
                if op['kind']=='setting' and op['name']=='enabled-extensions': previous=op['after']
            if previous != final_value:
                ops.append({'kind':'setting','name':'enabled-extensions','before':previous,'after':final_value})
        else:
            data = json.loads(core.contents(owner['after']))
            original_files = trial['originals'] if trial else {n:snapshot(home/n) for n in [*LINKS,RUNTIME]}
            installed_files = {}
            for n in LINKS:
                after = core.image(('@import url("' + (home / INCLUDE).as_uri() + '");\n').encode())
                now = snapshot(home/n)
                if trial and now != trial['installed'][n]: core.fail('T16 GTK entry edited; backups retained: ' + n)
                if now != after: ops.append({'kind':'file','name':n,'before':now,'after':after})
                installed_files[n]=after
            marker=core.image(core.canonical({'format':1,'target':'t16-trial','host':'T16','root':'/dev/nvme0n1p2'}),0o600)
            now=snapshot(home/RUNTIME)
            if trial and now != trial['installed'][RUNTIME]: core.fail('T16 runtime marker edited')
            if now != marker: ops.append({'kind':'file','name':RUNTIME,'before':now,'after':marker})
            installed_files[RUNTIME]=marker
            # Pause only at initial migration. Later user re-enablement is an
            # independent preference, not a request to pause the extension again.
            final=list(data['enabled_installed_effective'])
            if not trial: final=[n for n in final if n not in CONFLICTS]
            final_value=current_raw if final==current_enabled else settings.array(final)
            # The base planner may already emit an enable operation; replace it
            # with a single change from the real list to the trial list.
            ops=[op for op in ops if not (op['kind']=='setting' and op['name']=='enabled-extensions')]
            # Stop competing appearance extensions before material file writes.
            paused=[n for n in current_enabled if (trial or n not in CONFLICTS) and (n != m.UUID or n in final)]
            paused_value=current_raw if paused==current_enabled else settings.array(paused)
            if current_raw != paused_value:
                ops.insert(0,{'kind':'setting','name':'enabled-extensions','before':current_raw,'after':paused_value})
            if paused_value != final_value:
                ops.append({'kind':'setting','name':'enabled-extensions','before':paused_value,'after':final_value})
            data['target']='t16-trial'
            data['enabled_installed_effective']=final
            data['settings_installed']['enabled-extensions']=final_value
            data['t16_trial']={'originals':original_files,'installed':installed_files,'paused_conflicts':[n for n in CONFLICTS if n in data['enabled_before_effective']]}
            owner['after']=core.image(core.canonical(data),0o600)
        ops.append(owner)
        notes += ['T16 trial: preserve old GTK links/referents and pause only listed appearance extensions.',
                  'GDM, packages, drivers and system files are outside this trial.']
        return ops,notes
    m.make_plan = core.make_plan = make_plan
    m.status_extra = core.status_extra = lambda home, active: {**base_status(home,active),'target':'t16-trial','paused_conflicts':active.get('t16_trial',{}).get('paused_conflicts',[]) if active else []}


def main():
    spec=importlib.util.spec_from_file_location('t16_material',Path(__file__).with_name('manage-material.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    configure(m)
    return m.main()


if __name__=='__main__': sys.exit(main())
