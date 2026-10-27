#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""VM-private Light blur, High Contrast, Reduced Motion and Dark regression."""
import json,os,pathlib,signal,socket,subprocess,sys,tempfile,uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
import argparse
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True);a=p.parse_args();project=a.project.resolve();driver=project/'tools/tests/probe-light-effects.js';root=Path.home()/'.local/state/glass50/phase5-tests'/('light-render-'+uuid.uuid4().hex);root.mkdir(mode=0o700)
for n in ['home','config','data','cache']:(root/n).mkdir()
runtime=Path(tempfile.mkdtemp(prefix='hy-light-'))
ext=root/'data/gnome-shell/extensions/light-probe@hyalune.local';ext.mkdir(parents=True);(ext/'metadata.json').write_text(json.dumps({'uuid':'light-probe@hyalune.local','name':'Private Light preview','description':'VM only','shell-version':['50']}));(ext/'extension.js').write_bytes(driver.read_bytes())
import shutil
own=root/'data/gnome-shell/extensions/glass50-blur@myglass.local';shutil.copytree(project/'src/extension',own);shutil.copytree(project/'src/effects',own/'effects');subprocess.run(['glib-compile-schemas',str(own/'schemas')],check=True)
k=root/'config/glib-2.0/settings/keyfile';k.parent.mkdir(parents=True);k.write_text("[org/gnome/shell]\nenabled-extensions=['glass50-blur@myglass.local','light-probe@hyalune.local']\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version='50.1'\n[org/gnome/desktop/interface]\ncolor-scheme='prefer-light'\nenable-animations=false\n[org/gnome/desktop/session]\nidle-delay=uint32 0\n[org/gnome/desktop/background]\npicture-uri=''\npicture-uri-dark=''\nprimary-color='#285b62'\n")
env={k:v for k,v in os.environ.items() if k in ['USER','LOGNAME','PATH','LANG','SSH_CONNECTION']};env.update(HOME=str(root/'home'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'),XDG_CACHE_HOME=str(root/'cache'),XDG_RUNTIME_DIR=str(runtime),GLASS50_ISOLATED_PROBE='1',GSETTINGS_BACKEND='keyfile',HYALUNE_LIGHT_ROOT=str(root),HYALUNE_LIGHT_PROJECT=str(project),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',PYTHONFAULTHANDLER='1',PYTHONUNBUFFERED='1',NO_AT_BRIDGE='1',GIO_USE_VFS='local',XDG_SESSION_TYPE='wayland',XDG_CURRENT_DESKTOP='GNOME')
normal=subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip()
with (root/'shell.log').open('x') as log:
 launcher=root/'launch.py'
 launcher.write_text('''import os,pathlib,subprocess,time,sys
r=pathlib.Path(os.environ['XDG_RUNTIME_DIR']);s=subprocess.Popen(['gnome-shell','--headless','--no-x11','--virtual-monitor','1600x1000','--wayland-display','light-preview'])
for _ in range(100):
 if (r/'light-preview').exists():break
 time.sleep(.1)
os.environ['WAYLAND_DISPLAY']='light-preview'
time.sleep(3)\nchildren=[subprocess.Popen([sys.executable,sys.argv[1],kind]) for kind in ['3','4']]
s.wait()
for c in children:print('child status',c.pid,c.poll(),flush=True);c.terminate()
sys.exit(s.returncode)
''')
 proc=subprocess.Popen(['dbus-run-session','--',sys.executable,str(launcher),str(project/'tools/tests/light-gtk-preview.py')],env=env,stdout=log,stderr=log,start_new_session=True)
 try:proc.wait(timeout=55)
 except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=5)
 try:os.killpg(proc.pid,signal.SIGKILL)
 except ProcessLookupError:pass
import time;time.sleep(.4)
print(json.dumps({'root':str(root),'exit':proc.returncode}));print((root/'shell-result.json').read_text() if (root/'shell-result.json').exists() else (root/'shell.log').read_text()[-6000:])
assert subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip()==normal
assert proc.returncode==0 and not json.loads((root/'shell-result.json').read_text())['failed']
