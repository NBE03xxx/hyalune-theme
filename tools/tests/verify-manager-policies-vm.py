#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Persistent Flatpak follow/custom/hold policies in a VM-private HOME."""
import argparse,copy,hashlib,json,os,socket,subprocess,sys,uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);a=p.parse_args();project=a.project.resolve();sys.path.insert(0,str(project/'src'))
from manager import profile
root=Path.home()/'.local/state/glass50/phase5-tests'/('policies-'+uuid.uuid4().hex);root.mkdir(parents=True,mode=0o700)
home=root/'home';home.mkdir();checks=[];env=os.environ.copy()
def check(n,v):checks.append({'name':n,'passed':bool(v)});assert v,n
def call(action,request=None,expected=0,flags=()):
 r=subprocess.run([sys.executable,str(project/'tools/manage-settings.py'),action,'--test-root',str(home),*flags],input=json.dumps(request) if request else None,capture_output=True,text=True,env=env,timeout=60)
 assert r.returncode==expected,(action,r.returncode,r.stdout,r.stderr)
 if expected==86:return None
 j=json.loads(r.stdout);return j['result'] if expected==0 else j
def apply(value,flags=(),expected=0):
 request={'profile':value,'apps':[]};plan=call('plan',request);request['plan_token']=plan['manager']['token'];return call('set',request,expected,flags)
def owner():return json.loads((home/'.local/state/glass50/installer-material-v1/active.json').read_text())
def app_owner(app):return json.loads((home/'.local/state/glass50/installer-flatpak-v1'/app/'active.json').read_text())
def app_css(app):return (home/'.var/app'/app/'config/gtk-4.0/gtk.css').read_bytes()
value=profile.defaults();inventory=call('status')['flatpak'];apps=[r['app'] for r in inventory['apps'] if r['status']=='candidate' and r['toolkit'] in ('gtk3','gtk4')][:2];assert len(apps)==2
value['flatpak']={apps[0]:{'mode':'follow'},apps[1]:{'mode':'custom','surface':{'opacity':.74,'color':'#314552'}}}
result=apply(value);before=[app_css(app) for app in apps];original=owner()['originals']
check('both policies saved in the existing native owner',owner()['manager']['profile']['flatpak']==value['flatpak'])
check('per-app policy saved in existing Flatpak records',all(app_owner(app)['manager']['policy']==value['flatpak'][app] for app in apps))
value['common']={'opacity':.65,'color':'#385565'};result=apply(value)
check('common apply automatically updates enrolled app without selection',app_css(apps[0])!=before[0] and any(r['app']==apps[0] and r['status']=='applied' for r in result['manager']['apps']))
check('custom app CSS is stable when common material changes',app_css(apps[1])==before[1])
check('original native restoration data survives policy updates',owner()['originals']==original)
check('policy state survives backend restarts',call('status')['profile']['flatpak']==value['flatpak'])
held=app_css(apps[0]);value['flatpak'][apps[0]]={'mode':'hold'};value['common']['opacity']=.72;apply(value)
check('hold keeps last applied app bytes',app_css(apps[0])==held)
value['flatpak'][apps[0]]={'mode':'follow'};apply(value);check('returning to follow catches up with common values',app_css(apps[0])!=held)
# Closed/open behavior is emulated by a bounded command adapter, never launch/kill apps.
real=subprocess.check_output(['which','flatpak'],text=True).strip();bin_dir=root/'bin';bin_dir.mkdir();wrapper=bin_dir/'flatpak';wrapper.write_text('#!/usr/bin/python3\nimport os,sys\nif sys.argv[1:2]==["ps"]:print(os.environ.get("HYALUNE_TEST_RUNNING",""))\nelse:os.execv('+repr(real)+',["flatpak",*sys.argv[1:]])\n');wrapper.chmod(0o700)
env.update(PATH=str(bin_dir)+':'+os.environ['PATH'],HYALUNE_TEST_RUNNING=apps[0]);before=app_css(apps[0]);value['common']['opacity']=.61;result=apply(value)
check('running follower deferred without claiming success',app_css(apps[0])==before and any(r['app']==apps[0] and r['status']=='deferred' for r in result['manager']['apps']))
check('deferred follower reports needs-update',any(r['app']==apps[0] and r['needs_update'] for r in call('status')['flatpak']['apps']))
env.pop('HYALUNE_TEST_RUNNING');apply(value);check('closed follower catches up on next apply',app_css(apps[0])!=before)
env['HYALUNE_TEST_RUNNING']=apps[1];before_custom=app_css(apps[1]);value['common']['opacity']=.63;apply(value)
check('unchanged custom material is not falsely pending after common edit',app_css(apps[1])==before_custom and not next(r for r in call('status')['flatpak']['apps'] if r['app']==apps[1])['needs_update'])
env.pop('HYALUNE_TEST_RUNNING')
# Preserve conflict edits while applying independent native changes.
path=home/'.var/app'/apps[0]/'config/gtk-4.0/gtk.css';saved=path.read_bytes();path.write_bytes(saved.replace(b'Glass50 managed: flatpak GTK begin',b'Glass50 managed: edited GTK begin'))
before=path.read_bytes();value['common']['opacity']=.62;result=apply(value)
check('conflicting follower is deferred and its external edits kept',path.read_bytes()==before and any(r['app']==apps[0] and r['status']=='deferred' for r in result['manager']['apps']))
path.write_bytes(saved);apply(value)
# Crash after child writes rolls back preferences and every app together.
request={'profile':copy.deepcopy(value),'apps':[]};request['profile']['common']['opacity']=.69;plan=call('plan',request);request['plan_token']=plan['manager']['token'];before=[app_css(app) for app in apps];old=owner()
call('set',request,86,('--crash-after',str(len(plan['targets'])-1)));call('recover')
check('policy transaction crash restores native and all per-app records',owner()==old and [app_css(app) for app in apps]==before)
old_v1={k:v for k,v in profile.defaults().items() if k!='flatpak'};old_v1['format']=1
check('v1 profile retains original canonical representation',profile.validate(old_v1)==old_v1 and profile.upgrade(old_v1)['flatpak']=={})
plan=call('plan',flags=('--operation','remove'));call('remove',{'plan_token':plan['manager']['token']})
check('single remove clears all policy-managed ownership',not(home/'.local/state/glass50/installer-material-v1/active.json').exists() and all(not(home/'.local/state/glass50/installer-flatpak-v1'/app/'active.json').exists() for app in apps))
print(json.dumps({'status':'passed','root':str(root),'checks':checks},ensure_ascii=False,indent=2))
