#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Restricted GDM API against isolated real alternatives/resources, as root in VM."""
import argparse,copy,importlib.util,json,os,pwd,socket,subprocess,sys,tempfile,uuid
from pathlib import Path
assert os.geteuid()==0 and socket.gethostname()=='KVM-PC'
assert subprocess.check_output(['findmnt','-no','SOURCE','/'],text=True).strip()=='/dev/vda2'
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--desktop-user');p.add_argument('--child-root',type=Path);p.add_argument('--crash',type=int,default=0);a=p.parse_args();project=a.project.resolve();sys.path.insert(0,str(project/'src'))
from manager import gdm_profile,gdm_privileged as endpoint
spec=importlib.util.spec_from_file_location('gdm_fixture',project/'tools/tests/verify-gdm-vm.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
endpoint.ROOT=project
if a.child_root:
 g=fixture.setup(a.child_root);config=gdm_profile.defaults();config['surface']['opacity']=.61
 g.operate('update',gdm_profile.generate(config,project/'src/scss'),crash=a.crash,manager={'format':1,'profile':config});raise SystemExit(0)
user=pwd.getpwnam(a.desktop_user or os.environ['SUDO_USER']);before=subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource']);checks=[]
def check(n,v):checks.append({'name':n,'passed':bool(v)});assert v,n
root=Path(tempfile.mkdtemp(prefix='hyalune-gdm-manager-'))
for n in ['admin','alternatives','state']:(root/n).mkdir()
g=fixture.setup(root);base=root/'base.gresource';base.write_bytes(Path('/usr/share/gnome-shell/gnome-shell-theme.gresource').read_bytes());g.alt('--install',g.LINK,g.GROUP,str(base),'10');g.alt('--auto',g.GROUP);original=g.alternatives()
def call(r):return endpoint.handle(r,g,user)
def apply(value):
 plan=call({'action':'plan','profile':value});return call({'action':'set','profile':value,'plan_token':plan['plan_token']})
value=gdm_profile.defaults();value['background']={'mode':'bundled'}
plan=call({'action':'plan','profile':value});check('plan has no fixture ownership or alternatives change',g.alternatives()==original and g.read(g.STATE/'active.json') is None)
apply(value);owner=g.read(g.STATE/'active.json');check('typed GDM profile stored in existing GDM owner',owner['manager']['profile']['surface']==value['surface'])
check('GDM default overlay bytes match reviewed release',gdm_profile.generate(gdm_profile.defaults(),project/'src/scss')==(project/'build/Hyalune-GDM/overlay.css').read_bytes())
check('status separates pending, conflict and reflection',call({'action':'status'})['reflection']=='next-gdm-session' and not call({'action':'status'})['pending'])
value['background']={'mode':'keep'};value['surface']={'opacity':.47,'color':'#243c48'};value['text']={'mode':'custom','color':'#dffaff'};old_background=owner['background'];apply(value);owner=g.read(g.STATE/'active.json')
css=subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'gdm.css']);check('material and primary text compiled from limited values',b'rgba(36, 60, 72, 0.47)' in css and b'#dffaff' in css)
check('ordinary updates preserve stored background',owner['background']==old_background)
check('original alternatives restoration survives custom edits',owner['original']==original)
hc=subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'gnome-shell-high-contrast.css']);standard_hc=subprocess.check_output(['gresource','extract',str(base),g.PREFIX+'gnome-shell-high-contrast.css']);check('High Contrast resource stays byte-identical',hc==standard_hc)
for evil in ['#fff;@import "/tmp/x"','#{system("id")}']:
 bad=copy.deepcopy(value);bad['surface']['color']=evil
 try:call({'action':'plan','profile':bad});raise AssertionError('accepted CSS')
 except ValueError:pass
check('CSS expressions and caller execution rejected',True)
for extra in ['source','output','python','css','uid']:
 try:call({'action':'status',extra:'/tmp/attacker'});raise AssertionError('accepted extra')
 except ValueError:pass
check('arbitrary source, destination, code and identity rejected',True)
plan=call({'action':'plan','profile':value});other=copy.deepcopy(value);other['surface']['opacity']=.51;apply(other);old=g.read(g.STATE/'active.json')
try:call({'action':'set','profile':value,'plan_token':plan['plan_token']});raise AssertionError('stale accepted')
except ValueError:pass
check('stale GDM plan stopped before changes',g.read(g.STATE/'active.json')==old)
# Create and decode a selected image at the ordinary user's privileges.
folder=Path(user.pw_dir)/'.local/state/glass50'/('gdm-image-fixture-'+uuid.uuid4().hex);folder.mkdir(mode=0o700);os.chown(folder,user.pw_uid,user.pw_gid);png=folder/'selected.png'
code='import gi;gi.require_version("GdkPixbuf","2.0");from gi.repository import GdkPixbuf;p=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,80,50);p.fill(0x33667fff);p.savev('+repr(str(png))+',"png",[],[])'
subprocess.run(['/usr/sbin/runuser','--user',user.pw_name,'--','/usr/bin/python3','-c',code],check=True)
selected=copy.deepcopy(value);selected['background']={'mode':'image','path':str(png)};apply(selected);owner=g.read(g.STATE/'active.json')
check('selected image normalized as caller and copied into owned resource',owner['background']['origin']=='image' and owner['background']['captured_uid']==user.pw_uid and owner['background']['width']==80)
check('private filename is not stored in root profile',str(png) not in json.dumps(owner))
secret=root/'root-only.png';secret.write_bytes(png.read_bytes());secret.chmod(0o600)
try:endpoint.capture_image(g,user,str(secret));raise AssertionError('root file read')
except ValueError:pass
check('image decoder cannot read root-only input',True)
# Reject animation/XML without root-side decoding.
xml=folder/'dynamic.xml';xml.write_text('<background/>');os.chown(xml,user.pw_uid,user.pw_gid)
try:endpoint.capture_image(g,user,str(xml));raise AssertionError('XML accepted')
except ValueError:pass
check('dynamic XML rejected without changing GDM',True)
for cut in [1,3,4,5]:
 old=g.read(g.STATE/'active.json');alt=g.alternatives();r=subprocess.run([sys.executable,__file__,'--project',str(project),'--child-root',str(root),'--crash',str(cut)],capture_output=True,text=True);assert r.returncode==90,(r.stdout,r.stderr)
 result=call({'action':'recover'})
 check('GDM cut '+str(cut)+' recovered or finalized consistently',(result['result']=='committed' if cut==5 else g.read(g.STATE/'active.json')==old and g.alternatives()==alt))
# Existing CLI engine still sees/undoes exactly the same owner.
plan=call({'action':'plan','operation':'remove'});call({'action':'remove','plan_token':plan['plan_token']})
check('remove restores original fixture and keeps transactions',g.alternatives()==original and g.read(g.STATE/'active.json') is None and bool(list((g.STATE/'transactions').iterdir())))
check('real GDM alternatives unchanged',subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'])==before)
print(json.dumps({'status':'passed','root':str(root),'image_fixture':str(folder),'checks':checks},ensure_ascii=False,indent=2))
