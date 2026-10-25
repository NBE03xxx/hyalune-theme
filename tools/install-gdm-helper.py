#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install the fixed root-owned GDM endpoint. Does not apply or restart GDM."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import uuid

ROOT=Path(__file__).resolve().parent.parent
BASE=Path('/usr/local/share/hyalune/gdm-settings')
STATE=Path('/var/lib/hyalune-gdm-helper')
ENTRY=Path('/usr/local/libexec/hyalune-gdm-settings')
POLICY=Path('/usr/share/polkit-1/actions/io.github.NBE03xxx.Hyalune.Gdm.policy')

def engine():
    spec=importlib.util.spec_from_file_location('helper_install_gdm',ROOT/'tools/manage-gdm.py')
    g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g);return g

def image(g,path):
    g.safe(path)
    if not path.exists():return None
    s=path.stat()
    if s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Untrusted existing root file: '+str(path))
    return {'data':base64.b64encode(path.read_bytes()).decode(),'mode':stat.S_IMODE(s.st_mode)}

def write(g,path,value):
    if value is None:path.unlink(missing_ok=True)
    else:g.write(path,base64.b64decode(value['data'],validate=True),value['mode'])

def collect():
    names=['src/manager/__init__.py','src/manager/profile.py','src/manager/gdm_profile.py','src/manager/gdm_privileged.py','tools/manage-gdm.py','tools/gdm-wallpaper.py','build/Hyalune-GDM/background.svg']
    names += [str(p.relative_to(ROOT)) for p in (ROOT/'src/scss').rglob('*.scss')]
    return {n:(ROOT/n).read_bytes() for n in sorted(names)}

def recover(g):
    j=g.read(STATE/'pending.json')
    if not j:return {'recovered':False}
    paths={str(ENTRY),str(POLICY),str(STATE/'active.json')}
    if any(op['path'] not in paths for op in j['operations']):raise ValueError('Unexpected helper recovery path')
    for op in j['operations']:
        if image(g,Path(op['path'])) not in (op['before'],op['after']):raise ValueError('Helper recovery conflict; keep backups')
    if not j.get('committed'):
        for op in reversed(j['operations']):write(g,Path(op['path']),op['before'])
    (STATE/'pending.json').unlink();g.syncdir(STATE)
    return {'recovered':True,'committed':bool(j.get('committed'))}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['install','status','remove','recover']);a=p.parse_args()
    g=engine();g.guard(restoring=a.action in ('status','remove','recover'))
    g.safe(STATE);STATE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(STATE,0o700)
    g.safe(STATE/'lock')
    with (STATE/'lock').open('a') as lock:
        os.chmod(STATE/'lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.action=='recover':print(json.dumps(recover(g)));return
        old=g.read(STATE/'active.json')
        if a.action=='status':print(json.dumps({'installed':bool(old),'pending':bool(g.read(STATE/'pending.json')),'revision':(old or {}).get('revision'),'gdm_modified':False}));return
        if g.read(STATE/'pending.json'):raise ValueError('Run manager-gdm recover first')
        if not ENTRY.parent.exists():ENTRY.parent.mkdir(parents=True,mode=0o755)
        for path in (ENTRY,POLICY):
            current=image(g,path)
            if old and current!=old['installed'][str(path)]:raise ValueError('Helper entry edited: '+str(path))
            if not old and current is not None:raise ValueError('Unmanaged helper entry: '+str(path))
        if a.action=='remove' and not old:raise ValueError('Helper is not installed')
        files=collect() if a.action=='install' else {}
        hashes={n:g.digest(data) for n,data in files.items()};revision=g.digest(json.dumps(hashes,sort_keys=True).encode())
        if files:
            release=BASE/'releases'/revision
            for n,data in files.items():
                target=release/n;g.safe(target)
                if target.exists():
                    if image(g,target)['data']!=base64.b64encode(data).decode():raise ValueError('Retained helper release changed')
                else:g.write(target,data,0o644)
            # Root code is readable, never writable by other users; no symlinks.
            for folder in (release,*release.parents):
                if folder.is_relative_to(BASE):os.chmod(folder,0o755)
        desired={str(ENTRY):{'data':base64.b64encode((ROOT/'data/hyalune-gdm-settings').read_bytes()).decode(),'mode':0o755},
                 str(POLICY):{'data':base64.b64encode((ROOT/'data/io.github.NBE03xxx.Hyalune.Gdm.policy').read_bytes()).decode(),'mode':0o644}} if files else {str(ENTRY):None,str(POLICY):None}
        record={'format':1,'revision':revision,'files':hashes,'installed':dict(desired)} if files else None
        desired[str(STATE/'active.json')]=None if record is None else {'data':base64.b64encode((json.dumps(record,sort_keys=True,indent=2)+'\n').encode()).decode(),'mode':0o600}
        operations=[{'path':n,'before':image(g,Path(n)),'after':v} for n,v in desired.items()]
        ident=uuid.uuid4().hex;tx=STATE/'transactions'/ident;tx.mkdir(parents=True,mode=0o700)
        j={'format':1,'id':ident,'committed':False,'operations':operations};g.save(tx/'journal.json',j);g.save(STATE/'pending.json',j)
        try:
            for op in operations:write(g,Path(op['path']),op['after'])
            j['committed']=True;g.save(STATE/'pending.json',j);g.save(tx/'result.json',{'committed':True})
            (STATE/'pending.json').unlink();g.syncdir(STATE)
        except Exception:recover(g);raise
        print(json.dumps({'status':'committed','action':a.action,'revision':revision if files else None,'backup':str(tx),'gdm_modified':False},indent=2))

if __name__=='__main__':
    try:main()
    except Exception as error:print('Hyalune GDM helper: '+str(error),file=sys.stderr);raise SystemExit(1)
