#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""App lifecycle and menu-launch checks inside a dedicated VM HOME and bus."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
assert subprocess.check_output(['findmnt','-no','SOURCE','/'],text=True).strip()=='/dev/vda2'
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);a=p.parse_args();project=a.project.resolve()
root=Path.home()/'.local/state/glass50/phase5-tests'/('manager-ui-'+uuid.uuid4().hex);root.mkdir(parents=True,mode=0o700);home=root/'home';home.mkdir()
checks=[]
def check(n,v):checks.append({'name':n,'passed':bool(v)});assert v,n
def command(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=50);assert r.returncode==0,(r.returncode,r.stdout,r.stderr);return json.loads(r.stdout)
def app_install(action):return command([sys.executable,str(project/'tools/install-manager.py'),action,'--test-root',str(home)])
# Seed the ordinary appearance through the manager, not through the GUI.
sys.path.insert(0,str(project/'src'));from manager import profile
req=root/'request.json';request={'profile':profile.defaults(),'apps':[]};req.write_text(json.dumps(request))
cmd=[sys.executable,str(project/'tools/manage-settings.py')]
plan=command([*cmd,'plan','--test-root',str(home),'--request',str(req)])
request['plan_token']=plan['result']['manager']['token'];req.write_text(json.dumps(request))
command([*cmd,'set','--test-root',str(home),'--request',str(req)])
owner=home/'.local/state/glass50/installer-material-v1/active.json';appearance=owner.read_bytes()
app_install('install');entry=home/'.local/share/applications/io.github.NBE03xxx.Hyalune.Settings.desktop'
check('app, menu entry and icon installed',entry.is_file() and (home/'.local/share/hyalune/settings/app/tools/hyalune-settings.py').is_file() and (home/'.local/share/icons/hicolor/scalable/apps/io.github.NBE03xxx.Hyalune.Settings.svg').is_file())
import gi
gi.require_version('GdkPixbuf','2.0')
from gi.repository import GdkPixbuf
icon=GdkPixbuf.Pixbuf.new_from_file(str(home/'.local/share/icons/hicolor/scalable/apps/io.github.NBE03xxx.Hyalune.Settings.svg'))
check('installed SVG decodes through the system image loader',icon.get_width()==128 and icon.get_height()==128)
app_install('install');check('updating the app preserves appearance ownership',owner.read_bytes()==appearance)
runtime=Path(tempfile.mkdtemp(prefix='hyalune-ui-'))
for name in ['config','data','cache']:(root/name).mkdir(mode=0o700)
ext=root/'data/gnome-shell/extensions/manager-probe@hyalune.local';ext.mkdir(parents=True)
(ext/'metadata.json').write_text(json.dumps({'uuid':'manager-probe@hyalune.local','name':'Private manager probe','description':'VM only','shell-version':['50']}))
(ext/'extension.js').write_bytes((project/'tools/tests/probe-manager.js').read_bytes())
key=root/'config/glib-2.0/settings/keyfile';key.parent.mkdir(parents=True)
key.write_text("[org/gnome/shell]\nenabled-extensions=['manager-probe@hyalune.local']\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version='50.1'\n[org/gnome/desktop/interface]\ncolor-scheme='prefer-dark'\nenable-animations=false\n[org/gnome/desktop/session]\nidle-delay=uint32 0\n[org/gnome/desktop/background]\npicture-uri=''\npicture-uri-dark=''\nprimary-color='#285b62'\n")
env={k:v for k,v in os.environ.items() if k in ['USER','LOGNAME','PATH','LANG','SSH_CONNECTION']}
env.update(HOME=str(home),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'),XDG_CACHE_HOME=str(root/'cache'),XDG_RUNTIME_DIR=str(runtime),GSETTINGS_BACKEND='keyfile',HYALUNE_MANAGER_PROBE=str(root),HYALUNE_MANAGER_HOME=str(home),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',NO_AT_BRIDGE='1',GIO_USE_VFS='local',XDG_SESSION_TYPE='wayland',XDG_CURRENT_DESKTOP='GNOME',LC_ALL='C.UTF-8',LANGUAGE='ja')
# This child starts Shell, then the installed desktop entry via Gio. A second
# process drives the same installed module for widget/keyboard assertions.
child=root/'session.py'
child.write_text('''import os,pathlib,subprocess,time,signal,sys
from gi.repository import Gio,GLib
root=pathlib.Path(os.environ['HYALUNE_MANAGER_PROBE']);home=pathlib.Path(os.environ['HYALUNE_MANAGER_HOME'])
normal=None
with (root/'shell.log').open('w') as log:
 shell=subprocess.Popen(['gnome-shell','--headless','--no-x11','--virtual-monitor','1280x900','--wayland-display','manager-preview'],stdout=log,stderr=log)
 try:
  for i in range(100):
   if (pathlib.Path(os.environ['XDG_RUNTIME_DIR'])/'manager-preview').exists():break
   if shell.poll() is not None:raise RuntimeError('Shell failed')
   time.sleep(.1)
  os.environ['WAYLAND_DISPLAY']='manager-preview';time.sleep(2)
  # Menu launch is a real desktop-entry launch from a directory outside source.
  entry=home/'.local/share/applications/io.github.NBE03xxx.Hyalune.Settings.desktop'
  app=Gio.DesktopAppInfo.new_from_filename(str(entry));assert app and app.get_name()=='Hyalune 設定'
  app.launch([],None);time.sleep(4)
  # Use the session D-Bus application to prove it owns the expected ID.
  bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
  pid=bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID',GLib.Variant('(s)',('io.github.NBE03xxx.Hyalune.Settings',)),None,Gio.DBusCallFlags.NONE,3000,None).unpack()[0]
  assert pathlib.Path('/proc',str(pid)).stat().st_uid==os.getuid()
  (root/'menu-launch.json').write_text('true')
  os.kill(pid,signal.SIGTERM);time.sleep(.5)
  probe=subprocess.run([sys.executable,sys.argv[1]],timeout=70,stdout=log,stderr=log)
  assert probe.returncode==0
 finally:
  shell.terminate()
  try:shell.wait(timeout=5)
  except subprocess.TimeoutExpired:shell.kill();shell.wait()
''')
normal=subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip()
with (root/'session.log').open('x') as log:
 process=subprocess.Popen(['dbus-run-session','--',sys.executable,str(child),str(project/'tools/tests/probe-manager-ui.py')],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
 try:process.wait(timeout=95)
 except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
 try:os.killpg(process.pid,signal.SIGKILL)
 except ProcessLookupError:pass
check('normal VM Shell survives independent GUI session',subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip()==normal)
if process.returncode:
 print((root/'session.log').read_text());print((root/'shell.log').read_text()[-6000:]);raise AssertionError('GUI session failed: '+str(root))
check('desktop entry launches installed application outside checkout',(root/'menu-launch.json').exists())
ui=json.loads((root/'ui-result.json').read_text());check('UI and real keyboard assertions pass',ui['status']=='passed')
check('preview, save and cancellation never change installed theme ownership',owner.read_bytes()==appearance)
profile_file=home/'.config/hyalune/profile.json';profile_bytes=profile_file.read_bytes();gdm_file=home/'.config/hyalune/gdm.json';gdm_bytes=gdm_file.read_bytes()
app_install('remove');check('app removal removes entry and executable but retains profiles and theme',not entry.exists() and not(home/'.local/share/hyalune/settings/app/tools/hyalune-settings.py').exists() and profile_file.read_bytes()==profile_bytes and owner.read_bytes()==appearance and gdm_file.read_bytes()==gdm_bytes)
# Interrupted application installation uses its own journal; appearance stays out.
cut=root/'app-interruption';cut.mkdir()
def install_cut(action,expected=0,flags=()):
 r=subprocess.run([sys.executable,str(project/'tools/install-manager.py'),action,'--test-root',str(cut),*flags],capture_output=True,text=True,timeout=45)
 assert r.returncode==expected,(r.returncode,r.stdout,r.stderr)
 return r
install_cut('install',86,('--crash-after','2'));install_cut('recover')
check('interrupted app install recovers without orphaned entry',not(cut/'.local/share/applications/io.github.NBE03xxx.Hyalune.Settings.desktop').exists() and not(cut/'.local/state/hyalune/settings-installer-v1/pending.json').exists())
install_cut('install');installed=cut/'.local/share/hyalune/settings/app/tools/hyalune-settings.py';saved=installed.read_bytes();installed.write_bytes(saved+b'\n# external change\n')
install_cut('install',1);check('app update refuses external edits',installed.read_bytes()==saved+b'\n# external change\n')
installed.write_bytes(saved);install_cut('remove')
print(json.dumps({'status':'passed','root':str(root),'checks':checks,'ui':ui},ensure_ascii=False,indent=2))
