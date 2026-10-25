# SPDX-License-Identifier: MIT
"""Trusted root-owned GDM endpoint. No caller code, CSS or destination paths."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import uuid
from . import gdm_profile

ROOT=Path(__file__).resolve().parents[2]

def engine():
    spec=importlib.util.spec_from_file_location('hyalune_gdm_engine',ROOT/'tools/manage-gdm.py')
    g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g);return g

def caller(g):
    uid=os.environ.get('PKEXEC_UID',os.environ.get('SUDO_UID',''))
    if not uid.isdecimal() or int(uid)==0:raise ValueError('認証した通常利用者が必要です。')
    if os.environ.get('PKEXEC_UID') and os.environ.get('SUDO_UID') and os.environ['PKEXEC_UID']!=os.environ['SUDO_UID']:raise ValueError('呼出元UIDが一致しません。')
    user=pwd.getpwuid(int(uid));g.initiating_user(user.pw_name)
    return user

def capture_image(g,user,path):
    # Both the source read and image decoder run as the invoking user, with
    # resource limits in the fixed root-owned script. Root receives only PNG.
    result=subprocess.run(['/usr/sbin/runuser','--user',user.pw_name,'--','/usr/bin/python3','-I',str(ROOT/'tools/gdm-wallpaper.py'),'--file',path],env=g.capture_environment(user),capture_output=True,text=True,timeout=25)
    payload=json.loads(result.stdout)
    if result.returncode or 'error' in payload:raise ValueError(payload.get('error','画像を読み込めません。'))
    data=base64.b64decode(payload['png'],validate=True);d=payload['description']
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>g.MAX_BACKGROUND or d.get('sha256')!=g.digest(data) or d.get('captured_uid')!=user.pw_uid or d.get('origin')!='image' or d.get('resource_name')!='hyalune-background.png':raise ValueError('正規化画像を照合できません。')
    return {'data':data,'description':d}

def status(g):
    owner=g.read(g.STATE/'active.json');current=g.alternatives();pending=bool(g.read(g.STATE/'pending.json'))
    conflict=None
    if owner:
        try:g.check_owner(owner,current)
        except (ValueError,OSError) as error:conflict=str(error)
    value=(owner or {}).get('manager',{}).get('profile')
    identification='managed-profile' if value else 'unidentified-fixed-values'
    if value:value=gdm_profile.validate(value)
    elif owner and owner.get('overlay_sha256')==g.digest(gdm_profile.generate(gdm_profile.defaults(),ROOT/'src/scss')):
        value=gdm_profile.defaults();identification='fixed-release'
    return {'managed':bool(owner),'pending':pending,'conflict':conflict,'profile':value,'identification':identification,
            'version':(owner or {}).get('version'),'background':(owner or {}).get('background'),
            'reflection':'next-gdm-session','service_restart':False}

def handle(request,g,user):
    if not isinstance(request,dict):raise ValueError('JSON object required')
    action=request.get('action')
    if action not in ('status','plan','set','remove','recover'):raise ValueError('未対応のGDM操作です。')
    allowed={'action'}
    if action in ('plan','set'):allowed|={'profile','operation'}
    if action in ('set','remove'):allowed|={'plan_token'}
    if set(request)-allowed:raise ValueError('未対応のGDM引数です。')
    if action=='status':return status(g)
    if action=='recover':return g.recover()
    operation=request.get('operation','set')
    if operation not in ('set','remove'):raise ValueError('Invalid GDM operation')
    if action=='remove':operation='remove'
    owner=g.read(g.STATE/'active.json');config=None;snapshot=None;replace=False
    if operation=='remove':
        planned=g.operate('remove',None,dry=True)
        overlay=None;kind='remove'
    else:
        config=gdm_profile.validate(request['profile']);mode=config['background']['mode']
        if mode=='desktop':snapshot=g.capture_desktop_background(user.pw_name)
        elif mode=='bundled':snapshot=g.bundled_background()
        elif mode=='image':snapshot=capture_image(g,user,config['background']['path'])
        elif not owner:raise ValueError('初回は背景画像または現在の壁紙・同梱背景を選択してください。')
        replace=snapshot is not None and owner is not None
        overlay=gdm_profile.generate(config,ROOT/'src/scss');kind='update' if owner else 'apply'
        # Persist only normalized settings; no private source filename is saved.
        stored=dict(config,background={'mode':'keep'})
        manager={'format':1,'profile':stored}
        planned=g.operate(kind,overlay,dry=True,background=snapshot,replace_image=replace,manager=manager)
    token=g.digest(json.dumps({'plan':planned,'owner':owner,'config':config},sort_keys=True).encode())
    if action=='plan':return {'plan_token':token,'operation':kind,'background':planned.get('background'),'reflection':'next-gdm-session','service_restart':False}
    if request.get('plan_token')!=token:raise ValueError('GDMの状態・画像が確認後に変わりました。もう一度変更内容を確認してください。')
    return g.operate(kind,overlay,background=snapshot,replace_image=replace,manager=manager if config else None)

def main():
    response={'api':'hyalune.gdm','version':1,'operation_id':uuid.uuid4().hex}
    try:
        if os.geteuid()!=0:raise ValueError('管理者認証が必要です。')
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise ValueError('GDM設定が大きすぎます。')
        request=json.loads(raw);g=engine();user=caller(g)
        g.guard(restoring=request.get('action') in ('status','remove','recover') or request.get('operation')=='remove')
        with g.locked():result=handle(request,g,user)
        response.update(ok=True,result=result);code=0
    except Exception as error:
        response.update(ok=False,error={'code':'resource-busy' if isinstance(error,BlockingIOError) else 'gdm-rejected','message':str(error)});code=1
    print(json.dumps(response,ensure_ascii=False,sort_keys=True,indent=2));return code
