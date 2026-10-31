#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install/update/remove the user app and menu entry; appearance/backups untouched."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
APP='.local/share/hyalune/settings/app/'
ID='io.github.NBE03xxx.Hyalune.Settings'
ENTRY='.local/share/applications/'+ID+'.desktop'
ICON='.local/share/icons/hicolor/scalable/apps/'+ID+'.svg'


def module(name):
    spec=importlib.util.spec_from_file_location('manager_install_'+name.replace('-','_'),ROOT/'tools'/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'


def refresh_icon_cache(home):
    # A pre-existing hicolor cache can hide a new app even in a fresh process.
    # This shared derived cache is rebuilt, never owned or removed by this app.
    tool=shutil.which('gtk4-update-icon-cache') or shutil.which('gtk-update-icon-cache')
    folder=home/'.local/share/icons/hicolor'
    if not tool or not folder.is_dir():return
    try:
        subprocess.run([tool,'--force','--ignore-theme-index',str(folder)],check=True,capture_output=True,timeout=30)
    except (OSError,subprocess.SubprocessError):
        print('Hyalune app: アイコンキャッシュを更新できませんでした。アプリの処理は完了しています。',file=sys.stderr)


def payload(home,temp,test_root):
    # Validate dependencies before creating an entry that cannot launch.
    subprocess.run([sys.executable,'-c','import gi; gi.require_version("Gtk","4.0"); gi.require_version("Adw","1"); from gi.repository import Gtk,Adw'],check=True,capture_output=True)
    subprocess.run(['sassc','--version'],check=True,capture_output=True)
    source={}
    for folder in ['src/manager','src/scss','build/Glass50-Material-Preview']:
        for p in sorted((ROOT/folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:source[str(p.relative_to(ROOT))]=p.read_bytes()
    names=['manage-theme','manage-material','manage-desktop','desktop-context','manage-flatpak','flatpak-discovery','manage-settings','hyalune-settings','gdm-wallpaper']
    for name in names:source['tools/'+name+'.py']=(ROOT/'tools'/(name+'.py')).read_bytes()
    base=temp/'manager-base'
    saved = ROOT/'manager-base'
    if saved.is_dir():
        # A saved restore source must install its exact validated payload base,
        # matching backend.make_base, rather than regenerate today's package.
        module('manage-material').load_package(saved)
        shutil.copytree(saved,base)
    else:
        subprocess.run([sys.executable,str(ROOT/'tools/package-material.py'),'--directory',str(base)],check=True,stdout=subprocess.DEVNULL)
    for p in base.rglob('*'):
        if p.is_file():source['manager-base/'+str(p.relative_to(base))]=p.read_bytes()
    source['LICENSE']=(ROOT/'LICENSE').read_bytes()
    source['LICENSES.md']=(ROOT/'docs/LICENSES.md').read_bytes()
    source['build/Hyalune-GDM/background.svg']=(ROOT/'build/Hyalune-GDM/background.svg').read_bytes()
    result={APP+n:data for n,data in source.items()}
    exec_line='/usr/bin/python3 -B '+quote(home/APP/'tools/hyalune-settings.py')
    if test_root:exec_line+=' --test-root '+quote(test_root)
    result[ENTRY]=('[Desktop Entry]\nType=Application\nName=Hyalune Settings\nName[ja]=Hyalune 設定\nComment=Adjust Hyalune appearance and restore managed settings\nComment[ja]=Hyaluneの外観と復元を管理\nExec='+exec_line+'\nIcon='+ID+'\nTerminal=false\nCategories=Settings;DesktopSettings;\nStartupNotify=true\nStartupWMClass='+ID+'\nKeywords=Hyalune;Theme;Glass;Appearance;\n').encode()
    result[ICON]=(ROOT/'data'/(ID+'.svg')).read_bytes()
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['install','remove','status','recover','plan'])
    p.add_argument('--test-root');p.add_argument('--fail-after',type=int,default=0,help=argparse.SUPPRESS)
    p.add_argument('--crash-after',type=int,default=0,help=argparse.SUPPRESS)
    a=p.parse_args();real=module('desktop-context').guard(restoring=True);home=Path(a.test_root) if a.test_root else real
    c=module('manage-theme');c.guard=lambda:module('desktop-context').guard(restoring=True)
    c.STATE='.local/state/hyalune/settings-installer-v1';c.ACTIVE=c.STATE+'/active.json'
    c.CSS=ENTRY;c.KEYS={};c.require_user_themes=False;c.component_guard=lambda *_:None
    class NoSettings:
        def __init__(self,_):pass
    c.Settings=NoSettings
    old=c.snapshot(home/c.ACTIVE);owner=json.loads(c.contents(old)) if old else None
    if owner and (owner.get('format')!=1 or owner.get('component')!='hyalune-settings-app'):
        raise ValueError('Unknown application ownership')
    def allowed(name):
        relative=name.removeprefix(APP)
        return name in (ENTRY,ICON) or (name.startswith(APP) and relative and not Path(relative).is_absolute() and '..' not in Path(relative).parts)
    if owner and any(not allowed(n) for n in owner['installed']):raise ValueError('Unexpected owned application path')
    with tempfile.TemporaryDirectory(prefix='hyalune-app-') as directory:
        files=payload(home,Path(directory),a.test_root) if a.action in ('install','plan') else {}
        targets=set(files)|set(owner['installed'] if owner else {})
        c.FILES=tuple(sorted(targets));c.THEME=''
        def make_plan(h,s,action,package):
            if action=='remove' and not owner:raise ValueError('管理アプリは未導入です。')
            operations=[];installed={};originals=owner['originals'].copy() if owner else {}
            for name in sorted(targets):
                now=c.snapshot(h/name)
                if owner and name in owner['installed'] and now!=owner['installed'][name]:raise ValueError('Application file edited: '+name)
                if name not in originals:
                    if now is not None:raise ValueError('Unmanaged application file exists: '+name)
                    originals[name]=now
                after=originals[name] if action=='remove' or name not in files else c.image(files[name])
                if now!=after:operations.append({'kind':'file','name':name,'before':now,'after':after})
                installed[name]=after
            state=None if action=='remove' else c.image(c.canonical({'format':1,'component':'hyalune-settings-app','version':'0.3.2',
                  'originals':originals,'installed':installed}),0o600)
            current=c.snapshot(h/c.ACTIVE)
            if current!=state:operations.append({'kind':'file','name':c.ACTIVE,'before':current,'after':state})
            return operations,['App and menu entry only. Theme, profiles, GDM and appearance backups are retained.']
        c.make_plan=make_plan
        c.status_extra=lambda h,o:{'component':'hyalune-settings-app','desktop_entry':str(h/ENTRY),'appearance_unchanged':True}
        # Recovery permits only the application's closed subtree and two entries.
        pending=home/c.STATE/'pending.json';c.safe(pending)
        if a.action=='recover' and pending.exists():
            journal=json.loads(pending.read_text());names=[op['name'] for op in journal['operations']]
            if any(n!=c.ACTIVE and not allowed(n) for n in names):raise ValueError('Unexpected recovery path')
            c.FILES=tuple(names)
        a.action=('update' if owner else 'apply') if a.action=='install' else a.action
        a.operation='update' if owner else 'apply';a.package=directory;a.crash_after_commit=False
        c.run(a)
        if a.action in ('apply','update','remove','recover'):refresh_icon_cache(home)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:print('Hyalune app: '+str(error),file=sys.stderr);raise SystemExit(1)
