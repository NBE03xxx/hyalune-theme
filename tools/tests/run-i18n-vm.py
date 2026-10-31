#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Installed Japanese/English/fallback UI in a private Ubuntu VM session."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import uuid

assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
assert subprocess.check_output(['findmnt','-no','SOURCE','/'],text=True).strip()=='/dev/vda2'
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);a=p.parse_args();project=a.project.resolve()
root=Path.home()/'.local/state/glass50/phase5-tests'/('i18n-'+uuid.uuid4().hex);home=root/'home';home.mkdir(parents=True,mode=0o700)
normal=lambda:subprocess.run(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True,capture_output=True,check=False).stdout
before=normal()
command=[sys.executable,'-B',str(project/'tools/install-manager.py')]
subprocess.run([*command,'install','--test-root',str(home)],check=True,capture_output=True,timeout=80)
installed=home/'.local/share/hyalune/settings/app'
for name in ['src/manager/i18n.py','src/manager/locale/ja/LC_MESSAGES/hyalune.mo']:
    assert (installed/name).read_bytes()==(project/name).read_bytes(),name
# App update owns and preserves the catalogs exactly like any other app file.
subprocess.run([*command,'install','--test-root',str(home)],check=True,capture_output=True,timeout=80)
config=home/'.config';data=home/'.local/share';ext=data/'gnome-shell/extensions/manager-probe@hyalune.local';ext.mkdir(parents=True)
(ext/'metadata.json').write_text(json.dumps({'uuid':ext.name,'name':'Private locale probe','description':'VM only','shell-version':['50']}))
# Shell startup may reopen Overview after extension enable. Keep the private
# test window active so virtual keys reach GTK rather than the search field.
probe=(project/'tools/tests/probe-manager.js').read_text().replace('poll(){', '''poll(){
  Main.overview.hide();
  const window=global.get_window_actors().map(a=>a.meta_window).find(w=>w.get_wm_class()==='io.github.NBE03xxx.Hyalune.Settings');
  if(window)window.activate(global.get_current_time());''')
(ext/'extension.js').write_text(probe)
key=config/'glib-2.0/settings/keyfile';key.parent.mkdir(parents=True)
key.write_text("[org/gnome/shell]\nenabled-extensions=['manager-probe@hyalune.local']\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version='50.1'\n[org/gnome/desktop/interface]\ncolor-scheme='prefer-dark'\nenable-animations=false\n[org/gnome/desktop/session]\nidle-delay=uint32 0\n")
runtime=Path(tempfile.mkdtemp(prefix='hyalune-i18n-'));(root/'portals').mkdir();(data/'gnome-shell/update-check-50').touch()
env={k:v for k,v in os.environ.items() if k in ['USER','LOGNAME','PATH','LANG','SSH_CONNECTION']}
env.update(HOME=str(home),XDG_CONFIG_HOME=str(config),XDG_DATA_HOME=str(data),XDG_CACHE_HOME=str(home/'.cache'),
    XDG_RUNTIME_DIR=str(runtime),GSETTINGS_BACKEND='keyfile',HYALUNE_MANAGER_PROBE=str(root),HYALUNE_MANAGER_HOME=str(home),
    LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',NO_AT_BRIDGE='1',GIO_USE_VFS='local',
    ADW_DISABLE_PORTAL='1',GDK_BACKEND='wayland',GDK_DEBUG='no-portals',GTK_USE_PORTAL='0',
    XDG_SESSION_TYPE='wayland',XDG_CURRENT_DESKTOP='GNOME',XDG_DESKTOP_PORTAL_DIR=str(root/'portals'),LC_ALL='C.UTF-8',LANGUAGE='en')
launcher=root/'session.py'
launcher.write_text('''import json,os,pathlib,subprocess,sys,time
from gi.repository import Gio
root=pathlib.Path(os.environ['HYALUNE_MANAGER_PROBE']);home=pathlib.Path(os.environ['HYALUNE_MANAGER_HOME'])
with (root/'shell.log').open('w') as log:
 shell=subprocess.Popen(['gnome-shell','--headless','--no-x11','--virtual-monitor','1440x1100','--wayland-display','i18n-preview'],stdout=log,stderr=log)
 try:
  for i in range(150):
   if (pathlib.Path(os.environ['XDG_RUNTIME_DIR'])/'i18n-preview').exists():break
   if shell.poll() is not None:raise RuntimeError('Private Shell failed')
   time.sleep(.1)
  else:raise TimeoutError('Wayland socket')
  time.sleep(3);os.environ['WAYLAND_DISPLAY']='i18n-preview'
  for case,language in [('ja','ja'),('en','en'),('fr','fr:ja')]:
   environment=dict(os.environ,LANGUAGE=language,HYALUNE_I18N_CASE=case)
   with (root/(case+'.log')).open('w') as output:
    result=subprocess.run([sys.executable,'-B',sys.argv[1]],env=environment,stdout=output,stderr=output,timeout=50)
   if result.returncode:raise RuntimeError(case+' UI probe failed: '+(root/(case+'.log')).read_text()[-2000:])
 finally:
  shell.terminate()
  try:shell.wait(timeout=5)
  except subprocess.TimeoutExpired:shell.kill();shell.wait()
''')
with (root/'session.log').open('w') as log:
    proc=subprocess.Popen(['dbus-run-session','--',sys.executable,'-B',str(launcher),str(project/'tools/tests/probe-i18n-ui.py')],env=env,stdout=log,stderr=log,start_new_session=True)
    try:proc.wait(timeout=165)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=5)
    try:os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError:pass
assert normal()==before,'Ordinary user Shell processes changed'
if proc.returncode:
    print(json.dumps({'root':str(root),'session_log':(root/'session.log').read_text(),'shell_log':(root/'shell.log').read_text()[-3000:]},indent=2));raise AssertionError('Private locale session failed')
reports={case:json.loads((root/(case+'-result.json')).read_text()) for case in ('ja','en','fr')}
profiles=[home/'.config/hyalune'/n for n in ('profile.json','gdm.json')];saved={str(p):p.read_bytes() for p in profiles}
subprocess.run([*command,'remove','--test-root',str(home)],check=True,capture_output=True,timeout=50)
assert not (installed/'src/manager/locale/ja/LC_MESSAGES/hyalune.mo').exists()
assert all(p.read_bytes()==saved[str(p)] for p in profiles),'App removal changed saved profiles'
print(json.dumps({'status':'passed','root':str(root),'installed_catalog_verified':True,'update_verified':True,
    'removal_retains_profiles':True,'reports':reports},ensure_ascii=False,indent=2))
