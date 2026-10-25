# SPDX-License-Identifier: MIT
"""Versioned values only. No CSS, expressions, imports or executable settings."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

TARGETS = {'panel': 'パネル', 'shell': 'メニュー・ダイアログ', 'gtk3': 'GTK3ウィンドウ', 'gtk4': 'GTK4ウィンドウ'}
DEFAULT = {'format': 2, 'common': {'opacity': .56, 'color': '#1a1a1c'},
           'overrides': {'panel': {'opacity': .38, 'color': '#141416'}},
           'gdm': {'opacity': .32, 'color': '#1a1a1c'},
           'blur': {'quick_settings': False, 'windows': False}, 'flatpak': {}}


def defaults():
    return copy.deepcopy(DEFAULT)


def surface(value):
    if not isinstance(value, dict) or set(value) != {'opacity', 'color'}:
        raise ValueError('不透明度と素材色だけを指定してください。')
    alpha, color = value['opacity'], value['color']
    if type(alpha) not in (float, int) or not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError('不透明度は0〜100％です。')
    if not isinstance(color, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', color) is None:
        raise ValueError('色は #RRGGBB 形式で指定してください。')
    return {'opacity': float(alpha), 'color': color.lower()}


def validate(value):
    if not isinstance(value, dict) or type(value.get('format')) is not int or value['format'] not in (1, 2):
        raise ValueError('未対応のプロファイル形式です。')
    keys = set(DEFAULT) - ({'flatpak'} if value['format'] == 1 else set())
    if set(value) != keys: raise ValueError('未対応のプロファイル項目です。')
    overrides, blur = value['overrides'], value['blur']
    if not isinstance(overrides, dict) or set(overrides) - set(TARGETS):
        raise ValueError('未対応の個別調整対象です。')
    if not isinstance(blur, dict) or set(blur) != set(DEFAULT['blur']) or any(type(v) is not bool for v in blur.values()):
        raise ValueError('ぼかし設定は有効／無効で指定してください。')
    result = {'format': value['format'], 'common': surface(value['common']),
            'overrides': {k: surface(v) for k, v in overrides.items()},
            'gdm': surface(value['gdm']), 'blur': dict(blur)}
    if value['format'] == 2:
        apps = value['flatpak']
        if not isinstance(apps, dict) or len(apps) > 256: raise ValueError('Flatpak設定を確認してください。')
        result['flatpak'] = {}
        for app, policy in apps.items():
            if not isinstance(app, str) or len(app)>255 or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*){2,}',app) is None:
                raise ValueError('未対応のアプリIDです。')
            if not isinstance(policy,dict) or policy.get('mode') not in ('follow','custom','hold'):
                raise ValueError('追従・個別・保持から選択してください。')
            expected = {'mode','surface'} if policy['mode']=='custom' else {'mode'}
            if set(policy)!=expected: raise ValueError('アプリ個別設定の形式を確認してください。')
            result['flatpak'][app] = {'mode':policy['mode']}
            if policy['mode']=='custom': result['flatpak'][app]['surface']=surface(policy['surface'])
    return result


def upgrade(value):
    result = validate(value)
    if result['format']==1: result.update(format=2,flatpak={})
    return result


def for_app(value, policy):
    result=upgrade(value)
    if policy['mode']=='custom':
        face=surface(policy['surface']);result['common']=face
        result['overrides']={'panel':dict(face,opacity=face['opacity']*(.38/.56))}
    return result


def app_material_digest(value, policy):
    value=for_app(value,policy)
    panel=effective(value,'panel');window=effective(value,'gtk4')
    material={'gtk3':effective(value,'gtk3'),'gtk4':window,
              'base':dict(panel,opacity=min(panel['opacity'],window['opacity']))}
    return hashlib.sha256(json.dumps(material,sort_keys=True).encode()).hexdigest()


def canonical(value):
    return (json.dumps(validate(value), sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def effective(value, target):
    return value['overrides'].get(target, value['common'])


def rgba(value):
    c = value['color']
    return 'rgba(%d, %d, %d, %.8f)' % (*[int(c[i:i+2], 16) for i in (1, 3, 5)], value['opacity'])


def generate(value, scss, output):
    """Compile fixed entrypoints, with typed variable assignments before imports."""
    value = validate(value); output = Path(output)
    panel, shell, gtk3, gtk4 = (effective(value, k) for k in TARGETS)
    # The base may never exceed the desired content alpha: avoid negative overlays.
    base = dict(panel, opacity=min(panel['opacity'], gtk4['opacity']))
    # At alpha 1 there is no remaining background to fill, so an opaque base
    # already provides the requested material. The SCSS formula handles this.
    entries = [('material-shell', {'panel': panel, 'surface': shell}),
               ('material-gtk3', {'window': gtk3}),
               ('material-gtk4-global', {'window': gtk4, 'gtk4-window': base}),
               ('material-flatpak-gtk4', {'window': gtk4, 'gtk4-window': base})]
    names = ['gnome-shell/gnome-shell.css', 'gtk-3.0/gtk.css', 'gtk-4.0/material.css', 'gtk-4.0/flatpak.css']
    for (entry, variables), name in zip(entries, names):
        prefix = ''.join('$material-%s: %s;\n' % (k, rgba(v)) for k, v in variables.items())
        source = prefix + '@import "%s";\n' % entry
        result = subprocess.run(['sassc', '-t', 'expanded', '-I', str(scss)], input=source,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError('SCSS生成に失敗しました: ' + result.stderr.strip())
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.stdout)
    (output / 'gtk-3.0/gtk-dark.css').write_text('@import url("gtk.css");\n')
    return output
