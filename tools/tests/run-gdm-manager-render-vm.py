#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Render generated GDM style in a VM-private Shell; no login/authentication."""
import argparse,importlib.util,json,os,signal,socket,subprocess,sys,tempfile,uuid
from pathlib import Path
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);a=p.parse_args();project=a.project.resolve();sys.path.insert(0,str(project/'src'));from manager import gdm_profile
root=Path.home()/'.local/state/glass50/phase5-tests'/('gdm-render-'+uuid.uuid4().hex);root.mkdir(parents=True,mode=0o700)
for name in ['home','config','data','cache']:(root/name).mkdir(mode=0o700)
runtime=Path(tempfile.mkdtemp(prefix='hyalune-gdm-render-'))
spec=importlib.util.spec_from_file_location('gdm_render_engine',project/'tools/manage-gdm.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
value=gdm_profile.defaults();value['surface']={'opacity':.47,'color':'#243c48'};value['text']={'mode':'custom','color':'#dffaff'}
g.build('/usr/share/gnome-shell/gnome-shell-theme.gresource',gdm_profile.generate(value,project/'src/scss'),root/'candidate.gresource',g.bundled_background())
ext=root/'data/gnome-shell/extensions/gdm-manager-render@hyalune.local';ext.mkdir(parents=True);(ext/'metadata.json').write_text(json.dumps({'uuid':'gdm-manager-render@hyalune.local','name':'Private GDM manager rendering','description':'No authentication','shell-version':['50']}));(ext/'extension.js').write_bytes((project/'tools/tests/probe-gdm-manager.js').read_bytes())
k=root/'config/glib-2.0/settings/keyfile';k.parent.mkdir(parents=True);k.write_text("[org/gnome/shell]\nenabled-extensions=['gdm-manager-render@hyalune.local']\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version='50.1'\n[org/gnome/desktop/interface]\ncolor-scheme='prefer-dark'\nenable-animations=false\n[org/gnome/desktop/session]\nidle-delay=uint32 0\n")
env={k:v for k,v in os.environ.items() if k in ['USER','LOGNAME','PATH','LANG','SSH_CONNECTION']};env.update(HOME=str(root/'home'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'),XDG_CACHE_HOME=str(root/'cache'),XDG_RUNTIME_DIR=str(runtime),GSETTINGS_BACKEND='keyfile',HYALUNE_GDM_MANAGER_RENDER=str(root),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',NO_AT_BRIDGE='1',GIO_USE_VFS='local',XDG_SESSION_TYPE='wayland',XDG_CURRENT_DESKTOP='GNOME')
normal=subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip();gdm=subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'])
with (root/'shell.log').open('x') as log:
 process=subprocess.Popen(['dbus-run-session','--','gnome-shell','--headless','--no-x11','--virtual-monitor','1280x800','--wayland-display','gdm-preview'],env=env,stdout=log,stderr=log,start_new_session=True)
 try:process.wait(timeout=35)
 except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
 try:os.killpg(process.pid,signal.SIGKILL)
 except ProcessLookupError:pass
report=json.loads((root/'report.json').read_text());print(json.dumps({'root':str(root),'exit':process.returncode,**report},ensure_ascii=False,indent=2))
assert process.returncode==0 and not report['failed'] and all(row.get('ok') for row in report['rows'])
assert subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip()==normal
assert subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'])==gdm
assert 'Theme parser error' not in (root/'shell.log').read_text()
