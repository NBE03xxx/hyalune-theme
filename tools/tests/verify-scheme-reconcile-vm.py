#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit profile apply reconciles GNOME's scheme without weakening other guards."""
import json, os, socket, subprocess, sys, uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
project=Path(sys.argv[1]).resolve();sys.path.insert(0,str(project/'src'))
from manager import profile
root=Path.home()/'.local/state/glass50/phase5-tests'/('scheme-'+uuid.uuid4().hex)
home=root/'home';home.mkdir(parents=True);checks=[]
active=home/'.local/state/glass50/installer-material-v1/active.json'
def check(name, value):
    checks.append({'name':name,'passed':bool(value)});assert value,name
def call(action, request=None, expected=0, flags=()):
    p=subprocess.run([sys.executable,str(project/'tools/manage-settings.py'),action,'--test-root',str(home),*flags],input=json.dumps(request) if request else None,text=True,capture_output=True,timeout=60)
    assert p.returncode==expected,(p.returncode,p.stdout,p.stderr)
    if expected==86:return
    v=json.loads(p.stdout);return v['result'] if v['ok'] else v
def apply(value, expected=0, flags=()):
    req={'profile':value,'apps':[]};plan=call('plan',req);req['plan_token']=plan['manager']['token']
    return call('set',req,expected,flags)
def setting(key, value=None):
    env=os.environ.copy();env.update(HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'),GSETTINGS_BACKEND='keyfile')
    code="from gi.repository import Gio;import sys;s=Gio.Settings.new('org.gnome.desktop.interface');s.set_string(sys.argv[1],sys.argv[2]);Gio.Settings.sync()"
    if value is not None:subprocess.run([sys.executable,'-c',code,key,value],env=env,check=True)
def tree():
    return {str(p.relative_to(home)):p.read_bytes() for p in home.rglob('*') if p.is_file() and '/transactions/' not in str(p) and p.name not in ('pending.json','lock','appearance.lock')}
old=profile.defaults();old['common']['opacity']=.7;old['overrides']={}
light=profile.select_variant(old,'light');light['common']['opacity']=.4
dark=profile.select_variant(light,'dark');apply(light)
owner=json.loads(active.read_text());restoration={k:owner[k] for k in ('originals','settings_before','css_original')}
setting('color-scheme','prefer-dark');before=tree();state=call('status')
check('external scheme is reported without blocking explicit apply',state['external_color_scheme']['current']=='prefer-dark' and not state['conflicts'])
check('reading external scheme never changes profile or files',tree()==before and state['profile']==light)
req={'profile':dark,'apps':[]};plan=call('plan',req)
check('same-path Shell refresh is planned as two journal settings',sum(op['kind']=='setting' and op['name']=='shell-theme' for op in plan['targets'])==2)
apply(dark);record=json.loads(active.read_text())
check('Dark70 applied while Light40 remains stored',record['manager']['profile']==dark and record['settings_installed']['color-scheme']=="'prefer-dark'")
check('original restoration fields are unchanged',all(record[k]==v for k,v in restoration.items()))
setting('color-scheme','prefer-light');apply(light)
check('reverse external scheme reconciliation works',call('status')['profile']==light and not call('status')['conflicts'])
setting('color-scheme','prefer-dark');req={'profile':dark,'apps':[]};plan=call('plan',req);req['plan_token']=plan['manager']['token']
setting('color-scheme','default');before=tree();result=call('set',req,1)
check('scheme change after plan rejects stale token before writes',result['error']['code']=='stale-plan' and tree()==before)
setting('color-scheme','prefer-dark')
for flag,expected in [('--fail-after',1),('--crash-after',86)]:
    plan=call('plan',{'profile':dark,'apps':[]});index=next(i for i,op in enumerate(plan['targets'],1) if op['kind']=='setting' and op['name']=='shell-theme')
    before=tree();apply(dark,expected,(flag,str(index)))
    if expected==86:check('interrupted refresh is visible',call('status')['pending']);call('recover')
    check(flag+' inside transient theme refresh restores exact previous state',tree()==before)
setting('gtk-theme','Adwaita');before=tree();state=call('status');result=call('plan',{'profile':dark,'apps':[]},1)
check('other external theme settings still block and remain untouched',any(v['target']=='gtk-theme' for v in state['conflicts']) and not result['ok'] and tree()==before)
setting('gtk-theme','Hyalune')
print(json.dumps({'root':str(root),'checks':checks},indent=2))
