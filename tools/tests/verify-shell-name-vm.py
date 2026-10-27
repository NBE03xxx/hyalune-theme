#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""VM-private legacy Shell name migration, conflict, rollback and removal checks."""
import argparse, copy, hashlib, json, os, shutil, socket, stat, subprocess, sys, uuid
from pathlib import Path
assert socket.gethostname() == 'KVM-PC' and os.environ.get('SSH_CONNECTION')
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--legacy-project',type=Path,required=True);a=p.parse_args()
project=a.project.resolve();legacy=a.legacy_project.resolve();sys.path.insert(0,str(project/'src'))
from manager import profile
root=Path.home()/'.local/state/glass50/phase5-tests'/('shell-name-'+uuid.uuid4().hex);home=root/'home';home.mkdir(parents=True);rows=[]
state='.local/state/glass50/installer-material-v1';active=home/state/'active.json';old='.local/share/themes/Glass50-Material-Preview/gnome-shell/gnome-shell.css';new='.local/share/themes/Hyalune/gnome-shell/gnome-shell.css'
def check(name,value):
 rows.append(dict(name=name,passed=bool(value)));assert value,name
def call(action,request=None,source=project,expected=0,flags=()):
 r=subprocess.run([sys.executable,str(source/'tools/manage-settings.py'),action,'--test-root',str(home),*flags],input=json.dumps(request) if request else None,text=True,capture_output=True,timeout=90)
 assert r.returncode==expected,(r.returncode,r.stdout,r.stderr)
 if expected==86:return None
 v=json.loads(r.stdout);return v['result'] if v['ok'] else v
def apply(value,source=project,flags=(),expected=0):
 req=dict(profile=value,apps=[]);req['plan_token']=call('plan',req,source)['manager']['token'];return call('set',req,source,expected,flags)
def record():return json.loads(active.read_text())
def tree():
 return {str(p.relative_to(home)):(p.read_bytes(),stat.S_IMODE(p.stat().st_mode)) for p in home.rglob('*') if p.is_file() and '/transactions/' not in str(p) and p.name not in ('appearance.lock','lock')}
v=profile.defaults();v['common']['opacity']=.7;v['overrides']={};light=profile.select_variant(v,'light');light['common']['opacity']=.4;v=profile.select_variant(light,'dark');apply(v,legacy)
before=record();bytes_before=(home/old).read_bytes();gdm=home/'.config/hyalune/gdm.json';gdm.parent.mkdir(parents=True,exist_ok=True);gdm.write_text('{"independent":true}\n');gdm_bytes=gdm.read_bytes()
check('legacy fixture uses old Shell name and reviewed values',before['settings_installed']['shell-theme']=="'Glass50-Material-Preview'" and before['manager']['profile']==v)
(home/new).parent.mkdir(parents=True,exist_ok=True);(home/new).write_text('/* unrelated theme */\n');snapshot=tree();r=call('plan',dict(profile=v,apps=[]),expected=1)
check('a different unowned Hyalune theme blocks migration without writes',not r['ok'] and tree()==snapshot);(home/new).unlink()
# Exercise interruptions before committing the new ownership record.
for flag,expected in [('--fail-after',1),('--crash-after',86)]:
 snapshot=tree();apply(v,flags=(flag,'2'),expected=expected)
 if expected==86:check('migration interruption is recorded',call('status')['pending']);call('recover')
 check(flag+' restores legacy files, settings and owner exactly',tree()==snapshot)
req=dict(profile=v,apps=[]);plan=call('plan',req);check('migration plan changes the Shell selection and path',all(any(op['name']==name for op in plan['targets']) for name in ['shell-theme',new]))
apply(v);after=record()
check('Hyalune Shell bytes and Dark70/Light40 are preserved',after['settings_installed']['shell-theme']=="'Hyalune'" and (home/new).read_bytes()==bytes_before and after['manager']['profile']==v)
check('all previous originals and settings_before are preserved',all(after['originals'][n]==s for n,s in before['originals'].items()) and after['settings_before']==before['settings_before'])
check('retired Shell file is restored to its original absence',not (home/old).exists() and after['installed'][old] is None and after['originals'][new] is None)
check('migrated ownership is conflict free',not call('status')['conflicts'])
# Apply both modes through the new public name.
apply(light);apply(v);check('both modes retain the Hyalune Shell selection',record()['settings_installed']['shell-theme']=="'Hyalune'" and record()['manager']['profile']==v and (home/new).read_bytes()==bytes_before)
# Current engine accepts a saved legacy payload, including code9, for recovery.
rollback=root/'rollback-source';shutil.copytree(project,rollback)
subprocess.run([sys.executable,str(legacy/'tools/package-material.py'),'--directory',str(rollback/'manager-base')],check=True,stdout=subprocess.DEVNULL)
apply(v,rollback);back=record()
check('saved legacy payload restores old selection and retires new path',back['settings_installed']['shell-theme']=="'Glass50-Material-Preview'" and (home/old).read_bytes()==bytes_before and not (home/new).exists() and back['manager']['profile']==v)
subprocess.run([sys.executable,str(rollback/'tools/install-manager.py'),'install','--test-root',str(home)],check=True,stdout=subprocess.DEVNULL)
installed=home/'.local/share/hyalune/settings/app';base_manifest=json.loads((installed/'manager-base/manifest.json').read_text());rollback_plan=call('plan',dict(profile=v,apps=[]),installed)
check('restored app retains compatible engine and exact legacy payload base',base_manifest['extension_version']==9 and old in base_manifest['files'] and new not in base_manifest['files'] and not any(op['name'].startswith('.local/share/gnome-shell/extensions/') or op['name']=='shell-theme' for op in rollback_plan['targets']))
apply(v);check('explicit reupgrade after legacy restore succeeds',record()['settings_installed']['shell-theme']=="'Hyalune'" and (home/new).read_bytes()==bytes_before)
# Unknown target paths must remain outside the closed recovery/install allowlist.
saved=active.read_bytes();bad=record();bad['installed']['.local/share/themes/unrelated/gnome-shell/gnome-shell.css']=None;active.write_text(json.dumps(bad));snapshot=tree();r=call('plan',dict(profile=v,apps=[]),expected=1)
check('unknown owner target is rejected before writes',not r['ok'] and tree()==snapshot);active.write_bytes(saved)
req={'plan_token':call('plan',flags=('--operation','remove'))['manager']['token']};call('remove',req)
check('remove restores both names and leaves GDM data intact',not active.exists() and not(home/old).exists() and not(home/new).exists() and gdm.read_bytes()==gdm_bytes)
print(json.dumps(dict(root=str(root),checks=rows),indent=2))
