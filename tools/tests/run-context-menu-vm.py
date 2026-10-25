#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the context-menu continuity regression in a VM-private Wayland Shell."""
import argparse,json,os,pathlib,re,signal,socket,subprocess,sys,time,uuid
assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
assert subprocess.check_output(['findmnt','-no','SOURCE','/'],text=True).strip()=='/dev/vda2'
assert os.geteuid()!=0
assert subprocess.check_output(['gnome-shell','--version'],text=True).strip()=='GNOME Shell 50.1'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--project',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[2])
p.add_argument('--label',default='context-menu-'+uuid.uuid4().hex[:8])
p.add_argument('--managed-context',action='store_true',help='Exercise the normal installed runtime marker in the private Shell')
p.add_argument('--animations',action=argparse.BooleanOptionalAction,default=True)
a=p.parse_args();project=a.project.resolve()
if not re.fullmatch(r'context-menu-[a-z0-9-]{1,16}',a.label):p.error('Invalid private run label')
normal=subprocess.check_output(['pgrep','-x','gnome-shell'],text=True).strip();assert normal.isdecimal()
root=pathlib.Path.home()/'.local/state/glass50'/a.label
if len(os.fsencode(root/'runtime/gnome-shell-test-display'))>=108:p.error('Socket path too long')
root.mkdir(mode=0o700,exist_ok=False)
files={'showcase.js':project/'tools/tests/probe-context-menu.js','backdrop.py':project/'tools/tests/context-menu-backdrop.py','material.css':project/'build/Glass50-Material-Preview/gtk-4.0/material.css','build/Glass50-Material-Preview/gnome-shell/gnome-shell.css':project/'build/Glass50-Material-Preview/gnome-shell/gnome-shell.css'}
for f in (project/'src/extension').rglob('*'):
 if f.is_file() and '__pycache__' not in f.parts:files['extension/'+str(f.relative_to(project/'src/extension'))]=f
for f in (project/'src/effects').glob('*.js'):files['extension/effects/'+f.name]=f
for n,source in files.items():
 assert not pathlib.Path(n).is_absolute() and '..' not in pathlib.Path(n).parts
 p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(source.read_bytes())
# Solid background needs no third-party image fixture.
(root/'runtime').mkdir(mode=0o700);(root/'portals').mkdir();(root/'home/Showcase').mkdir(parents=True)
for n in ['Documents','Pictures','Projects']:(root/'home/Showcase'/n).mkdir()
(root/'home/Showcase/Welcome.txt').write_text('Glass50 Dark\nA clear view, even when windows overlap.\n')
subprocess.run(['glib-compile-schemas','--strict',str(root/'extension/schemas')],check=True)
env={k:os.environ[k] for k in ['USER','LOGNAME','PATH','LANG','SSH_CONNECTION'] if k in os.environ}
env.update(XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'),XDG_CACHE_HOME=str(root/'cache'),GSETTINGS_BACKEND='keyfile',GDK_BACKEND='wayland',GDK_DEBUG='no-portals',GTK_USE_PORTAL='0',HOME=str(pathlib.Path.home()),XDG_RUNTIME_DIR=str(root/'runtime'),GLASS50_ISOLATED_PROBE='1',GLASS50_PROBE_OUTPUT=str(root),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',NO_AT_BRIDGE='1',GIO_USE_VFS='local',ADW_DISABLE_PORTAL='1',WAYLAND_DISPLAY='gnome-shell-test-display',XDG_SESSION_TYPE='wayland',XDG_CURRENT_DESKTOP='GNOME',XDG_DESKTOP_PORTAL_DIR=str(root/'portals'),LANGUAGE='en_US',LC_ALL='C.UTF-8')
if a.managed_context:
 env.pop('GLASS50_ISOLATED_PROBE')
 env['GLASS50_MANAGED_PROBE']='1';env['HOME']=str(root/'home')
 marker=root/'home/.local/state/glass50/installer-material-v1/runtime.json'
 marker.parent.mkdir(parents=True);marker.write_text(json.dumps({'format':1,'target':'desktop','shell_major':50}));marker.chmod(0o600)
own=root/'data/gnome-shell/extensions/glass50-blur@myglass.local'
import shutil
own.parent.mkdir(parents=True);(own.parent.parent/'update-check-50').touch(exist_ok=False);shutil.copytree(root/'extension',own)
driver=own.parent/'showcase@myglass.local';driver.mkdir()
(driver/'metadata.json').write_text(json.dumps({'uuid':'showcase@myglass.local','name':'Private showcase','description':'Private only','shell-version':['50']}))
(driver/'showcase.js').write_bytes((root/'showcase.js').read_bytes())
(driver/'extension.js').write_text("import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';import {init} from './showcase.js';export default class Showcase extends Extension {enable(){init();}disable(){}}\n")
k=root/'config/glib-2.0/settings/keyfile';k.parent.mkdir(parents=True)
k.write_text("[org/gnome/shell]\nenabled-extensions=['glass50-blur@myglass.local', 'showcase@myglass.local']\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version='50.1'\n[org/gnome/desktop/background]\nprimary-color='#30251f'\nsecondary-color='#30251f'\ncolor-shading-type='solid'\npicture-uri=''\npicture-uri-dark=''\n[org/gnome/desktop/lockdown]\ndisable-lock-screen=true\n[org/gnome/desktop/session]\nidle-delay=uint32 0\n[org/gnome/desktop/interface]\ncolor-scheme='prefer-dark'\nenable-animations=false\nenable-hot-corners=false\n".replace('enable-animations=false','enable-animations='+str(a.animations).lower()))
(root/'warmup.py').write_text("import gi;gi.require_version('Gtk','4.0');from gi.repository import Gtk,Gio,GLib\na=Gtk.Application(application_id='local.myglass.Warmup',flags=Gio.ApplicationFlags.NON_UNIQUE)\ndef go(a):\n w=Gtk.ApplicationWindow(application=a,title='Private startup',default_width=32,default_height=32);w.present();GLib.timeout_add(1500,lambda:(a.quit(),False)[1])\na.connect('activate',go);a.run([])\n")
(root/'start.py').write_text("import subprocess,os,time,pathlib,sys\nr=pathlib.Path(sys.argv[1]);c=subprocess.Popen(['gnome-shell','--headless','--no-x11','--virtual-monitor','1920x1200','--wayland-display','gnome-shell-test-display'])\nfor i in range(150):\n if (r/'runtime/gnome-shell-test-display').exists():break\n time.sleep(.05)\nw=subprocess.Popen(['python3',str(r/'warmup.py')],env=dict(os.environ,HOME=str(r/'home')))\nc.wait();w.wait();sys.exit(c.returncode)\n")
cmd=['dbus-run-session','--','python3',str(root/'start.py'),str(root)]

with (root/'stdout.log').open('x') as out,(root/'stderr.log').open('x') as err:
 c=subprocess.Popen(cmd,env=env,stdout=out,stderr=err,start_new_session=True)
 try:c.wait(timeout=110)
 except subprocess.TimeoutExpired:
  os.killpg(c.pid,signal.SIGTERM)
  try:c.wait(timeout=3)
  except subprocess.TimeoutExpired:os.killpg(c.pid,signal.SIGKILL);c.wait()
# Clean only the process group created for this private run.
try:os.killpg(c.pid,signal.SIGKILL)
except ProcessLookupError:pass
time.sleep(1)
after=subprocess.check_output(['pgrep','-x','gnome-shell'],text=True).strip()
report=json.loads((root/'report.json').read_text()) if (root/'report.json').exists() else {}
checks=report.get('checks',{})
# Check rendered foreground pixels as well as enabled flags: a blur layer above
# a native actor can otherwise pass continuity checks while hiding all text.
# Use just the Documents label, excluding legitimate focus/selection borders.
if checks and (root/'00-baseline.png').exists() and len(list(root.glob('*-closed-*.png')))==4:
 from PIL import Image, ImageChops, ImageStat
 baseline=Image.open(root/'00-baseline.png').convert('RGB').crop((502,375,578,391))
 closed=sorted(root.glob('*-closed-*.png'))
 differences=[sum(ImageStat.Stat(ImageChops.difference(baseline,Image.open(f).convert('RGB').crop((502,375,578,391)))).mean)/3 for f in closed]
 checks['foreground_pixels_restored']=len(differences)==4 and max(differences)<2
 # A former popup rectangle must not remain a sharp hole in the backdrop.
 back=Image.open(root/'00-baseline.png').convert('RGB').crop((902,675,1100,725))
 background_differences=[sum(ImageStat.Stat(ImageChops.difference(back,Image.open(f).convert('RGB').crop((902,675,1100,725)))).mean)/3 for f in closed]
 checks['background_pixels_restored']=len(background_differences)==4 and max(background_differences)<2
 report['background_mean_pixel_errors']=background_differences
 report['checks']=checks;report['foreground_mean_pixel_errors']=differences
 (root/'report.json').write_text(json.dumps(report,indent=2))
if checks and 'foreground_pixels_restored' not in checks:
 checks['foreground_pixels_restored']=checks['background_pixels_restored']=False
 (root/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'exit':c.returncode,'normal_before':normal,'normal_after':after,'root':str(root),'checks':checks},indent=2))
assert after==normal and c.returncode==0 and checks and all(checks.values())
