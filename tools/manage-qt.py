#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install the optional, reversible Qt decoration launchers and session policy."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PREFIX = '.local/share/hyalune/qt/'
STATE = '.local/state/hyalune/qt-installer-v1'
ACTIVE = STATE+'/active.json'
NAME = 'io.github.NBE03xxx.Hyalune.QtAppearance'
SERVICE = '.local/share/dbus-1/services/'+NAME+'.service'
ENTRIES = {
    '.local/share/applications/setup-mozc.desktop': ('/usr/share/applications/setup-mozc.desktop','mozc'),
    '.local/share/applications/ibus-setup-mozc-jp.desktop': ('/usr/share/applications/ibus-setup-mozc-jp.desktop','mozc'),
    '.local/share/applications/com.nextcloud.desktopclient.nextcloud.desktop': ('/usr/share/applications/com.nextcloud.desktopclient.nextcloud.desktop','nextcloud'),
    '.local/share/applications/org.keepassxc.KeePassXC.desktop': ('/var/lib/flatpak/exports/share/applications/org.keepassxc.KeePassXC.desktop','keepassxc'),
}
AUTOSTART = '.config/autostart/Nextcloud.desktop'


def module(name):
    spec = importlib.util.spec_from_file_location('hyalune_qt_'+name.replace('-','_'),ROOT/'tools'/(name+'.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def allowed(name):
    path = Path(name)
    return (not path.is_absolute() and '..' not in path.parts and
            (name in (*ENTRIES,SERVICE,AUTOSTART) or name.startswith(PREFIX)))


def owner_at(core, home):
    image = core.snapshot(home/ACTIVE)
    value = json.loads(core.contents(image)) if image else None
    if value and (value.get('format')!=1 or value.get('component')!='hyalune-qt' or
                  set(value.get('installed',{}))!=set(value.get('originals',{})) or
                  any(not allowed(name) for name in value.get('installed',{}))):
        raise ValueError('Unknown Qt ownership; retained backups require inspection.')
    return value


def quote(text):
    return '"'+str(text).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'


def desktop_data(original, app, home):
    launcher = '/usr/bin/python3 -B '+quote(home/PREFIX/'runtime/launch.py')+' '+app+' --'
    lines = []
    changed = 0
    for line in original.decode().splitlines(keepends=True):
        if line.startswith('Exec='):
            command = line[5:].rstrip('\r\n')
            if app=='keepassxc':
                match = re.fullmatch(r'(?:/usr/bin/)?flatpak run .*?org\.keepassxc\.KeePassXC(.*)',command)
            elif app=='mozc':
                match = re.fullmatch(r'/usr/lib/mozc/mozc_tool(.*)',command)
            else:
                match = re.fullmatch(r'(?:(?:"?/usr/bin/)?nextcloud"?)(.*)',command)
            if not match:
                raise ValueError('Unrecognised '+app+' launcher; inspect it before applying.')
            line = 'Exec='+launcher+match[1]+'\n'
            changed += 1
        lines.append(line)
    if not changed:
        raise ValueError('No Exec entry for '+app)
    return ''.join(lines).encode()


def payload(core, home, owner):
    build = ROOT/'build/Hyalune-Qt'
    manifest = json.loads((build/'manifest.json').read_text())
    if manifest.get('format')!=1 or manifest.get('component')!='hyalune-qt' or set(manifest.get('variants',{}))!={'native5','native6','flatpak6'}:
        raise ValueError('Build the supported Qt variants first with tools/build-qt.py.')
    if manifest['source_sha256'] != module('build-qt').source_digest():
        raise ValueError('Qt source differs from the build; rebuild before installing.')
    scopes = []
    for scope in ['system','user']:
        found = subprocess.run(['flatpak','info','--'+scope,'--show-runtime','org.keepassxc.KeePassXC'],
                               capture_output=True,text=True,timeout=5)
        if found.returncode == 0:
            if found.stdout.strip() != 'org.kde.Platform/x86_64/6.11':
                raise ValueError('KeePassXC runtime differs from the supported Qt build.')
            scopes.append(scope)
    if len(scopes) != 1:
        raise ValueError('Exactly one supported KeePassXC installation is required.')
    manifest['flatpak_scope'] = scopes[0]
    result = {PREFIX+'manifest.json': core.image(core.canonical(manifest))}
    for name,(major,abi,source) in module('build-qt').VARIANTS.items():
        entry = manifest['variants'][name]
        if (entry['major'],entry['abi'],entry['path']) != (int(major),abi,name+'/wayland-decoration-client/libhyalune.so'):
            raise ValueError('Unexpected Qt ABI payload')
        data = (build/entry['path']).read_bytes()
        if core.digest(data)!=entry['sha256']:
            raise ValueError('Qt binary hash mismatch: '+name)
        result[PREFIX+entry['path']] = core.image(data,0o755)
    for path in sorted((ROOT/'src/qt').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            name = str(path.relative_to(ROOT/'src/qt'))
            result[PREFIX+'source/src/qt/'+name] = core.image(path.read_bytes())
    result[PREFIX+'source/LICENSE'] = core.image((ROOT/'LICENSE').read_bytes())
    result[PREFIX+'source/tools/build-qt.py'] = core.image((ROOT/'tools/build-qt.py').read_bytes())
    for name in ['launch.py','theme-service.py']:
        result[PREFIX+'runtime/'+name] = core.image((ROOT/'src/qt'/name).read_bytes())
    exec_line = '/usr/bin/python3 -B '+quote(home/PREFIX/'runtime/theme-service.py')
    result[SERVICE] = core.image(('[D-BUS Service]\nName='+NAME+'\nExec='+exec_line+'\n').encode())
    for target,(system,app) in ENTRIES.items():
        saved = owner['originals'].get(target) if owner else core.snapshot(home/target)
        upstream = Path(system)
        if app == 'keepassxc' and scopes[0] == 'user':
            upstream = home/'.local/share/flatpak/exports/share/applications'/upstream.name
        original = core.contents(saved) if saved else upstream.read_bytes()
        result[target] = core.image(desktop_data(original,app,home), saved['mode'] if saved else 0o644)
    original = owner['originals'].get(AUTOSTART) if owner else core.snapshot(home/AUTOSTART)
    if original:
        result[AUTOSTART] = core.image(desktop_data(core.contents(original),'nextcloud',home),original['mode'])
    return manifest,result


def refresh_service():
    # Stop the old read-only instance so a completed update/remove is reflected
    # in already-open Qt windows. A later client can activate an installed service.
    from gi.repository import Gio,GLib
    try:
        Gio.bus_get_sync(Gio.BusType.SESSION,None).call_sync(NAME,
            '/io/github/NBE03xxx/Hyalune/QtAppearance',NAME,'Quit',None,None,
            Gio.DBusCallFlags.NO_AUTO_START,2000,None)
    except GLib.Error:
        pass


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['install','plan','status','remove','recover'])
    p.add_argument('--operation',choices=['install','remove'],default='install')
    p.add_argument('--test-root',type=Path,help=argparse.SUPPRESS)
    p.add_argument('--fail-after',type=int,default=0,help=argparse.SUPPRESS)
    p.add_argument('--crash-after',type=int,default=0,help=argparse.SUPPRESS)
    args=p.parse_args()
    context=module('desktop-context')
    restoring=args.action in ('status','remove','recover') or args.operation=='remove'
    if args.test_root:
        import socket
        if socket.gethostname()!='KVM-PC' or not os.environ.get('SSH_CONNECTION'):
            raise ValueError('Private tests require the established VM SSH session.')
    real=context.guard(restoring=restoring or bool(args.test_root))
    home=args.test_root if args.test_root else real
    core=module('manage-theme')
    core.guard=lambda: context.guard(restoring=restoring or bool(args.test_root))
    core.STATE,core.ACTIVE=STATE,ACTIVE
    core.THEME=''
    core.CSS=SERVICE
    core.KEYS={}
    core.require_user_themes=False
    class NoSettings:
        def __init__(self,home):
            pass
    core.Settings=NoSettings
    owner=owner_at(core,home)
    action=args.operation if args.action=='plan' else args.action
    installing=action=='install'
    manifest,files=payload(core,home,owner) if installing else ({},{})
    targets=set(files)|set(owner['installed'] if owner else {})
    core.FILES=tuple(sorted(targets))

    def make_plan(home,settings,operation,package):
        current_owner=owner_at(core,home)
        if current_owner!=owner:
            raise ValueError('Concurrent Qt ownership update; plan again.')
        if operation=='remove' and not owner:
            raise ValueError('Qt component is not installed.')
        originals=dict(owner['originals']) if owner else {}
        installed={}
        operations=[]
        # Install payload before launchers, remove launchers before payload.
        ordered=sorted(targets,key=lambda name:(not name.startswith(PREFIX),name),reverse=operation=='remove')
        for name in ordered:
            now=core.snapshot(home/name)
            if owner and name in owner['installed'] and now!=owner['installed'][name]:
                raise ValueError('Managed Qt file edited: '+name)
            if name not in originals:
                if now is not None and (name.startswith(PREFIX) or name==SERVICE):
                    raise ValueError('Unmanaged Qt file exists: '+name)
                originals[name]=now
            after=originals[name] if operation=='remove' or name not in files else files[name]
            if now!=after:
                operations.append({'kind':'file','name':name,'before':now,'after':after})
            installed[name]=after
        after=None if operation=='remove' else core.image(core.canonical({
            'format':1,'component':'hyalune-qt','version':manifest['version'],
            'originals':originals,'installed':installed}),0o600)
        before=core.snapshot(home/ACTIVE)
        if before!=after:
            operations.append({'kind':'file','name':ACTIVE,'before':before,'after':after})
        return operations,['Qt app launchers and read-only theme policy; per-launch Flatpak permissions.']

    core.make_plan=make_plan
    core.status_extra=lambda home,owner:{'component':'hyalune-qt','conflicts':[
        name for name,value in (owner or {}).get('installed',{}).items() if core.snapshot(home/name)!=value]}
    pending=home/STATE/'pending.json'
    core.safe(pending)
    if args.action=='recover' and pending.exists():
        names=[op['name'] for op in json.loads(pending.read_text())['operations']]
        if any(name!=ACTIVE and not allowed(name) for name in names):
            raise ValueError('Unexpected Qt recovery path')
        core.FILES=tuple(names)
    args.action=('update' if owner else 'apply') if args.action=='install' else args.action
    args.operation=('update' if owner else 'apply') if args.operation=='install' else 'remove'
    args.package=str(ROOT)
    args.crash_after_commit=False
    core.run(args)
    if args.action in ('apply','update','remove','recover') and not args.test_root:
        refresh_service()
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('Hyalune Qt: '+str(error),file=sys.stderr)
        raise SystemExit(1)
