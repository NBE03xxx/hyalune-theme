#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""VM-private GTK name migration and compatible saved-package recovery."""
import argparse, json, os, shutil, socket, stat, subprocess, sys, uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--legacy-project',type=Path,required=True);a=p.parse_args()
project=a.project.resolve();legacy=a.legacy_project.resolve();sys.path.insert(0,str(project/'src'))
from manager import profile
root=Path.home()/'.local/state/glass50/phase5-tests'/('gtk-name-'+uuid.uuid4().hex);home=root/'home';home.mkdir(parents=True);rows=[]
active=home/'.local/state/glass50/installer-material-v1/active.json'
old='.local/share/themes/Glass50-Material-Preview/gtk-3.0/';new='.local/share/themes/Hyalune/gtk-3.0/'
def check(name,value):rows.append(dict(name=name,passed=bool(value)));assert value,name
def call(action,request=None,source=project,expected=0,flags=()):
 r=subprocess.run([sys.executable,str(source/'tools/manage-settings.py'),action,'--test-root',str(home),*flags],input=json.dumps(request) if request else None,text=True,capture_output=True,timeout=90)
 assert r.returncode==expected,(r.returncode,r.stdout,r.stderr)
 if expected==86:return
 v=json.loads(r.stdout);return v['result'] if v['ok'] else v
def apply(value,source=project,flags=(),expected=0):
 req=dict(profile=value,apps=[]);req['plan_token']=call('plan',req,source)['manager']['token'];return call('set',req,source,expected,flags)
def record():return json.loads(active.read_text())
def tree():return {str(p.relative_to(home)):(p.read_bytes(),stat.S_IMODE(p.stat().st_mode)) for p in home.rglob('*') if p.is_file() and '/transactions/' not in str(p) and p.name not in ('appearance.lock','lock')}
v=profile.defaults();v['common']['opacity']=.7;v['overrides']={};light=profile.select_variant(v,'light');light['common']['opacity']=.4;v=profile.select_variant(light,'dark');apply(v,legacy)
before=record();original={n:(home/old/n).read_bytes() for n in ('gtk.css','gtk-dark.css')};shell=home/'.local/share/themes/Hyalune/gnome-shell/gnome-shell.css';shell_bytes=shell.read_bytes();gtk4=home/'.config/gtk-4.0/gtk.css';gtk4_bytes=gtk4.read_bytes()
check('released fixture has Hyalune Shell and legacy GTK name',before['settings_installed']['shell-theme']=="'Hyalune'" and before['settings_installed']['gtk-theme']=="'Glass50-Material-Preview'")
(home/new).mkdir(parents=True);(home/new/'gtk.css').write_text('/* unrelated */\n');snapshot=tree();r=call('plan',dict(profile=v,apps=[]),expected=1)
check('unowned different Hyalune GTK CSS blocks migration without writes',not r['ok'] and tree()==snapshot);(home/new/'gtk.css').unlink()
plan=call('plan',dict(profile=v,apps=[]));index=next(i for i,op in enumerate(plan['targets'],1) if op['kind']=='setting' and op['name']=='gtk-theme')
check('migration changes only GTK selection among settings',[(op['kind'],op['name']) for op in plan['targets'] if op['kind']=='setting']==[('setting','gtk-theme')])
for flag,expected in [('--fail-after',1),('--crash-after',86)]:
 snapshot=tree();apply(v,flags=(flag,str(index)),expected=expected)
 if expected==86:check('interrupted GTK name migration is recorded',call('status')['pending']);call('recover')
 check(flag+' at GTK setting boundary restores complete pre-migration state',tree()==snapshot)
apply(v);after=record()
check('public Hyalune GTK name selected with exact same GTK3 bytes',after['settings_installed']['gtk-theme']=="'Hyalune'" and all((home/new/n).read_bytes()==b for n,b in original.items()))
check('retired GTK3 files restore original absence',all(not(home/old/n).exists() and after['installed'][old+n] is None for n in original))
check('Shell and GTK4 imports are byte identical',shell.read_bytes()==shell_bytes and gtk4.read_bytes()==gtk4_bytes)
check('original restoration and reviewed materials retained',all(after['originals'][n]==s for n,s in before['originals'].items()) and all(after[k]==before[k] for k in ('settings_before','css_original')) and after['manager']['profile']==v)
check('migration is conflict free',not call('status')['conflicts'])
apply(light);apply(v);check('both variants keep public GTK name and values',record()['settings_installed']['gtk-theme']=="'Hyalune'" and record()['manager']['profile']==v and (home/new/'gtk.css').read_bytes()==original['gtk.css'])
rollback=root/'rollback-source';shutil.copytree(project,rollback);subprocess.run([sys.executable,str(legacy/'tools/package-material.py'),'--directory',str(rollback/'manager-base')],check=True,stdout=subprocess.DEVNULL)
apply(v,rollback);back=record()
check('compatible engine restores saved old GTK name and payload',back['settings_installed']['gtk-theme']=="'Glass50-Material-Preview'" and all((home/old/n).read_bytes()==b and not(home/new/n).exists() for n,b in original.items()))
subprocess.run([sys.executable,str(rollback/'tools/install-manager.py'),'install','--test-root',str(home)],check=True,stdout=subprocess.DEVNULL)
installed=home/'.local/share/hyalune/settings/app';plan=call('plan',dict(profile=v,apps=[]),installed)
check('saved-payload app does not silently migrate GTK on next apply',not any(op['name']=='gtk-theme' or op['name'].startswith(new) for op in plan['targets']))
apply(v);check('explicit migration after restore succeeds',record()['settings_installed']['gtk-theme']=="'Hyalune'" and not call('status')['conflicts'])
req={'plan_token':call('plan',flags=('--operation','remove'))['manager']['token']};call('remove',req)
check('remove restores original settings and both GTK locations',not active.exists() and all(not(home/base/n).exists() for base in (old,new) for n in original))
# A pre-existing identical new file is adopted and restored, never deleted.
(home/new/'gtk.css').write_bytes(original['gtk.css']);apply(v);req={'plan_token':call('plan',flags=('--operation','remove'))['manager']['token']};call('remove',req)
check('pre-existing identical GTK file survives apply and removal',(home/new/'gtk.css').read_bytes()==original['gtk.css'])
print(json.dumps(dict(root=str(root),checks=rows),indent=2))
