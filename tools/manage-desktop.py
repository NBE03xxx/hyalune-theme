#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generic user-desktop adapter with exact restoration of GTK entries and trials."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile

LINKS = ('.config/gtk-4.0/gtk.css', '.config/gtk-4.0/gtk-dark.css')
INCLUDE = '.config/gtk-4.0/glass50-managed.css'
OLD_INCLUDE = '.config/gtk-4.0/glass50-t16-managed.css'
RUNTIME = '.local/state/glass50/installer-material-v1/runtime.json'
OLD_RUNTIME = '.local/state/glass50/installer-material-v1/t16-runtime.json'
CONFLICTS = ('blur-my-shell@aunetx',)


def context():
    spec = importlib.util.spec_from_file_location('glass50_desktop_context', Path(__file__).with_name('desktop-context.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def configure(m, home):
    core = m.core
    core.explicit_adapter = True
    args = m.ARGS
    action = args.operation if args.action == 'plan' else args.action
    core.guard = lambda: context().guard(restoring=action in ('remove', 'recover', 'status'))
    target_home = Path(args.test_root) if args.test_root else home
    if args.test_root:
        base = home/'.local/state/glass50/phase5-tests'
        if not target_home.is_absolute() or target_home == base or not target_home.is_relative_to(base) or '..' in target_home.parts:
            core.fail('Private test root must be a child of '+str(base))
        for parent in (target_home,*target_home.parents):
            if parent.is_symlink(): core.fail('Linked private test root: '+str(parent))
    # Layout is chosen from ownership, or the interrupted journal's planned
    # owner. Paths remain a closed list, never supplied by the record itself.
    saved = core.snapshot(target_home/core.ACTIVE)
    active = json.loads(core.contents(saved)) if saved else None
    pending = core.snapshot(target_home/core.STATE/'pending.json')
    planned = None
    if pending:
        for op in json.loads(core.contents(pending)).get('operations', []):
            if op.get('kind') == 'file' and op.get('name') == core.ACTIVE :
                value = op.get('after') or op.get('before')
                if value: planned = json.loads(core.contents(value))
    layout_owner = planned or active
    if layout_owner and 'desktop' in layout_owner:
        layout = layout_owner['desktop'].get('layout')
    elif layout_owner and layout_owner.get('target') == 't16-trial': layout = 'legacy-t16'
    elif layout_owner: layout = 'legacy-import'
    else: layout = 'desktop'
    if layout not in ('desktop','legacy-t16','legacy-import'):
        core.fail('Unknown desktop ownership layout; backups retained.')
    if active and active.get('target') not in (None, 'desktop', 't16-trial'):
        core.fail('Unknown managed target; do not adopt its files.')
    include = {'desktop':INCLUDE, 'legacy-t16':OLD_INCLUDE, 'legacy-import':LINKS[0]}[layout]
    extra = (RUNTIME,) if layout == 'legacy-import' else (*LINKS, RUNTIME, OLD_RUNTIME)
    core.CSS = include
    core.FILES = (*m.TARGETS, *extra)
    snapshot, write = core.snapshot, core.write

    def entry_snapshot(path):
        if layout != 'legacy-import' and str(path) in {str(target_home/n) for n in LINKS} and path.is_symlink():
            core.safe(path.parent/'.glass50-entry-parent')
            return {'symlink':os.readlink(path)}
        return snapshot(path)

    def entry_write(path, value):
        if str(path) not in {str(target_home/n) for n in LINKS} or layout == 'legacy-import':
            return write(path,value)
        core.safe(path.parent/'.glass50-entry-parent')
        if os.path.lexists(path) and not path.is_symlink() and not path.is_file():
            core.fail('Unexpected GTK entry type: ' + str(path))
        if value is None: path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            core.safe(path.parent/'.glass50-entry-parent')
            fd, name = tempfile.mkstemp(prefix='.glass50-entry-',dir=path.parent)
            try:
                if 'symlink' in value:
                    if set(value) != {'symlink'} or not isinstance(value['symlink'],str): core.fail('Invalid saved GTK link')
                    os.close(fd); os.unlink(name); os.symlink(value['symlink'],name)
                else:
                    with os.fdopen(fd,'wb') as stream:
                        stream.write(core.contents(value));os.fchmod(stream.fileno(),value['mode']);stream.flush();os.fsync(stream.fileno())
                os.replace(name,path)
            finally:
                if os.path.lexists(name): os.unlink(name)
        directory = os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    core.snapshot, core.write = entry_snapshot, entry_write
    base_plan, base_status = m.make_plan, m.status_extra

    def make_plan(home, settings, operation, package):
        raw = entry_snapshot(home/core.ACTIVE)
        old = json.loads(core.contents(raw)) if raw else None
        descriptor = old.get('desktop') if old else None
        trial = old.get('t16_trial') if old else None
        if old and old.get('target') == 't16-trial' and not trial: core.fail('Missing trial restoration data.')
        if not old and operation != 'remove':
            conflicts = sorted(set(settings.effective('enabled-extensions')) & set(CONFLICTS))
            if conflicts: core.fail('先に競合するぼかし拡張を無効化してください: ' + ', '.join(conflicts))
            if layout == 'desktop' and entry_snapshot(home/include) is not None:
                core.fail('Unmanaged Glass50 include exists; preserve/inspect it before applying.')
        # Keep the original trial data verbatim. The public adapter never pauses
        # the user's dock/logo again, and removal still restores paused UUIDs.
        operations, notes = base_plan(home,settings,operation,package)
        owner = next((op for op in operations if op['kind']=='file' and op['name']==core.ACTIVE),None)
        if owner is None:
            # A legacy update can be byte-identical until the adapter adds its
            # ownership/runtime metadata. The core correctly emits no no-op.
            if raw is None: core.fail('Missing desktop ownership operation.')
            owner = {'kind':'file','name':core.ACTIVE,'before':raw,'after':raw}
        else: operations.remove(owner)
        enabling = [op for op in operations if operation != 'remove' and op['kind']=='setting' and op['name']=='enabled-extensions']
        operations = [op for op in operations if op not in enabling]
        originals = dict(descriptor['originals']) if descriptor else {}
        referents = dict(descriptor.get('referents',{})) if descriptor else {}
        installed = {}
        if trial and not descriptor:
            originals.update(trial['originals'])
        for name in extra:
            now = entry_snapshot(home/name)
            if descriptor and now != descriptor['installed'][name]: core.fail('Managed desktop entry edited: '+name)
            if trial and not descriptor and name in trial['installed'] and now != trial['installed'][name]:
                core.fail('Trial GTK/runtime entry edited: '+name)
            if name not in originals: originals[name] = now
            if operation == 'remove':
                after = originals[name]
            elif name in LINKS:
                after = core.image(('@import url("'+(home/include).as_uri()+'");\n').encode(), now.get('mode',0o644) if now else 0o644)
                if not old and now and 'symlink' in now:
                    source = (home/name).resolve(strict=True)
                    if not source.is_file() or source.stat().st_size > 8*1024*1024:
                        core.fail('GTK link must refer to a regular CSS file of at most 8 MiB: '+name)
                    # Preserve bytes for emergency inspection without ever
                    # writing through or restoring over this unowned referent.
                    referents[name] = {'path':str(source),'saved':core.image(source.read_bytes(),stat.S_IMODE(source.stat().st_mode))}
            elif name == RUNTIME:
                after = core.image(core.canonical({'format':1,'target':'desktop','shell_major':50}),0o600)
                if not old and now is not None: core.fail('Unmanaged desktop runtime marker exists.')
            else:
                after = now  # Retain the historical trial marker until removal.
                if not old and now is not None: core.fail('Unmanaged trial marker exists; inspect its ownership first.')
            installed[name] = after
            if now != after: operations.append({'kind':'file','name':name,'before':now,'after':after})
        if operation == 'remove' and trial:
            enabled = settings.effective('enabled-extensions')
            final = [n for n in enabled if n != m.UUID]
            for name in trial['paused_conflicts']:
                if name in old['enabled_before_effective'] and name not in old['enabled_installed_effective'] and name not in final:
                    final.insert(min(old['enabled_before_effective'].index(name),len(final)),name)
            if m.UUID in old['enabled_before_effective'] and m.UUID not in final: final.append(m.UUID)
            value = old['settings_before']['enabled-extensions'] if enabled == old['enabled_installed_effective'] else settings.array(final)
            before = settings.get('enabled-extensions')
            for op in operations:
                if op['kind']=='setting' and op['name']=='enabled-extensions': before=op['after']
            if before != value: operations.append({'kind':'setting','name':'enabled-extensions','before':before,'after':value})
        if operation != 'remove':
            data = json.loads(core.contents(owner['after']))
            if trial: data['t16_trial'] = trial
            data.update(target='desktop',desktop={'format':1,'layout':layout,'originals':originals,'installed':installed,'referents':referents})
            owner['after'] = core.image(core.canonical(data),0o600)
        operations.extend(enabling)
        operations.append(owner)
        notes += ['User desktop: GTK entry files/links and settings are preserved for exact restoration.',
                  'No machine-specific target is required. Existing trial restoration data is retained.']
        return operations,notes
    m.make_plan = core.make_plan = make_plan
    m.status_extra = core.status_extra = lambda home, owner: {**base_status(home,owner),'target':'desktop',
        'ownership_layout':layout,'record_target':owner.get('target','legacy') if owner else None,'legacy_trial':bool(owner and owner.get('t16_trial'))}


def main():
    spec = importlib.util.spec_from_file_location('desktop_material',Path(__file__).with_name('manage-material.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.core.guard=lambda: context().guard(restoring=True)
    m.configure_adapter=lambda: configure(m,context().guard(restoring=(m.ARGS.operation if m.ARGS.action=='plan' else m.ARGS.action) in ('remove','recover','status')))
    return m.main()


if __name__=='__main__': raise SystemExit(main())
