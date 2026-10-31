#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the installed UI in a VM-private session; never apply live settings."""
import copy
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
root = Path(os.environ['HYALUNE_MANAGER_PROBE'])
home = Path(os.environ['HYALUNE_MANAGER_HOME'])
case = os.environ['HYALUNE_I18N_CASE']
expected = 'ja' if case == 'ja' else 'en'
sys.path.insert(0, str(home/'.local/share/hyalune/settings/app/src'))
from manager import app, i18n, profile
from gi.repository import GLib, Gtk
assert os.environ['GSETTINGS_BACKEND'] == 'keyfile'
checks = []
stage = 0
deadline = time.monotonic() + 40
application = app.Application(home)


def check(name, value):
    checks.append({'name': name, 'passed': bool(value)})
    assert value, name


def shot(name):
    (root/(name+'.done')).unlink(missing_ok=True)
    (root/(name+'.request')).write_text('capture')


def captured(name):
    if not (root/(name+'.done')).exists(): return False
    (root/(name+'.png')).replace(root/(case+'-'+name+'.png'))
    (root/(name+'.done')).unlink()
    return True


class PlanAdapter:
    def __init__(self): self.requests = []
    def call(self, action, request, done, operation=None):
        self.requests.append(action)
        assert action == 'plan', 'UI test must never apply changes'
        result = {'manager': {'token': 'private-plan-token', 'apps': [
            {'status': 'planned', 'note': 'High Contrastを維持するためGTK3は標準外観。素材の個別値は保存します。'},
            {'status': 'deferred'}]}}
        GLib.idle_add(lambda: (done({'ok': True, 'result': result}), False)[1])


class GdmAdapter:
    def __init__(self): self.requests = []
    def call(self, request, done):
        self.requests.append(request['action'])
        assert request['action'] in ('status', 'plan'), 'UI test must never apply GDM'
        result = ({'ok':False, 'error':{'message':'管理者認証を取り消しました。'}}
                  if request['action']=='status' else {'ok':True,'result':{'plan_token':'private-gdm-token'}})
        GLib.idle_add(lambda: (done(result), False)[1])


def tick():
    global stage, baseline
    try:
        if time.monotonic() > deadline: raise TimeoutError('UI locale probe stage '+str(stage))
        w = application.window
        if not w or not w.initialized or w.busy: return True
        if stage == 0:
            check('selected language', i18n.LANGUAGE == expected)
            check('installed title', w.get_title() == ('Hyalune 設定' if expected=='ja' else 'Hyalune Settings'))
            check('all page names', [text for key,text in app.PAGES] == (
                ['概要','外観','ぼかし','ログイン画面','Flatpakアプリ','履歴と復元'] if expected=='ja' else
                ['Overview','Appearance','Blur','Login Screen','Flatpak Apps','History and Restore']))
            check('target chooser', w.target.get_model().get_string(1) == ('パネル' if expected=='ja' else 'Panel'))
            check('Flatpak policies', w.app_mode.get_model().get_string(0) == ('共通設定に追従' if expected=='ja' else 'Follow Common Settings'))
            check('GDM background chooser', w.gdm_view.background.get_model().get_string(0) == ('保存済みの背景を保持' if expected=='ja' else 'Keep Saved Background'))
            check('overview localizes backend note', ('配置状態です。' if expected=='ja' else 'This is the installed state.') in w.overview_text.get_text())
            check('GDM is not queried on startup', w.gdm_view.current is None)
            baseline = copy.deepcopy(w.value)
            shot('initial'); stage=1
        elif stage == 1:
            if not captured('initial'): return True
            check('keyboard focus', w.details_toggle.grab_focus())
            (root/'space.request').write_text('space'); stage=2
        elif stage == 2:
            if not w.details.get_visible(): return True
            check('keyboard disclosure retains profile', w.value == baseline)
            w.target.set_selected(1); w.target_scale.set_value(47)
            check('target edit and summary', w.value['overrides']['panel']['opacity']==.47 and
                  ('パネル' if expected=='ja' else 'Panel') in w.summary.get_text())
            w.cancel_edit(); check('cancel retains baseline', w.value==baseline)
            w.error({'error':{'message':'色は #RRGGBB 形式で指定してください。'}})
            check('validation error language', w.notice.get_title()==('色は #RRGGBB 形式で指定してください。' if expected=='ja' else 'Specify colors in #RRGGBB format.'))
            w.update_apps({'available':True,'apps':[{'app':'org.example.Editor','toolkit':'gtk4', 'status':'deferred',
                'policy':{'mode':'hold'}, 'reason':'起動中です。終了後に再検出してください。',
                'rendering_note':'High Contrastを維持するためGTK3は標準外観。素材の個別値は保存します。'}]})
            row = w.app_rows.get_first_child().get_last_child().get_text()
            check('Flatpak reason is translated', ('The app is running.' in row) if expected=='en' else '起動中です。' in row)
            check('saved rendering note is translated', ('Custom material values are retained.' in row) if expected=='en' else '素材の個別値は保存します。' in row)
            w.save_profile()
            check('save feedback is translated', w.notice.get_title()==i18n._('Profile saved. It has not been applied to your desktop.'))
            w.adapter=PlanAdapter(); w.review(); stage=3
        elif stage == 3:
            dialog=w.get_visible_dialog()
            if not dialog:return True
            check('apply confirmation title', dialog.get_heading()==('変更内容を適用' if expected=='ja' else 'Apply Changes'))
            check('confirmation interpolates both counts', '1' in dialog.get_body() and '{count}' not in dialog.get_body() and '{deferred}' not in dialog.get_body())
            check('confirmation translates saved notes', ('GTK3 uses its standard appearance' in dialog.get_body()) if expected=='en' else 'High Contrastを維持' in dialog.get_body())
            shot('confirmation'); stage=4
        elif stage == 4:
            if not captured('confirmation'):return True
            w.get_visible_dialog().close()
            check('confirmation cancellation has no set', w.adapter.requests==['plan'])
            v=w.gdm_view;v.adapter=GdmAdapter();v.alpha.set_value(44);v.text_toggle.set_active(True);v.text.set_text('#e5faff')
            check('GDM edits stay separate', w.value==baseline and v.value['surface']['opacity']==.44)
            w.stack.set_visible_child_name('gdm');w.content_page.set_title(dict(app.PAGES)['gdm']);w.header_apply.set_visible(False)
            v.run({'action':'status'},v.loaded);stage=5
        elif stage == 5:
            check('authentication cancellation language', w.notice.get_title()==('管理者認証を取り消しました。' if expected=='ja' else 'Administrator authentication was cancelled.'))
            v=w.gdm_view;v.save()
            check('GDM save feedback', v.state.get_text()==i18n._('GDM draft saved. It has not been applied to the login screen.'))
            shot('gdm-editor');stage=6
        elif stage == 6:
            if not captured('gdm-editor'):return True
            w.gdm_view.review();stage=7
        elif stage == 7:
            dialog=w.get_visible_dialog()
            if not dialog:return True
            check('GDM confirmation language',dialog.get_heading()==('ログイン画面に適用' if expected=='ja' else 'Apply to Login Screen'))
            dialog.close()
            check('GDM cancellation has no set',w.gdm_view.adapter.requests==['status','plan'])
            w.stop_watch();w.initialized=False;application.quit()
            (root/(case+'-result.json')).write_text(json.dumps({'status':'passed','language':expected,'checks':checks},ensure_ascii=False,indent=2))
            return False
        return True
    except Exception as error:
        (root/(case+'-result.json')).write_text(json.dumps({'status':'failed','stage':stage,'error':str(error),'checks':checks},ensure_ascii=False,indent=2))
        application.quit();return False

GLib.timeout_add(200,tick)
application.run([sys.argv[0]])
assert json.loads((root/(case+'-result.json')).read_text())['status']=='passed'
