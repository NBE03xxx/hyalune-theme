#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Automatic system appearance follows committed materials without touching GDM."""
import json, os, socket, subprocess, sys, uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
project=Path(sys.argv[1]).resolve();sys.path.insert(0,str(project/'src'))
from manager import profile
root=Path.home()/'.local/state/glass50/phase5-tests'/('appearance-'+uuid.uuid4().hex)
home=root/'home';home.mkdir(parents=True);rows=[];extra={}
user='user-theme@gnome-shell-extensions.gcampax.github.com';own='glass50-blur@myglass.local'
active=home/'.local/state/glass50/installer-material-v1/active.json'
def check(name,value):rows.append({'name':name,'passed':bool(value)});assert value,name
def call(action,request=None,expected=0,flags=()):
    p=subprocess.run([sys.executable,str(project/'tools/manage-settings.py'),action,'--test-root',str(home),*flags],input=json.dumps(request) if request else None,text=True,capture_output=True,timeout=75,env=os.environ|extra)
    assert p.returncode==expected,(p.returncode,p.stdout,p.stderr)
    if expected==86:return
    v=json.loads(p.stdout);return v['result'] if v['ok'] else v
def apply(value):
    req={'profile':value,'apps':[]};req['plan_token']=call('plan',req)['manager']['token'];return call('set',req)
def setting(schema,key,value='READ',variant='s'):
    env=os.environ|dict(HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'),GSETTINGS_BACKEND='keyfile')
    code="import json,sys;from gi.repository import Gio,GLib;s=Gio.Settings.new(sys.argv[1]);v=json.loads(sys.argv[3]);k=sys.argv[2];s.reset(k) if v is None else (s.set_value(k,GLib.Variant(sys.argv[4],v)) if v!='READ' else None);Gio.Settings.sync();u=s.get_user_value(k);print(json.dumps({'raw':u.print_(True) if u else None,'value':s.get_value(k).unpack()}))"
    return json.loads(subprocess.check_output([sys.executable,'-c',code,schema,key,json.dumps(value),variant],env=env,text=True))
def scheme(value):return setting('org.gnome.desktop.interface','color-scheme',value)
def record():return json.loads(active.read_text())
def state():
    return {str(p.relative_to(home)):p.read_bytes() for p in home.rglob('*') if p.is_file() and '/transactions/' not in str(p) and p.name not in ('pending.json','lock','appearance.lock')}
setting('org.gnome.shell','enabled-extensions',[user,'unrelated@example.invalid'],'as')
old=profile.defaults();old['common']['opacity']=.7;old['overrides']={}
light=profile.select_variant(old,'light');light['common']['opacity']=.4;dark=profile.select_variant(light,'dark');apply(dark)
initial=record();restoration={k:initial[k] for k in ['originals','settings_before','css_original']}
enabled=setting('org.gnome.shell','enabled-extensions')['value']
check('watcher stays enabled in Dark with both blur preferences off',own in enabled and not any(dark['blur'].values()))
draft=home/'.config/hyalune/profile.json';draft.parent.mkdir(parents=True);draft.write_bytes(profile.canonical(profile.defaults('light')))
gdm=home/'.config/hyalune/gdm.json';gdm.write_text('{"sentinel":"independent GDM edit"}\n');sentinels={p:p.read_bytes() for p in [draft,gdm]}
gtk4=home/'.local/share/themes/Glass50-Material-Preview/gtk-4.0/material.css';pair=gtk4.read_bytes()
check('running GTK4 can already load both media branches',b'prefers-color-scheme: dark' in pair and b'prefers-color-scheme: light' in pair)
scheme('prefer-light');call('sync')
check('system Light alone selects saved Light40',call('status')['profile']==light)
check('system preference is preserved exactly',setting('org.gnome.desktop.interface','color-scheme')['raw']=="'prefer-light'")
check('GTK4 pair stays byte identical across the mode switch',gtk4.read_bytes()==pair)
check('draft and independent GDM data are never consumed or changed',all(p.read_bytes()==b for p,b in sentinels.items()))
check('initial restoration and unrelated extensions are preserved',all(record()[k]==v for k,v in restoration.items()) and setting('org.gnome.shell','enabled-extensions')['value']==enabled)
before=state();history=len(call('status')['history']);result=call('sync')
check('an already synchronized event creates no writes or history',result['status']=='unchanged' and state()==before and len(call('status')['history'])==history)
scheme('prefer-dark');call('sync');check('system Dark restores saved Dark70 and Light40',call('status')['profile']==dark)
scheme(None);call('sync');check('unset/default appearance selects Light without writing prefer-light',record()['manager']['profile']==light and setting('org.gnome.desktop.interface','color-scheme')['raw'] is None)
setting('org.gnome.shell','disable-user-extensions',True,'b');scheme('prefer-dark');before=state();result=call('sync')
check('global extension stop pauses sync without overriding it',result['reason']=='extensions-disabled' and state()==before and setting('org.gnome.shell','disable-user-extensions')['value'])
setting('org.gnome.shell','disable-user-extensions',False,'b')
setting('org.gnome.shell','enabled-extensions',[n for n in enabled if n!=own],'as');before=state();result=call('sync')
check('an individually disabled Hyalune extension is not re-enabled',result['reason']=='extension-disabled' and state()==before)
setting('org.gnome.shell','enabled-extensions',enabled,'as');call('sync')
setting('org.gnome.desktop.interface','gtk-theme','Adwaita');scheme('prefer-light');before=state();result=call('sync',expected=1)
check('unrelated theme conflicts still block automatic changes',not result['ok'] and state()==before)
setting('org.gnome.desktop.interface','gtk-theme','Glass50-Material-Preview')
for flag,expected in [('--fail-after',1),('--crash-after',86)]:
    before=state();call('sync',expected=expected,flags=(flag,'2'))
    if expected==86:check('interrupted automatic sync is visible',call('status')['pending']);call('recover')
    check(flag+' restores exact state including the system choice',state()==before)
call('sync')
inventory=call('status')['flatpak'];app=next(r['app'] for r in inventory['apps'] if r['toolkit']=='gtk4' and r['status']=='candidate')
light['flatpak']={app:{'mode':'follow'}};dark=profile.select_variant(light,'dark');apply(dark)
child=home/'.local/state/glass50/installer-flatpak-v1'/app/'active.json';old_child=child.read_bytes()
stub=root/'bin';stub.mkdir();flagfile=root/'running';flagfile.touch();wrapper=stub/'flatpak'
wrapper.write_text('#!/bin/sh\nif [ "$1" = ps ] && [ -e '+str(flagfile)+' ]; then echo '+app+'; else exec /usr/bin/flatpak "$@"; fi\n');wrapper.chmod(0o755)
extra['PATH']=str(stub)+':'+os.environ['PATH'];scheme('prefer-light');result=call('sync')
check('native follows immediately while running Flatpak is deferred',record()['manager']['profile']==light and child.read_bytes()==old_child and any(r['status']=='deferred' for r in result['manager']['apps']))
count=len(call('status')['history']);result=call('sync')
check('waiting for an application does not create empty journals',result['status']=='deferred' and len(call('status')['history'])==count)
flagfile.unlink();call('sync')
check('a deferred selected Flatpak catches up after exit',child.read_bytes()!=old_child and not next(r for r in call('status')['flatpak']['apps'] if r['app']==app)['needs_update'])
check('GDM data and unsaved draft remain intact after Flatpak retry',all(p.read_bytes()==b for p,b in sentinels.items()))
print(json.dumps({'root':str(root),'checks':rows},indent=2))
