#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise real alternatives transactions in a private VM fixture, never GDM."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

MODULE = Path(__file__).resolve().parents[1]/'manage-gdm.py'
CSS = MODULE.parent.parent/'build/Hyalune-GDM/overlay.css'


def setup(root):
    spec=importlib.util.spec_from_file_location('gdm',MODULE);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    g.STATE=root/'state';g.ASSETS=root/'assets';g.LINK=str(root/'theme.gresource')
    base_call=g.call
    options=['--admindir',str(root/'admin'),'--altdir',str(root/'alternatives')]
    def call(*args):
        if args[0]=='update-alternatives': return base_call(args[0],*options,*args[1:])
        return base_call(*args)
    g.call=call
    g.alt=lambda *args: subprocess.run(['update-alternatives',*options,*args],check=True,stdout=subprocess.DEVNULL)
    return g


def main():
    p=argparse.ArgumentParser();p.add_argument('--child-root',type=Path);p.add_argument('--action');p.add_argument('--crash',type=int,default=0);a=p.parse_args()
    if a.child_root:
        g=setup(a.child_root);g.operate(a.action,CSS.read_bytes() if a.action!='remove' else None,crash=a.crash);return
    assert subprocess.check_output(['systemd-detect-virt','--vm'],text=True).strip()=='kvm'
    installed=subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'],text=True)
    source=Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
    checks=[]
    def ok(name,value):
        assert value,name
        checks.append(name)
    with tempfile.TemporaryDirectory(prefix='hyalune-gdm-tests-') as temp:
        root=Path(temp)
        for name in ['admin','alternatives','state']: (root/name).mkdir()
        base=root/'base.gresource';base.write_bytes(source.read_bytes());g=setup(root)
        g.alt('--install',g.LINK,g.GROUP,str(base),'10');g.alt('--auto',g.GROUP)
        original=g.alternatives();before=list(root.rglob('*'))
        plan=g.operate('apply',CSS.read_bytes(),dry=True)
        ok('plan leaves fixture unchanged',list(root.rglob('*'))==before and g.alternatives()==original)
        g.operate('apply',CSS.read_bytes());owner=g.read(g.STATE/'active.json')
        ok('apply selects dedicated resource',g.alternatives()==owner['installed_alternatives'])
        ok('upstream resource unchanged',base.read_bytes()==source.read_bytes())
        artwork=CSS.parent/'background.svg'
        bundled=subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'hyalune-background.svg'])
        ok('own background bundled without alteration',bundled==artwork.read_bytes())
        ok('background content hash recorded',owner['background_sha256']==g.digest(bundled))
        hc=subprocess.check_output(['gresource','extract',owner['resource'],g.PREFIX+'gdm-high-contrast.css'])
        standard_hc=subprocess.check_output(['gresource','extract',str(base),g.PREFIX+'gnome-shell-high-contrast.css'])
        ok('High Contrast preserves upstream bytes',hc==standard_hc)
        g.operate('update',CSS.read_bytes()+b'\n/* update fixture */\n')
        ok('update keeps original auto state',g.read(g.STATE/'active.json')['original']==original)
        active=g.read(g.STATE/'active.json');asset=Path(active['resource']);data=asset.read_bytes();asset.write_bytes(data+b'x')
        try: g.operate('remove',None);raise AssertionError('resource conflict accepted')
        except ValueError:pass
        ok('resource conflict stops before journal',not (g.STATE/'pending.json').exists())
        asset.write_bytes(data)
        # Source package changes and links must fail without editing anything.
        base_data=base.read_bytes();base.write_bytes(base_data+b'x')
        try:g.operate('remove',None);raise AssertionError('source update accepted')
        except ValueError:pass
        ok('source package conflict stops before journal',not (g.STATE/'pending.json').exists())
        base.write_bytes(base_data)
        saved=asset.with_suffix('.saved');asset.rename(saved);asset.symlink_to(saved)
        try:g.operate('remove',None);raise AssertionError('managed symlink accepted')
        except ValueError:pass
        ok('managed symlink rejected without target writes',saved.read_bytes()==data and not (g.STATE/'pending.json').exists())
        asset.unlink();saved.rename(asset)
        g.alt('--set',g.GROUP,str(base))
        try:g.operate('update',CSS.read_bytes());raise AssertionError('alternatives conflict accepted')
        except ValueError:pass
        ok('alternative conflict stops before journal',not (g.STATE/'pending.json').exists())
        g.alt('--set',g.GROUP,active['resource']);g.operate('remove',None)
        ok('remove restores original automatic selection',g.alternatives()==original and not (g.STATE/'active.json').exists())
        for action,steps in [('apply',range(1,6)),('update',range(1,6)),('remove',range(1,4))]:
            for step in steps:
                if action!='apply':g.operate('apply',CSS.read_bytes())
                before=g.alternatives();old=g.read(g.STATE/'active.json')
                child=subprocess.run([sys.executable,__file__,'--child-root',str(root),'--action',action,'--crash',str(step)],capture_output=True,text=True)
                ok(f'{action} crash {step} injected',child.returncode==90)
                recovery=g.recover(); committed=(step==5 if action!='remove' else step==3)
                ok(f'{action} crash {step} recovery',recovery['result']==('committed' if committed else 'rolled-back'))
                if not committed:ok(f'{action} crash {step} original state',g.alternatives()==before and g.read(g.STATE/'active.json')==old)
                if g.read(g.STATE/'active.json'):g.operate('remove',None)
                ok(f'{action} crash {step} final restore',g.alternatives()==original and not (g.STATE/'pending.json').exists())
        g.alt('--set',g.GROUP,str(base));manual=g.alternatives();g.operate('apply',CSS.read_bytes());g.operate('remove',None)
        ok('manual selection restored',g.alternatives()==manual)
        # Pending recovery must reject new third-party registrations.
        subprocess.run([sys.executable,__file__,'--child-root',str(root),'--action','apply','--crash','2'],check=False,stdout=subprocess.DEVNULL)
        other=root/'other.gresource';other.write_bytes(base.read_bytes());g.alt('--install',g.LINK,g.GROUP,str(other),'20')
        try:g.recover();raise AssertionError('external recovery conflict accepted')
        except ValueError:pass
        ok('pending recovery retains journal on conflict',(g.STATE/'pending.json').exists())
        g.alt('--remove',g.GROUP,str(other));g.recover()
        ok('recovery succeeds after conflict resolved',g.alternatives()==manual)
    # Privilege remains mandatory on every hardware platform.
    old_uid=g.os.geteuid
    try:
        g.os.geteuid=lambda:1000
        try:g.guard(restoring=True);raise AssertionError('normal user accepted')
        except ValueError as e:ok('restoration still requires root', 'root' in str(e))
    finally:g.os.geteuid=old_uid
    ok('real GDM alternatives untouched',subprocess.check_output(['update-alternatives','--query','gdm-theme.gresource'],text=True)==installed)
    print(json.dumps({'passed':len(checks),'checks':checks},indent=2))


if __name__=='__main__':main()
