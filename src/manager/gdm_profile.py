# SPDX-License-Identifier: MIT
"""Restricted GDM values shared by the user preview and trusted helper."""
import copy
import hashlib
import json
import subprocess
from .profile import surface, rgba

DEFAULT={'format':1,'surface':{'opacity':.32,'color':'#1a1a1c'},'text':{'mode':'standard'},'background':{'mode':'keep'}}

def defaults():return copy.deepcopy(DEFAULT)

def validate(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT) or type(value['format']) is not int or value['format']!=1:raise ValueError('未対応のGDM設定です。')
    text=value['text'];background=value['background']
    if not isinstance(text,dict) or text.get('mode') not in ('standard','custom'):raise ValueError('GDM文字色を確認してください。')
    if set(text)!=({'mode','color'} if text['mode']=='custom' else {'mode'}):raise ValueError('文字色の形式が違います。')
    if not isinstance(background,dict) or background.get('mode') not in ('keep','desktop','bundled','image'):raise ValueError('GDM背景を確認してください。')
    if set(background)!=({'mode','path'} if background['mode']=='image' else {'mode'}):raise ValueError('背景の形式が違います。')
    if background['mode']=='image':
        path=background['path']
        if not isinstance(path,str) or not path.startswith('/') or '\0' in path or len(path)>4096:raise ValueError('ローカル静止画像を指定してください。')
    result={'format':1,'surface':surface(value['surface']),'text':dict(text),'background':dict(background)}
    if text['mode']=='custom':result['text']['color']=surface({'opacity':1,'color':text['color']})['color']
    return result

def generate(value,scss):
    value=validate(value);face=value['surface']
    prefix='$material-surface: '+face['color']+';\n$gdm-surface-opacity: '+str(face['opacity'])+';\n'
    prefix+='$gdm-text-color: '+(value['text']['color'] if value['text']['mode']=='custom' else 'null')+';\n@import "gdm";\n'
    r=subprocess.run(['/usr/bin/sassc','-t','expanded','-I',str(scss)],input=prefix,text=True,capture_output=True,timeout=30)
    if r.returncode:raise ValueError('GDMの生成に失敗しました: '+r.stderr)
    return r.stdout.encode()
