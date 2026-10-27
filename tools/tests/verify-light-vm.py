#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Dark/Light ownership, profile retention and interruption checks in a private VM HOME."""
import copy,hashlib,json,os,pathlib,socket,subprocess,sys,uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
assert subprocess.check_output(['findmnt','-no','SOURCE','/'],text=True).strip()=='/dev/vda2'
project=Path(sys.argv[1]);sys.path.insert(0,str(project/'src'));from manager import profile as p
root=Path.home()/'.local/state/glass50/phase5-tests'/('light-'+uuid.uuid4().hex);root.mkdir(mode=0o700);home=root/'home';home.mkdir();rows=[]
def check(n,v):rows.append({'name':n,'passed':bool(v)});assert v,n
def call(action,req=None,expect=0,flags=()):
 r=subprocess.run([sys.executable,str(project/'tools/manage-settings.py'),action,'--test-root',str(home),*flags],input=json.dumps(req) if req else None,capture_output=True,text=True,timeout=60)
 assert r.returncode==expect,(r.returncode,r.stdout,r.stderr)
 if expect==86:return
 j=json.loads(r.stdout);return j['result'] if expect==0 else j

def apply(v,expect=0,flags=(),apps=[]):
 req={'profile':v,'apps':apps};plan=call('plan',req);req['plan_token']=plan['manager']['token'];return call('set',req,expect,flags)
def record():return (home/'.local/state/glass50/installer-material-v1/active.json').read_bytes()
def owner():return json.loads(record())
def css():return (home/'.local/share/themes/Hyalune/gnome-shell/gnome-shell.css').read_bytes()
def acss(app):return (home/'.var/app'/app/'config/gtk-4.0/gtk.css').read_bytes()
def body(data):return data.split(b'/* Glass50 managed: flatpak GTK begin */\n',1)[1].rsplit(b'\n/* Glass50 managed: flatpak GTK end */',1)[0]
old=p.defaults();v1={k:v for k,v in old.items() if k!='flatpak'};v1['format']=1
check('format1 and format2 canonical hashes unchanged on read',p.validate(v1)==v1 and p.validate(old)==old)
old['common']={'color':'#28343c','opacity':.63};old['overrides']['gtk3']={'color':'#28343c','opacity':.68}
apps=[r['app'] for r in call('status')['flatpak']['apps'] if r['toolkit'] in ('gtk3','gtk4') and r['status']=='candidate'][:3];assert len(apps)==3
old['flatpak']={apps[0]:{'mode':'follow'},apps[1]:{'mode':'custom','surface':{'color':'#425663','opacity':.71}},apps[2]:{'mode':'hold'}}
apply(old);initial=owner();orig=initial['originals'];darkcss=css();darkapps=[acss(n) for n in apps[:2]]
light=p.select_variant(old,'light');apply(light);lightcss=css();rec=owner()
check('light scheme and material recorded in same existing owner',rec['settings_installed']['color-scheme']=="'prefer-light'" and rec['manager']['profile']==light)
check('native originals remain identical across light switch',rec['originals']==orig and rec['settings_before']==initial['settings_before'])
check('light CSS uses native light resource and dark foreground',b'gnome-shell-light.css' in lightcss and b'#202124' in lightcss)
check('follower receives light CSS',acss(apps[0])!=darkapps[0] and b'prefers-color-scheme: light' in acss(apps[0]))
check('custom surface preserved while light foreground changes',call('status')['profile']['flatpak'][apps[1]]==old['flatpak'][apps[1]] and acss(apps[1])!=darkapps[1] and b'66, 86, 99' in acss(apps[1]))
check('hold is never silently installed',not(home/'.local/state/glass50/installer-flatpak-v1'/apps[2]/'active.json').exists())
light['common']['opacity']=.81;light['overrides']['panel']['opacity']=.76;apply(light)
dark=p.select_variant(light,'dark');check('dark edited material restored from alternate',dark['common']==old['common'] and dark['overrides']==old['overrides']);apply(dark)
check('Dark Shell bytes and original Dark Flatpak CSS branch preserved',css()==darkcss and all(body(acss(n)).startswith(body(before)+b'\n') and b'prefers-color-scheme: light' in acss(n) for n,before in zip(apps[:2],darkapps)))
check('light edits survive return trip',p.select_variant(call('status')['profile'],'light')['common']['opacity']==.81)
check('reset defaults affects current variant only',p.reset_material(dark)['alternate']==dark['alternate'] and p.reset_material(light)['common']==p.LIGHT['common'] and p.reset_material(light)['flatpak']==light['flatpak'])
r=subprocess.run([str(project/'install.sh'),'plan','--operation','update','--test-root',str(home)],capture_output=True,text=True,timeout=60)
check('fixed Dark CLI update cannot silently discard variant values',r.returncode!=0 and 'Dark/Light profile' in r.stderr+r.stdout)
previous=record();apply(light);call('undo');check('undo restores exact dark record and payload',record()==previous and css()==darkcss)
for flag,expect in [('--fail-after',1),('--crash-after',86)]:
 previous=record();apply(light,expect,(flag,'3'))
 if expect==86:check('interrupted switch exposes pending state',call('status')['pending']);call('recover')
 check(flag+' restores exact dark owner and material',record()==previous and css()==darkcss)
req={'profile':light,'apps':[]};plan=call('plan',req);req['plan_token']=plan['manager']['token'];mod=copy.deepcopy(dark);mod['common']['opacity']=.65;apply(mod)
check('stale switch plan rejected',call('set',req,1)['error']['code']=='stale-plan')
plan=call('plan',flags=('--operation','remove'));call('remove',{'plan_token':plan['manager']['token']})
check('single removal restores pre-install native and selected Flatpak',not(home/'.local/state/glass50/installer-material-v1/active.json').exists() and all(not(home/'.local/state/glass50/installer-flatpak-v1'/n/'active.json').exists() for n in apps))
(root/'result.json').write_text(json.dumps({'root':str(root),'checks':rows},indent=2));print((root/'result.json').read_text())
