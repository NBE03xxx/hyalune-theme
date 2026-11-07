#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise Qt ownership, rollback, recovery and ABI-aware launchers in VM HOME fixtures."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import uuid

assert socket.gethostname()=='KVM-PC' and os.environ.get('SSH_CONNECTION')
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--project',type=Path,required=True)
p.add_argument('--fixtures',type=Path)
a=p.parse_args()
project=a.project.resolve()
root=Path.home()/'.local/state/glass50/phase5-tests'/('qt-install-'+uuid.uuid4().hex)
root.mkdir(parents=True)
checks=[]


def check(condition,label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)


def fixture(label):
    home=root/label
    entries=home/'.local/share/applications'
    entries.mkdir(parents=True)
    for name in ['setup-mozc.desktop','ibus-setup-mozc-jp.desktop',
                 'com.nextcloud.desktopclient.nextcloud.desktop','org.keepassxc.KeePassXC.desktop']:
        source=a.fixtures/name if a.fixtures else Path('/usr/share/applications')/name
        if not source.exists():
            source=Path('/var/lib/flatpak/exports/share/applications')/name
        shutil.copyfile(source,entries/name)
        (entries/name).chmod(0o640)
    auto=home/'.config/autostart/Nextcloud.desktop'
    auto.parent.mkdir(parents=True)
    auto.write_text('[Desktop Entry]\nType=Application\nName=Nextcloud\nExec="/usr/bin/nextcloud" --background\n')
    return home


def files(home):
    return {str(p.relative_to(home)):(p.read_bytes(),stat.S_IMODE(p.stat().st_mode))
            for p in home.rglob('*') if p.is_file() and '.local/state/' not in str(p.relative_to(home))}


def run(home,action,*extra,ok=True):
    proc=subprocess.run([sys.executable,'-B',str(project/'tools/manage-qt.py'),action,
                         '--test-root',str(home),*extra],capture_output=True,text=True)
    if ok and proc.returncode:
        raise RuntimeError(proc.stderr+proc.stdout)
    if not ok:
        check(proc.returncode!=0,action+' rejected')
        return proc
    return json.loads(proc.stdout)


home=fixture('normal')
original=files(home)
plan=run(home,'plan')
check(len(plan['targets'])>10,'nonempty plan')
check(files(home)==original,'plan did not change launchers')
run(home,'install')
status=run(home,'status')
check(status['managed'] and not status['pending'] and not status['conflicts'],'installed ownership')
owner_path=home/'.local/state/hyalune/qt-installer-v1/active.json'
owner=json.loads(owner_path.read_text())
originals=copy.deepcopy(owner['originals'])
check(not run(home,'plan')['targets'],'idempotent update plan')
check('runtime/launch.py' in (home/'.config/autostart/Nextcloud.desktop').read_text(),'autostart wrapper')
check('theme-service.py' in (home/'.local/share/dbus-1/services/io.github.NBE03xxx.Hyalune.QtAppearance.service').read_text(),'session policy entry')
version_path=project/'build/Hyalune-Qt/manifest.json'
version_bytes=version_path.read_bytes()
try:
    manifest=json.loads(version_bytes)
    manifest['version']='0.1.0-qt-preview.2'
    version_path.write_text(json.dumps(manifest))
    run(home,'install')
    changed=json.loads(owner_path.read_text())
    check(changed['originals']==originals,'update preserved original settings')
    check(changed['version']=='0.1.0-qt-preview.2','update committed')
finally:
    version_path.write_bytes(version_bytes)
entry=home/'.local/share/applications/setup-mozc.desktop'
installed=entry.read_bytes()
entry.write_bytes(installed+b'# personal change\n')
before=files(home)
run(home,'remove',ok=False)
check(files(home)==before,'conflict stopped before any write')
entry.write_bytes(installed)
run(home,'remove')
check(files(home)==original,'remove restored bytes and modes')
run(home,'install')
check(not run(home,'status')['conflicts'],'reinstall')
run(home,'remove')
for number in [1,len(plan['targets'])]:
    trial=fixture('failure-'+str(number))
    before=files(trial)
    run(trial,'install','--fail-after',str(number),ok=False)
    check(files(trial)==before,'rollback '+str(number))
    check(not run(trial,'status')['pending'],'rollback cleared pending '+str(number))
trial=fixture('crash')
before=files(trial)
proc=run(trial,'install','--crash-after','3',ok=False)
check(proc.returncode==86,'interrupted transaction')
check(run(trial,'status')['pending'],'pending recorded')
run(trial,'install',ok=False)
run(trial,'recover')
check(files(trial)==before,'recover restored bytes and modes')
check(not run(trial,'status')['pending'],'recover cleared pending')
spec=importlib.util.spec_from_file_location('qt_launch_test',project/'src/qt/launch.py')
launcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
manifest=json.loads(version_bytes)
manifest['flatpak_scope']='user' if os.environ.get('FLATPAK_USER_DIR') else 'system'
prefix=project/'build/Hyalune-Qt'
env={}
argv=launcher.command('mozc',['--mode=config_dialog'],prefix,env,manifest)
check(argv==['/usr/lib/mozc/mozc_tool','--mode=config_dialog'] and env.get('QT_WAYLAND_DECORATION')=='hyalune','scoped native environment')
bad=copy.deepcopy(manifest)
bad['variants']['native5']['abi']='5.0.0'
env={}
launcher.command('mozc',[],prefix,env,bad)
check(not env,'ABI mismatch uses original environment')
env={'QT_WAYLAND_DECORATION':'personal'}
launcher.command('mozc',[],prefix,env,manifest)
check(env=={'QT_WAYLAND_DECORATION':'personal'},'custom decoration is retained')
argv=launcher.command('keepassxc',[],prefix,{},manifest)
check('--talk-name='+launcher.NAME in argv,'scoped Flatpak policy permission')
check(any(item.startswith('--filesystem=') and item.endswith(':ro') for item in argv),'scoped Flatpak plugin access')
result={'checks':checks,'count':len(checks),'root':str(root),'passed':True}
(root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
