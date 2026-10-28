#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""VM-private integration tests for the manager's shared ownership and journals."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import uuid

assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
assert subprocess.check_output(['findmnt','-no','SOURCE','/'],text=True).strip()=='/dev/vda2'
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);a=p.parse_args();project=a.project.resolve()
sys.path.insert(0,str(project/'src'))
from manager import profile
root=Path.home()/'.local/state/glass50/phase5-tests'/('manager-'+uuid.uuid4().hex);root.mkdir(parents=True,mode=0o700)
home=root/'home';home.mkdir();rows=[]
state='.local/state/glass50/installer-material-v1';active=home/state/'active.json'

def check(name,value):rows.append({'name':name,'passed':bool(value)});assert value,name

call_env=os.environ.copy()

def call(action,request=None,expected=0,flags=(),target=home):
 if action=='remove' and request is None:
  request={'plan_token':call('plan',flags=('--operation','remove'),target=target)['manager']['token']}
 r=subprocess.run([sys.executable,str(project/'tools/manage-settings.py'),action,'--test-root',str(target),*flags],input=json.dumps(request) if request else None,capture_output=True,text=True,timeout=45,env=call_env)
 assert r.returncode==expected,(action,r.returncode,r.stdout,r.stderr)
 if expected==86:return r
 response=json.loads(r.stdout);assert response['api']=='hyalune.settings' and response['version']==1
 return response['result'] if expected==0 else response

def tree(base):
 result={}
 for f in base.rglob('*'):
  n=str(f.relative_to(base))
  if n.startswith('.local/state/') or n=='.config/glib-2.0/settings/keyfile':continue
  if f.is_symlink():result[n]=('link',os.readlink(f))
  elif f.is_file():result[n]=(hashlib.sha256(f.read_bytes()).hexdigest(),stat.S_IMODE(f.stat().st_mode))
 return result

def apply(value,apps=(),flags=(),expected=0):
 request={'profile':value,'apps':list(apps)};plan=call('plan',request)
 request['plan_token']=plan['manager']['token']
 return call('set',request,expected,flags),plan

# Source semantics: the default runtime profile must preserve all reviewed bytes.
output=profile.generate(profile.defaults(),project/'src/scss',root/'compiled')
check('default profile reproduces all five release CSS outputs',all((output/n).read_bytes()==(project/'build/Glass50-Material-Preview'/n).read_bytes() for n in ['gnome-shell/gnome-shell.css','gtk-3.0/gtk.css','gtk-3.0/gtk-dark.css','gtk-4.0/material.css','gtk-4.0/flatpak.css']))
for value in [float('nan'),float('inf'),-1,1.01,True,'0.56']:
 v=profile.defaults();v['common']['opacity']=value
 try:profile.validate(v);raise AssertionError('accepted invalid alpha')
 except ValueError:pass
check('nonfinite, boolean, string and out-of-range alpha rejected',True)
for value in ['#fff','red','#{system("id")}','#123456;@import "/tmp/x";']:
 v=profile.defaults();v['common']['color']=value
 try:profile.validate(v);raise AssertionError('accepted executable color')
 except ValueError:pass
check('color expressions and CSS injection rejected',True)
for opacity in [0,.1,.56,1]:
 v=profile.defaults();v['common']['opacity']=opacity;v['overrides']['panel']['opacity']=1
 profile.generate(v,project/'src/scss',root/'boundary')
check('opaque base and content below panel alpha compile',True)
folder=home/'.config/gtk-4.0';folder.mkdir(parents=True);(folder/'original.css').write_text('/* independent source */\n');(folder/'original.css').chmod(0o640)
for n in ['gtk.css','gtk-dark.css']:(folder/n).symlink_to('original.css')
original=tree(home);before=call('status')
check('first state read has no appearance writes',tree(home)==original and not active.exists() and not before['managed'])
default=profile.defaults();request={'profile':default,'apps':[]};q=call('plan',request)
check('planning never creates ownership',tree(home)==original and not active.exists())
request['plan_token']=q['manager']['token'];result=call('set',request)
owner=json.loads(active.read_text());original_fields={k:copy.deepcopy(owner[k]) for k in ['originals','settings_before','css_original','enabled_before_effective']}
check('profile and original restoration share existing native ownership',owner['manager']['profile']==default and owner['target']=='desktop')
check('both GTK original links remain in restoration record',all(owner['desktop']['originals']['.config/gtk-4.0/'+n]=={'symlink':'original.css'} for n in ['gtk.css','gtk-dark.css']))
changed=profile.defaults();changed['common']={'opacity':.68,'color':'#28434f'};changed['blur']={'quick_settings':True,'windows':False}
result,q=apply(changed);updated=json.loads(active.read_text())
check('update preserves all initial restoration values',all(updated[k]==v for k,v in original_fields.items()))
check('blur choices are independent in same ownership',updated['settings_installed']['effect-enabled']=='true' and updated['settings_installed']['window-material-enabled']=='false')
check('setting and configured profile reported separately from runtime',call('status')['profile']==changed and call('status')['runtime']['code_loaded']=='not-verified')
# Stale plan protection is evaluated again under the shared lock.
request={'profile':default,'apps':[]};q=call('plan',request);request['plan_token']=q['manager']['token'];apply(changed|{'common':{'opacity':.71,'color':'#28434f'}})
before=tree(home);r=call('set',request,1)
check('stale plan is rejected before any appearance writes',r['error']['code']=='stale-plan' and tree(home)==before)
# A different CLI owns the same appearance lock, independently of GUI lifetime.
request={'profile':default,'apps':[]};q=call('plan',request);request['plan_token']=q['manager']['token']
with (home/'.local/state/glass50/appearance.lock').open('a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);before=tree(home);r=call('set',request,1)
 check('shared CLI lock prevents simultaneous GUI writes',r['error']['code']=='resource-busy' and tree(home)==before)
# Existing profile state and native changes must be recovered together.
for flag,expected in [('--fail-after',1),('--crash-after',86)]:
 before=tree(home);old_owner=active.read_bytes();apply(default,flags=(flag,'2'),expected=expected)
 if expected==86:
  check('crash is visible through status',call('status')['pending']);call('recover')
 check(flag+' restores installed profile, links and payload',tree(home)==before and active.read_bytes()==old_owner and not(home/state/'pending.json').exists())
# Conflict reporting and engine refusal are both required.
css=home/'.local/share/themes/Hyalune/gtk-3.0/gtk.css';saved=css.read_bytes();css.write_bytes(saved+b'/* user edit */\n');before=tree(home)
check('external edit is visible in structured state',bool(call('status')['conflicts']))
r=call('plan',{'profile':default,'apps':[]},1);check('external edit cannot be overwritten by GUI adapter',not r['ok'] and tree(home)==before);css.write_bytes(saved)
# Use the real installed GTK inventory, but write only into the private HOME.
inventory=call('status')['flatpak'];apps=[r['app'] for r in inventory['apps'] if r['status']=='candidate' and r['toolkit'] in ('gtk3','gtk4')][:2]
check('VM contains two detected GTK fixtures',len(apps)==2)
for app in apps:
 f=home/'.var/app'/app/'config/gtk-4.0/gtk.css';f.parent.mkdir(parents=True,exist_ok=True);f.write_text('/* independent app CSS */\n');f.chmod(0o640)
original_app={app:(home/'.var/app'/app/'config/gtk-4.0/gtk.css').read_bytes() for app in apps}
result,q=apply(changed,apps)
journal=json.loads((Path(result['transaction'])/'journal.json').read_text())
check('native and selected app ownership are committed in one existing journal',all(any(op['name'].endswith('/'+app+'/active.json') for op in journal['operations']) for app in apps) and journal['operations'][-1]['name']==state+'/active.json')
check('all selected GTK apps are managed',all((home/'.local/state/glass50/installer-flatpak-v1'/app/'active.json').exists() for app in apps))
# Simulate a running ID without launching or killing the user's applications.
real_flatpak=shutil.which('flatpak');bin_dir=root/'bin';bin_dir.mkdir();wrapper=bin_dir/'flatpak'
wrapper.write_text('#!/usr/bin/python3\nimport os,sys\nif sys.argv[1:2]==["ps"]: print(os.environ["HYALUNE_TEST_RUNNING"])\nelse: os.execv('+repr(real_flatpak)+',["flatpak",*sys.argv[1:]])\n');wrapper.chmod(0o700)
call_env.update(PATH=str(bin_dir)+':'+os.environ['PATH'],HYALUNE_TEST_RUNNING=apps[0]);before=tree(home)
r=call('plan',{'profile':default,'apps':apps},1)
check('running selected app stops the entire plan without writes',r['error']['code']=='app-unavailable' and tree(home)==before and any(row['app']==apps[0] and row['status']=='deferred' for row in call('status')['flatpak']['apps']))
call_env.clear();call_env.update(os.environ)
before=tree(home);old_owner=active.read_bytes();apply(default,apps,flags=('--crash-after',str(len(q['targets'])-1)),expected=86);call('recover')
check('composite update crash recovers native and both app records',tree(home)==before and active.read_bytes()==old_owner)
before_undo=tree(home);previous=copy.deepcopy(changed);previous['common']={'opacity':.78,'color':'#36515c'}
apply(previous,apps);call('undo')
check('undo restores exact previous native and selected Flatpak bytes',tree(home)==before_undo and call('status')['profile']['common']==changed['common'])
# Existing CLI remains usable after the GUI attached its profile metadata.
r=subprocess.run([str(project/'install.sh'),'plan','--operation','remove','--test-root',str(home)],capture_output=True,text=True,timeout=45)
check('existing CLI can plan complete GUI-managed removal',r.returncode==0)
call('remove')
check('remove restores all original GTK links, bytes and modes',all(tree(home).get(k)==v for k,v in original.items()) and not active.exists())
check('remove restores app-owned CSS and preserves independent text',all((home/'.var/app'/app/'config/gtk-4.0/gtk.css').read_bytes()==original_app[app] for app in apps))
print(json.dumps({'status':'passed','root':str(root),'home':str(home),'checks':rows},ensure_ascii=False,indent=2))
