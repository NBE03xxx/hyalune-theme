#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise default public entry, link restoration, migrations and interruption."""
import argparse,base64,configparser,hashlib,json,os,shutil,socket,stat,subprocess,sys,uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--legacy-package',type=Path);p.add_argument('--migration-only',action='store_true');a=p.parse_args();project=a.project.resolve();package=(a.legacy_package or a.package).resolve()
root=Path.home()/'.local/state/glass50/phase5-tests'/('desktop-'+uuid.uuid4().hex);root.mkdir(parents=True,mode=0o700)
state='.local/state/glass50/installer-material-v1';links=['.config/gtk-4.0/gtk.css','.config/gtk-4.0/gtk-dark.css'];include='.config/gtk-4.0/glass50-managed.css';checks=[]
def check(n,v):checks.append({'name':n,'passed':bool(v)});assert v,n
def call(h,args,expected=0):
 r=subprocess.run([str(project/'install.sh'),*args,'--test-root',str(h)],capture_output=True,text=True,timeout=45)
 assert r.returncode==expected,(args,r.returncode,r.stdout[-1000:],r.stderr)
 return json.loads(r.stdout) if expected==0 else r
def env(h):return dict(os.environ,HOME=str(h),XDG_CONFIG_HOME=str(h/'.config'),XDG_DATA_HOME=str(h/'.local/share'),XDG_STATE_HOME=str(h/'.local/state'),GSETTINGS_BACKEND='keyfile')
def prefs(h):
 c=configparser.ConfigParser(interpolation=None);c.read(h/'.config/glib-2.0/settings/keyfile');return {s:dict(c[s]) for s in c if s!='DEFAULT' and dict(c[s])}
def tree(h):
 d={}
 for f in h.rglob('*'):
  n=str(f.relative_to(h))
  if n.startswith('.local/state/glass50/') or n=='.config/glib-2.0/settings/keyfile':continue
  if f.is_symlink():d[n]=('link',os.readlink(f))
  elif f.is_file():d[n]=(hashlib.sha256(f.read_bytes()).hexdigest(),stat.S_IMODE(f.stat().st_mode))
 return d
def fresh(label,kind='links'):
 h=root/label;h.mkdir();folder=h/'.config/gtk-4.0';folder.mkdir(parents=True)
 if kind=='links':
  f=folder/'old.css';f.write_text('/* original linked CSS */\n');f.chmod(0o640)
  for n in links:(h/n).symlink_to('old.css')
 elif kind=='files':
  for n in links:(h/n).write_text('/* original regular CSS */\n');(h/n).chmod(0o600)
 return h
if not a.migration_only:
 for kind in ['links','files','absent']:
  h=fresh(kind,kind);before=tree(h);q=call(h,['plan','--blur','off','--flatpak','none']);check(kind+': plan has no writes',tree(h)==before and not(h/state).exists())
  r=call(h,['apply','--blur','off','--flatpak','none']);owner=json.loads((h/state/'active.json').read_text())
  check(kind+': generic ownership and normal runtime marker',owner['target']=='desktop' and owner['desktop']['layout']=='desktop' and json.loads((h/state/'runtime.json').read_text())['shell_major']==50)
  check(kind+': both GTK entry points use owned include',all(not(h/n).is_symlink() and b'glass50-managed.css' in(h/n).read_bytes() for n in links))
  if kind=='links':check('linked source bytes/mode backed up without mutation',tree(h)['.config/gtk-4.0/old.css']==before['.config/gtk-4.0/old.css'] and all(n in owner['desktop']['referents'] for n in links))
  call(h,['update','--blur','on']);before_prefs=prefs(h);r=call(h,['remove']);check(kind+': complete restore with one command',tree(h)==before and not(h/state/'active.json').exists() and not prefs(h))
  check(kind+': all extra marker ownership removed',not(h/state/'runtime.json').exists() and not(h/state/'t16-runtime.json').exists())
 # Actual material file changes and generic include + entry + owner cut points.
 h=fresh('cuts');before=tree(h);q=call(h,['plan','--blur','on','--flatpak','none']);names=[n['name'] for n in q['targets']]
 check('marker and files are staged before extension enable',names.index(state+'/runtime.json')<names.index('enabled-extensions'))
 cuts=sorted(set([1,names.index(links[0])+1,names.index(state+'/runtime.json')+1,len(names)]))
 for cut in cuts:
  for flag,exit in [('--fail-after',1),('--crash-after',86)]:
   h=fresh(flag[2:]+str(cut));before=tree(h);call(h,['apply','--blur','on','--flatpak','none',flag,str(cut)],expected=exit)
   if exit==86:call(h,['recover'])
   check(flag+' apply restores original links at '+str(cut),tree(h)==before and not prefs(h) and not(h/state/'pending.json').exists())
 h=fresh('remove-cuts');before=tree(h);call(h,['apply','--flatpak','none']);installed=tree(h);owner=(h/state/'active.json').read_bytes();q=call(h,['plan','--operation','remove'])
 for cut in [1,len(q['targets'])]:
  call(h,['remove','--crash-after',str(cut)],86);call(h,['recover']);check('remove recovery including missing owner at '+str(cut),tree(h)==installed and(h/state/'active.json').read_bytes()==owner)
 call(h,['remove','--crash-after-commit'],86);r=call(h,['recover']);check('committed generic removal finalized',r['status']=='commit-finalized' and tree(h)==before)
 h=fresh('edited');call(h,['apply','--flatpak','none']);(h/links[1]).write_text('/* later independent change */');before=tree(h);call(h,['remove'],1);check('entry conflict stops entire removal',tree(h)==before and(h/state/'active.json').exists())
 h=fresh('parent-link');shutil.rmtree(h/'.config/gtk-4.0');out=root/'outside';out.mkdir();(h/'.config/gtk-4.0').symlink_to(out);call(h,['apply','--flatpak','none'],1);check('parent link never followed',not list(out.iterdir()))
 h=fresh('conflict');subprocess.run(['gsettings','set','org.gnome.shell','enabled-extensions',"['blur-my-shell@aunetx']"],env=env(h),check=True,capture_output=True);before=tree(h);v=prefs(h);call(h,['apply','--flatpak','none'],1);check('known competing blur stops before files or preferences change',tree(h)==before and prefs(h)==v)
# Migrate real historical planners, without replacing the desktop user's state.
code="""import importlib.util,sys
from pathlib import Path
p=Path(sys.argv.pop(1));s=importlib.util.spec_from_file_location('material',p/'manage-material.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
if sys.argv[1]=='trial':
 sys.argv.pop(1);vm=m.core.guard;s=importlib.util.spec_from_file_location('trial',p/'manage-t16.py');t=importlib.util.module_from_spec(s);s.loader.exec_module(t);t.configure(m);m.core.guard=vm
else:sys.argv.pop(1)
sys.exit(m.main())
"""
for kind in ['trial','legacy']:
 h=fresh('migration-'+kind,'links' if kind=='trial' else 'files');before=tree(h)
 if kind=='trial':
  original_members=['user-theme@gnome-shell-extensions.gcampax.github.com','blur-my-shell@aunetx','dash-to-dock@micxgx.gmail.com','top-panel-logo@jmpegi.github.com','just-perfection-desktop@just-perfection','unrelated@example.test']
  subprocess.run(['gsettings','set','org.gnome.shell','enabled-extensions',repr(original_members)],env=env(h),check=True,capture_output=True)
 original_preferences=prefs(h)
 args=[sys.executable,'-c',code,str(package),kind,'apply','--blur','off','--package',str(package),'--test-root',str(h)]
 r=subprocess.run(args,capture_output=True,text=True);assert r.returncode==0,(r.stdout,r.stderr)
 original=json.loads((h/state/'active.json').read_text())
 if kind=='trial':
  members=['user-theme@gnome-shell-extensions.gcampax.github.com','unrelated@example.test','dash-to-dock@micxgx.gmail.com','top-panel-logo@jmpegi.github.com']
  subprocess.run(['gsettings','set','org.gnome.shell','enabled-extensions',repr(members)],env=env(h),check=True,capture_output=True)
 q=call(h,['plan','--operation','update']);call(h,['update'])
 migrated=json.loads((h/state/'active.json').read_text())
 check(kind+': all original native/settings restoration data retained',all(migrated[k]==original[k] for k in ['originals','settings_before','css_original','enabled_before_effective']))
 check(kind+': existing layout auto-detected without target flag',migrated['target']=='desktop' and migrated['desktop']['layout']==('legacy-t16' if kind=='trial' else 'legacy-import'))
 if kind=='legacy':
  entry=h/links[0];saved_bytes=entry.read_bytes();saved_mode=stat.S_IMODE(entry.stat().st_mode)
  external=root/'legacy-external.css';external.write_text('/* independent referent */');entry.unlink();entry.symlink_to(external)
  changed=tree(h);call(h,['remove'],1)
  check('legacy import later symlink rejected without following it',tree(h)==changed and external.read_text()=='/* independent referent */')
  entry.unlink();entry.write_bytes(saved_bytes);entry.chmod(saved_mode)
 if kind=='trial':
  check('trial original entry and membership metadata retained',migrated['t16_trial']==original['t16_trial'])
  check('migration never pauses user-reenabled dock/logo',not any(op['name']=='enabled-extensions' for op in q['targets']))
 call(h,['remove','--crash-after',str(len(call(h,['plan','--operation','remove'])['targets']))],86);call(h,['recover']);check(kind+': removal recovery handles owner absence',(h/state/'active.json').exists())
 call(h,['remove']);check(kind+': migrated uninstall restores original entry files/links',tree(h)==before and prefs(h)==original_preferences)
print(json.dumps({'status':'passed','root':str(root),'checks':checks},indent=2))
