#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""No desktop writes: language precedence, catalog coverage and profile stability."""
import ast
import json
import os
from pathlib import Path
import string
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from manager.i18n import select_language, JAPANESE

cases = [
    ({}, 'en'), ({'LANG': 'ja_JP.UTF-8'}, 'ja'), ({'LANG': 'ja'}, 'ja'),
    ({'LANG': 'ja-JP'}, 'ja'), ({'LANG': 'en_US.UTF-8'}, 'en'),
    ({'LANG': 'en_GB.UTF-8'}, 'en'), ({'LANG': 'fr_FR.UTF-8'}, 'en'),
    ({'LANG': 'de_DE.UTF-8'}, 'en'), ({'LANG': 'zh_CN.UTF-8'}, 'en'),
    ({'LANG': 'garbage'}, 'en'), ({'LANG': 'jargon'}, 'en'),
    ({'LANG': 'en_US.UTF-8', 'LANGUAGE': 'ja:en'}, 'ja'),
    ({'LANG': 'ja_JP.UTF-8', 'LANGUAGE': 'en:ja'}, 'en'),
    ({'LANG': 'ja_JP.UTF-8', 'LANGUAGE': 'fr:ja:en'}, 'en'),
    ({'LANG': 'ja_JP.UTF-8', 'LANGUAGE': ':de::ja'}, 'en'),
    ({'LANG': 'ja_JP.UTF-8', 'LANGUAGE': '::'}, 'ja'),
    ({'LANG': 'en_US.UTF-8', 'LC_MESSAGES': 'ja_JP.UTF-8'}, 'ja'),
    ({'LANG': 'ja_JP.UTF-8', 'LC_MESSAGES': 'en_US.UTF-8'}, 'en'),
    ({'LANG': 'ja_JP.UTF-8', 'LC_MESSAGES': 'ja', 'LC_ALL': 'de_DE.UTF-8'}, 'en'),
    ({'LANG': 'en_US.UTF-8', 'LC_MESSAGES': 'en', 'LC_ALL': 'ja_JP.UTF-8'}, 'ja'),
    ({'LANG': 'ja_JP.UTF-8', 'LC_ALL': 'C', 'LANGUAGE': 'ja'}, 'en'),
    ({'LANG': 'ja_JP.UTF-8', 'LC_ALL': 'POSIX', 'LANGUAGE': 'ja'}, 'en'),
    ({'LC_ALL': 'C.UTF-8', 'LANGUAGE': 'ja'}, 'ja'),
    ({'LANGUAGE': 'ja'}, 'ja'),
]
for env, expected in cases:
    assert select_language(env) == expected, (env, expected)
# Each invocation is a fresh process: selection is fixed for an app's lifetime.
probe = '''import json,os
from manager.i18n import _,message,LANGUAGE
from manager import profile
before=dict(os.environ)
result={'language':LANGUAGE,'title':_('Hyalune Settings'),
'error':message('色は #RRGGBB 形式で指定してください。'),
'nested':message('GDMの生成に失敗しました: /tmp/example_日本語.png'),
'discovery':message('App is running; it will not be stopped'),
'unknown':message('External detail: /tmp/example_日本語.png'),
'profile':profile.digest(profile.defaults()),'canonical':profile.canonical(profile.defaults()).decode()}
assert dict(os.environ)==before
os.environ['LANGUAGE']='en' if LANGUAGE=='ja' else 'ja'
assert _('Hyalune Settings')==result['title']
print(json.dumps(result))'''
results = {}
for key, preference in [('ja','ja'), ('en','en'), ('fr','fr:ja')]:
    env = dict(os.environ, PYTHONPATH=str(ROOT/'src'), PYTHONDONTWRITEBYTECODE='1',
               LC_ALL='C.UTF-8', LANGUAGE=preference)
    results[key] = json.loads(subprocess.check_output([sys.executable, '-B', '-c', probe], env=env, text=True))
assert results['ja']['title'] == 'Hyalune 設定'
assert results['en'] == results['fr']
assert results['en']['title'] == 'Hyalune Settings'
assert results['en']['error'] == 'Specify colors in #RRGGBB format.'
assert results['ja']['error'] == '色は #RRGGBB 形式で指定してください。'
assert results['en']['nested'] == 'GDM generation failed: /tmp/example_日本語.png'
assert results['ja']['nested'] == 'GDMの生成に失敗しました: /tmp/example_日本語.png'
assert results['en']['discovery'] == 'App is running; it will not be stopped'
assert results['ja']['discovery'] == 'アプリが起動中です。自動終了しません'
assert all(r['unknown'] == 'External detail: /tmp/example_日本語.png' for r in results.values())
assert len({r['canonical'] for r in results.values()}) == len({r['profile'] for r in results.values()}) == 1
# Every UI msgid has a Japanese translation and matching named placeholders.
formatter = string.Formatter()
fields = lambda text: sorted(field for _, field, _, _ in formatter.parse(text) if field is not None)
count = 0
for name in ('app.py', 'gdm_ui.py'):
    tree = ast.parse((ROOT/'src/manager'/name).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any('\u3040' <= c <= '\u9fff' for c in node.value), (name, node.lineno, node.value)
        if isinstance(node, ast.Name) and node.id == '_':
            assert isinstance(node.ctx, ast.Load), (name, node.lineno)
        if isinstance(node, ast.arg):
            assert node.arg != '_', (name, node.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_':
            if not node.args or not isinstance(node.args[0], ast.Constant): continue
            text = node.args[0].value
            translated = JAPANESE.gettext(text)
            assert text != translated, (name, node.lineno, text)
            assert fields(text) == fields(translated), text
            count += 1
# Known helper messages must have an explicit display translation. No backend
# code, validation, saved messages or plan tokens are localized in place.
for name in ('profile.py','backend.py','gdm_profile.py','flatpak.py','gdm_privileged.py'):
    tree = ast.parse((ROOT/'src/manager'/name).read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):continue
        text = node.value
        if not any('\u3040' <= c <= '\u9fff' for c in text) or text.endswith(': '):continue
        assert JAPANESE.pgettext('legacy',text) != text, (name,node.lineno,text)
print(json.dumps({'status':'passed','locale_cases':len(cases),'UI_translation_calls':count,
                  'fresh_processes':len(results),'profiles_identical':True},indent=2))
