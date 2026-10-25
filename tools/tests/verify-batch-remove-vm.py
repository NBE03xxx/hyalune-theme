#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify atomic desktop+Flatpak removal in VM-private homes, including recovery."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import uuid

assert socket.gethostname() == 'KVM-PC' and os.environ.get('SSH_CONNECTION')
p = argparse.ArgumentParser(); p.add_argument('--project', type=Path, required=True)
a = p.parse_args(); project = a.project.resolve()
root = Path.home() / '.local/state/glass50/phase5-tests' / ('batch-remove-' + uuid.uuid4().hex)
root.mkdir(parents=True, mode=0o700)
state = '.local/state/glass50/installer-material-v1'
apps = ['org.example.First', 'org.example.Second']
checks = []

def check(name, value):
    checks.append({'name': name, 'passed': bool(value)}); assert value, name

bin_dir = root / 'bin'; bin_dir.mkdir()
flatpak = bin_dir / 'flatpak'
flatpak.write_text('''#!/usr/bin/python3
import os,sys
args=sys.argv[1:]
if args[:1]==['ps']: print(os.environ.get('GLASS50_TEST_RUNNING',''))
elif args[:1]==['info']:
 flag=args[1];app=args[2]
 print({'--show-ref':'app/'+app+'/x86_64/stable','--show-origin':'fixture','--show-runtime':'org.gnome.Platform/x86_64/50','--show-commit':'fixture-commit'}[flag])
else: sys.exit(77)
'''); flatpak.chmod(0o700)
env = dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH'])
no_flatpak = root / 'without-flatpak'; no_flatpak.mkdir()
for name in ['python3', 'dirname', 'git', 'findmnt', 'gnome-shell', 'glib-compile-schemas']:
    (no_flatpak / name).symlink_to(shutil.which(name))

def call(home, args, expected=0, extra_env=None):
    r = subprocess.run([str(project / 'install.sh'), *args, '--test-root', str(home)],
                       env=dict(env, **(extra_env or {})), capture_output=True, text=True, timeout=40)
    assert r.returncode == expected, (args, r.returncode, r.stdout[-1000:], r.stderr)
    return json.loads(r.stdout) if expected == 0 else r

def tree(home):
    result = {}
    for p in home.rglob('*'):
        name = str(p.relative_to(home))
        if name.startswith('.local/state/glass50/') or name == '.config/glib-2.0/settings/keyfile': continue
        if p.is_symlink(): result[name] = ('link', os.readlink(p))
        elif p.is_file(): result[name] = (hashlib.sha256(p.read_bytes()).hexdigest(), stat.S_IMODE(p.stat().st_mode))
    return result

def preferences(home):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(home / '.config/glib-2.0/settings/keyfile')
    return {g: dict(parser[g]) for g in parser.sections() if parser[g]}


def owner(home, app): return home / '.local/state/glass50/installer-flatpak-v1' / app / 'active.json'

def fresh(label):
    home = root / label; home.mkdir()
    for app in apps + ['org.example.Unmanaged']:
        f = home / '.var/app' / app / 'config/gtk-4.0/gtk.css'; f.parent.mkdir(parents=True)
        f.write_text('/* original ' + app + ' */\n'); f.chmod(0o640)
    original = tree(home)
    call(home, ['apply', '--blur', 'on', '--flatpak', 'none'])
    for app in apps: call(home, ['flatpak', 'apply', '--app', app])
    return home, original

h, original = fresh('cycle'); installed = tree(h)
q = call(h, ['plan', '--operation', 'remove'])
check('scan lists all managed apps, including IDs absent from installed inventory',
      [r['app'] for r in q['flatpak_remove']['apps']] == apps)
check('plan leaves native and app ownership and files unchanged',
      tree(h) == installed and all(owner(h, a).exists() for a in apps))
r = call(h, ['remove', '--settings', 'keep'])
check('one command restores all app and desktop files and modes', tree(h) == original)
check('all ownership removed and unmanaged app retained',
      not (h / state / 'active.json').exists() and all(not owner(h, a).exists() for a in apps) and
      (h / '.var/app/org.example.Unmanaged/config/gtk-4.0/gtk.css').read_text() == '/* original org.example.Unmanaged */\n')
journal = json.loads((Path(r['transaction']) / 'journal.json').read_text())
check('one removal journal contains every app and native setting, native owner last',
      all(any(o['name'] == str(owner(h, a).relative_to(h)) for o in journal['operations']) for a in apps) and
      any(o['kind'] == 'setting' for o in journal['operations']) and journal['operations'][-1]['name'] == state + '/active.json')
check('result reports every app removed', r['flatpak_remove']['summary']['removed'] == 2)
check('batch keep retains only the managed effect preferences', preferences(h).get('org/gnome/shell/extensions/glass50-blur') == {'effect-enabled': 'true', 'window-material-enabled': 'true'})

h, _ = fresh('running'); before = tree(h)
r = call(h, ['remove'], expected=1, extra_env={'GLASS50_TEST_RUNNING': apps[1]})
check('running app stops entire batch before writes and names the app',
      apps[1] in r.stderr and 'App is running' in r.stderr and tree(h) == before and (h / state / 'active.json').exists())
call(h, ['remove'])
check('same command succeeds after running app closes', all(not owner(h, a).exists() for a in apps))

h, _ = fresh('conflict'); f = h / '.local/share/flatpak/overrides' / apps[1]; f.write_text('/* later permissions edit */')
before = tree(h); call(h, ['remove'], expected=1)
check('later-app conflict prevents earlier app and desktop writes', tree(h) == before and all(owner(h, a).exists() for a in apps))

h, _ = fresh('pending'); owner(h, apps[1]).with_name('pending.json').write_text('{}')
before = tree(h); call(h, ['remove'], expected=1)
check('per-app pending state prevents the entire batch', tree(h) == before and (h / state / 'active.json').exists())

h, _ = fresh('linked'); record = owner(h, apps[1]); raw = record.read_bytes(); record.unlink(); external = root / 'external.json'; external.write_bytes(raw); record.symlink_to(external)
before = tree(h); call(h, ['remove'], expected=1)
check('linked ownership rejected and referent unchanged', tree(h) == before and external.read_bytes() == raw)

# Check rollback after first app ownership, native settings, and final owner.
h, _ = fresh('cuts'); q = call(h, ['plan', '--operation', 'remove'])
cuts = [next(i + 1 for i, op in enumerate(q['targets']) if op['name'] == str(owner(h, apps[0]).relative_to(h))),
        next(i + 1 for i, op in enumerate(q['targets']) if op['kind'] == 'setting'), len(q['targets'])]
for cut in cuts:
    for kind in ['failure', 'crash']:
        h, _ = fresh(kind + str(cut)); before = tree(h); owners = {a: owner(h, a).read_bytes() for a in apps}; native = (h / state / 'active.json').read_bytes(); before_preferences = preferences(h)
        call(h, ['remove', '--' + ('fail-after' if kind == 'failure' else 'crash-after'), str(cut)], expected=1 if kind == 'failure' else 86)
        if kind == 'crash':
            call(h, ['recover'], extra_env={'PATH': str(no_flatpak)})
        check(kind + ' restores every file and owner at ' + str(cut),
              tree(h) == before and all(owner(h, a).read_bytes() == owners[a] for a in apps) and
              (h / state / 'active.json').read_bytes() == native and preferences(h) == before_preferences and not (h / state / 'pending.json').exists())

h, original = fresh('committed'); call(h, ['remove', '--crash-after-commit'], expected=86)
r = call(h, ['recover'], extra_env={'PATH': str(no_flatpak)})
check('committed removal finalized without Flatpak command', r['status'] == 'commit-finalized' and tree(h) == original and not preferences(h) and not (h / state / 'active.json').exists())

# Run the actual T16 planner inside this private VM fixture. Only the test
# harness substitutes the verified VM guard; production has no bypass option.
loader = """import importlib.util,sys
from pathlib import Path
p=Path(sys.argv.pop(1));s=importlib.util.spec_from_file_location('source',p/'tools/install-from-source.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);original=m.module
vm=original(p/'tools/manage-theme.py','verified_vm').guard
def load(path,name):
 value=original(path,name)
 if Path(path).name=='manage-t16.py':value.guard=vm
 return value
m.module=load
sys.exit(m.main())
"""
def trial(home, args):
    r = subprocess.run(['python3', '-c', loader, str(project), *args,
                        '--target', 't16-trial', '--test-root', str(home)], env=env,
                       capture_output=True, text=True, timeout=40)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return json.loads(r.stdout)
h = root / 't16'; h.mkdir(); folder = h / '.config/gtk-4.0'; folder.mkdir(parents=True)
(folder / 'old.css').write_text('/* retained original target */')
for name in ['gtk.css', 'gtk-dark.css']:(folder / name).symlink_to('old.css')
original = tree(h)
trial(h, ['apply', '--blur', 'off', '--flatpak', 'none'])
for app in apps:call(h, ['flatpak', 'apply', '--app', app])
trial_owner=json.loads((h/state/'active.json').read_text())
call(h, ['update', '--blur', 'on'])
public_owner=json.loads((h/state/'active.json').read_text())
check('generic entry migrates trial+Flatpak without losing trial originals',
      public_owner['target']=='desktop' and public_owner['t16_trial']==trial_owner['t16_trial'])
installed=tree(h);native=(h/state/'active.json').read_bytes();owners={a:owner(h,a).read_bytes() for a in apps}
q=call(h,['plan','--operation','remove']);cut=next(i+1 for i,op in enumerate(q['targets']) if op['name']==str(owner(h,apps[0]).relative_to(h)))
call(h,['remove','--crash-after',str(cut)],expected=86);call(h,['recover'])
check('migrated trial composite recovery restores all app/native ownership',
      tree(h)==installed and (h/state/'active.json').read_bytes()==native and all(owner(h,a).read_bytes()==owners[a] for a in apps))
r = call(h, ['remove', '--settings', 'discard'])
check('T16 composite restores both original links and referent', tree(h) == original)
check('T16 composite removes all app owners in the same transaction',
      r['flatpak_remove']['summary']['removed'] == 2 and all(not owner(h,a).exists() for a in apps))

h = root / 'no-apps'; h.mkdir(); call(h, ['apply', '--flatpak', 'none']); r = call(h, ['remove'], extra_env={'PATH': str(no_flatpak)})
check('desktop-only removal needs no Flatpak command', r['flatpak_remove']['summary']['removed'] == 0)
print(json.dumps({'status': 'passed', 'root': str(root), 'checks': checks}, indent=2))
