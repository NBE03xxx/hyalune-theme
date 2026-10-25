# SPDX-License-Identifier: MIT
"""Hyalune Settings. Draft edits never write live theme settings."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk
from . import profile

APP_ID = 'io.github.NBE03xxx.Hyalune.Settings'
ROOT = Path(__file__).resolve().parents[2]
PAGES = [('overview','概要'), ('appearance','外観'), ('blur','ぼかし'), ('gdm','ログイン画面'), ('apps','Flatpakアプリ'), ('history','履歴と復元')]


def label(text='', **kwargs):
    return Gtk.Label(label=text, wrap=True, xalign=0, **kwargs)


def button(text, callback, suggested=False):
    b = Gtk.Button(label=text); b.connect('clicked', callback)
    if suggested: b.add_css_class('suggested-action')
    return b


class Adapter:
    def __init__(self, test_root=None):
        self.test_root = test_root

    def call(self, action, request, callback, operation=None):
        argv = [sys.executable, str(ROOT/'tools/manage-settings.py'), action]
        if self.test_root: argv += ['--test-root', str(self.test_root)]
        if operation: argv += ['--operation', operation]
        try:
            process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
            def done(proc, result):
                try:
                    _, stdout, stderr = proc.communicate_utf8_finish(result)
                    value = json.loads(stdout)
                    if value.get('api') != 'hyalune.settings' or value.get('version') != 1:
                        raise ValueError('未対応の操作応答です。')
                    callback(value)
                except Exception as error:
                    callback({'ok':False,'error':{'code':'adapter-failed','message':str(error)}})
            process.communicate_utf8_async(json.dumps(request) if request else None, None, done)
        except Exception as error:
            callback({'ok':False,'error':{'code':'launch-failed','message':str(error)}})


class Window(Adw.ApplicationWindow):
    def __init__(self, application, test_root=None):
        super().__init__(application=application, title='Hyalune 設定', default_width=1000, default_height=760)
        self.set_size_request(360, 480)
        self.adapter = Adapter(test_root); self.test_root = test_root
        self.value = profile.defaults(); self.applied = None; self.current = None
        self.initialized = False; self.updating = False; self.busy = False
        self.selected_apps = set(); self.plan = None; self.row_controls = []
        self.config = (Path(test_root)/'.config' if test_root else Path(GLib.get_user_config_dir()))/'hyalune/profile.json'
        self.connect('close-request', self.close_request)
        self.split = Adw.NavigationSplitView(min_sidebar_width=190, max_sidebar_width=230)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 720sp'))
        bp.add_setter(self.split, 'collapsed', True); self.add_breakpoint(bp)
        self.set_content(self.split)
        side = Adw.ToolbarView(); side.add_top_bar(Adw.HeaderBar())
        nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, margin_top=12, margin_start=8, margin_end=8)
        nav.add_css_class('navigation-sidebar')
        for key, text in PAGES:
            row = Gtk.ListBoxRow(); row.page_key = key
            row.set_child(label(text, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)); nav.append(row)
        nav.connect('row-selected', self.navigate); side.set_content(nav)
        self.split.set_sidebar(Adw.NavigationPage.new(side, 'Hyalune 設定'))
        content = Adw.ToolbarView(); self.header = Adw.HeaderBar()
        self.refresh = button('再読込', lambda _: self.reload()); self.header.pack_end(self.refresh)
        self.header_apply = button('変更を確認', lambda _: self.review(), True); self.header.pack_end(self.header_apply)
        content.add_top_bar(self.header)
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.notice = Adw.Banner(title='状態を確認しています', revealed=True); layout.append(self.notice)
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        layout.append(self.stack); content.set_content(layout)
        self.content_page = Adw.NavigationPage.new(content, '外観')
        self.split.set_content(self.content_page)
        self.pages = {}
        for key, text in PAGES:
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            clamp = Adw.Clamp(maximum_size=670, tightening_threshold=520)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=22, margin_bottom=28,
                          margin_start=24, margin_end=24)
            title = label(text); title.add_css_class('title-1'); box.append(title)
            clamp.set_child(box); scroll.set_child(clamp); self.stack.add_named(scroll, key); self.pages[key]=box
        self.make_appearance(); self.make_other_pages()
        nav.select_row(nav.get_row_at_index(1))
        self.reload()

    def navigate(self, nav, row):
        if row:
            self.stack.set_visible_child_name(row.page_key)
            self.content_page.set_title(dict(PAGES)[row.page_key]); self.split.set_show_content(True)
            self.header_apply.set_visible(row.page_key not in ('gdm','history'))

    def set_busy(self, value, text=''):
        self.busy = value; self.stack.set_sensitive(not value); self.refresh.set_sensitive(not value)
        self.header_apply.set_sensitive(not value)
        if text: self.notice.set_title(text); self.notice.set_revealed(True)
        if value: self.get_application().hold()
        else: self.get_application().release()

    def error(self, result):
        self.notice.set_title(result.get('error',{}).get('message','処理に失敗しました。'))
        self.notice.set_revealed(True)

    def make_appearance(self):
        box = self.pages['appearance']
        box.append(label('共通の素材を調整し、プレビューで確認してから適用します。'))
        self.preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=4, margin_bottom=4)
        self.preview.add_css_class('hyalune-preview')
        self.preview_panel = label('Hyalune  •  パネルの参考表示', margin_top=14, margin_bottom=14, margin_start=16, margin_end=16)
        self.preview_panel.add_css_class('hyalune-panel'); self.preview.append(self.preview_panel)
        self.preview_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=22, margin_end=22, margin_bottom=24, margin_top=8)
        self.preview_card.add_css_class('hyalune-card')
        self.preview_card.append(label('ガラス素材のプレビュー', margin_top=16, margin_start=16, margin_end=16))
        controls = Gtk.Box(spacing=10, margin_start=16, margin_end=16, margin_bottom=16)
        controls.append(Gtk.Button(label='標準ボタン')); controls.append(Gtk.Switch(active=True, valign=Gtk.Align.CENTER))
        self.preview_card.append(controls); self.preview.append(self.preview_card); box.append(self.preview)
        box.append(label('GTK部品の実描画と素材の参考表示です。Shell／GDMの実画面や実ぼかしを再現するものではありません。', css_classes=['dim-label']))
        self.common_scale = self.add_scale(box, '共通の不透明度', lambda v:self.change_surface('common','opacity',v))
        self.common_color = self.color_control(box, '素材色', lambda v:self.change_surface('common','color',v))
        self.summary = label('パネルに個別設定あり（38％）。ログイン画面は別操作で32％。'); box.append(self.summary)
        self.details_toggle = Gtk.ToggleButton(label='部分ごとに調整'); box.append(self.details_toggle)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, visible=False)
        box.append(self.details)
        self.details_toggle.connect('toggled', lambda b:self.details.set_visible(b.get_active()))
        self.target = Gtk.DropDown.new_from_strings(['対象を選択', *profile.TARGETS.values()])
        self.target.add_css_class('hyalune-target-selector')
        self.target.update_property([Gtk.AccessibleProperty.LABEL], ['個別調整の対象'])
        self.target.connect('notify::selected', self.select_target); self.details.append(self.target)
        self.target_form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, visible=False); self.details.append(self.target_form)
        self.target_scale = self.add_scale(self.target_form, '選択した対象の不透明度', self.target_opacity)
        self.target_color = self.color_control(self.target_form, '対象の素材色', self.target_color_changed)
        self.target_form.append(button('この対象を共通設定に戻す', self.inherit))
        self.edit_state = label(''); box.append(self.edit_state)
        actions = Gtk.Box(spacing=10, orientation=Gtk.Orientation.VERTICAL)
        self.apply_button = button('変更内容を確認して適用', lambda _:self.review(), True); actions.append(self.apply_button)
        actions.append(button('プロファイルを保存', self.save_profile))
        actions.append(button('編集を取り消す', self.cancel_edit))
        actions.append(button('Hyaluneの既定値を編集に戻す', self.reset_defaults))
        box.append(actions)
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        # Fixed app chrome, independent of the unapplied preview's material.
        self.chrome_provider = Gtk.CssProvider()
        # Custom providers have their own media-query preferences. Follow the
        # display settings with one-way bindings; never write desktop settings.
        settings = Gtk.Settings.get_for_display(Gdk.Display.get_default())
        self.chrome_bindings = [settings.bind_property(source, self.chrome_provider, target, GObject.BindingFlags.SYNC_CREATE)
                                for source, target in [('gtk-interface-color-scheme','prefers-color-scheme'),
                                                       ('gtk-interface-contrast','prefers-contrast')]]
        self.chrome_provider.load_from_path(str(Path(__file__).with_name('style.css')))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.chrome_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        self.sync_form()

    def add_scale(self, box, title, callback):
        box.append(label(title))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        scale.set_draw_value(True); scale.set_value_pos(Gtk.PositionType.RIGHT); scale.set_digits(0)
        scale.update_property([Gtk.AccessibleProperty.LABEL],[title])
        scale.connect('value-changed', lambda w:callback(round(w.get_value()/100,2)) if not self.updating else None)
        box.append(scale); return scale

    def color_control(self, box, title, callback):
        row = Gtk.Box(spacing=10, orientation=Gtk.Orientation.VERTICAL)
        choose = Gtk.CheckButton(label=title+'を調整'); row.append(choose)
        entry = Gtk.Entry(placeholder_text='#1a1a1c', visible=False)
        entry.update_property([Gtk.AccessibleProperty.LABEL],[title+'（#RRGGBB）'])
        row.append(entry); box.append(row)
        choose.connect('toggled', lambda b:entry.set_visible(b.get_active()))
        def changed(w):
            if not self.updating:
                try: color = profile.surface({'opacity':.56,'color':w.get_text()})['color']
                except ValueError: w.add_css_class('error'); return
                w.remove_css_class('error'); callback(color)
        entry.connect('changed', changed)
        # Hiding the entry retains the selected color. Returning to default is
        # the explicit default/common action, never the disclosure checkbox.
        return entry

    def change_surface(self, scope, field, value):
        self.value[scope][field] = value; self.changed()

    def selected_target(self):
        i = self.target.get_selected()
        return list(profile.TARGETS)[i-1] if 1 <= i <= len(profile.TARGETS) else None

    def select_target(self, *_):
        key = self.selected_target(); self.target_form.set_visible(bool(key))
        if key:
            self.updating=True; v=profile.effective(self.value,key)
            self.target_scale.set_value(v['opacity']*100); self.target_color.set_text(v['color']); self.updating=False
            self.target_color.remove_css_class('error')

    def target_opacity(self, alpha):
        key = self.selected_target()
        if key:
            self.value['overrides'].setdefault(key, copy.deepcopy(self.value['common']))['opacity']=alpha; self.changed()

    def target_color_changed(self, color):
        key = self.selected_target()
        if key:
            self.value['overrides'].setdefault(key, copy.deepcopy(self.value['common']))['color']=color; self.changed()

    def inherit(self, *_):
        key=self.selected_target()
        if key: self.value['overrides'].pop(key,None); self.select_target(); self.changed()

    def changed(self):
        self.plan=None
        self.summary.set_text('個別設定: '+('、'.join(profile.TARGETS[k] for k in self.value['overrides']) or 'なし')+'。ログイン画面は別管理（既定32％）。')
        dirty = self.applied is None or self.value != self.applied
        self.edit_state.set_text('未適用の編集があります。保存だけでは実環境に反映しません。' if dirty else '最後に配置したプロファイルと同じ値です。実読み込みは別途確認してください。')
        p=profile.rgba(profile.effective(self.value,'panel')); c=profile.rgba(self.value['common'])
        self.provider.load_from_string('''
.hyalune-preview { background-image: linear-gradient(135deg, #286c83, #8c5965 48%%, #c0ad79); border-radius: 18px; }
.hyalune-preview .hyalune-panel { background-color: %s; color: #f4f6fa; border-radius: 14px; }
.hyalune-preview .hyalune-card { background-color: %s; color: #f4f6fa; border-radius: 16px; border: 1px solid alpha(white,.22); }
''' % (p,c))

    def sync_form(self):
        self.updating=True
        self.common_scale.set_value(self.value['common']['opacity']*100); self.common_color.set_text(self.value['common']['color'])
        self.common_color.remove_css_class('error')
        if hasattr(self,'blur_switches'):
            for k,w in self.blur_switches.items(): w.set_active(self.value['blur'][k])
        self.updating=False; self.select_target(); self.changed()
        if getattr(self,'active_app',None):
            visible=self.app_editor.get_visible();self.open_app(self.active_app);self.app_editor.set_visible(visible)

    def make_other_pages(self):
        self.overview_text=label('確認しています'); self.pages['overview'].append(self.overview_text)
        self.pages['overview'].append(button('配置状態を再読込',lambda _:self.reload()))
        b=self.pages['blur']; b.append(label('Quick Settingsとウィンドウの効果を個別に選べます。「適用」まで反映しません。'))
        self.blur_switches={}
        for key,title in [('quick_settings','Quick Settingsのぼかし'),('windows','ウィンドウの素材効果')]:
            row=Adw.SwitchRow(title=title); b.append(row); self.blur_switches[key]=row
            row.connect('notify::active',lambda w,_,k=key:self.change_blur(k,w.get_active()))
        b.append(label('既存拡張の対応条件で動きます。配置／設定の有効と実際の描画は区別します。倍率・High Contrast等により停止する場合があります。'))
        b.append(button('変更内容を確認して適用',lambda _:self.review(),True))
        from .gdm_ui import View
        self.gdm_view=View(self);self.pages['gdm'].append(self.gdm_view)
        apps=self.pages['apps']; apps.append(label('共通設定へ追従するアプリは「適用」のたびに更新します。起動中や競合中の対象は保留し、勝手に終了しません。'))
        apps.append(button('再検出',lambda _:self.reload())); self.app_rows=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8); apps.append(self.app_rows)
        self.app_editor=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,visible=False);apps.append(self.app_editor)
        self.app_title=label('');self.app_editor.append(self.app_title);self.active_app=None
        self.app_mode=Gtk.DropDown.new_from_strings(['共通設定に追従','個別設定','現在の適用を保持'])
        self.app_mode.add_css_class('hyalune-target-selector');self.app_mode.update_property([Gtk.AccessibleProperty.LABEL],['Flatpakの設定方法'])
        self.app_mode.connect('notify::selected',self.app_mode_changed);self.app_editor.append(self.app_mode)
        self.app_custom=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,visible=False);self.app_editor.append(self.app_custom)
        self.app_scale=self.add_scale(self.app_custom,'このアプリの不透明度',lambda v:self.app_surface_changed('opacity',v))
        self.app_color=self.color_control(self.app_custom,'このアプリの素材色',lambda v:self.app_surface_changed('color',v))
        self.app_editor.append(button('個別設定を閉じる',lambda _:self.app_editor.set_visible(False)))
        apps.append(button('変更内容を確認して適用',lambda _:self.review(),True))
        h=self.pages['history']; h.append(label('テーマ解除は管理中Flatpakを含みます。GDMは別操作です。アプリ本体の解除やバックアップ削除は行いません。'))
        h.append(button('直前の適用へ戻す',lambda _:self.confirm_operation('undo','直前の適用へ戻す','最後の更新直前の通常テーマ・設定・対象Flatpakを、そのままの記録から戻します。現在値が履歴と異なる場合は停止します。')))
        h.append(button('中断した処理を復旧',lambda _:self.confirm_operation('recover','中断した処理を復旧','既存journalを使って復旧します。')))
        h.append(button('テーマを解除して導入前へ戻す',lambda _:self.review_remove()))
        self.history_text=label(''); h.append(self.history_text)

    def change_blur(self,key,value):
        if not self.updating: self.value['blur'][key]=value; self.changed()

    def reload(self):
        if self.busy:return
        self.set_busy(True,'配置状態とFlatpakを確認しています')
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):self.error(response);return
            state=response['result']; self.current=state
            if not self.initialized:
                self.applied=profile.upgrade(state['profile']) if state['profile'] else None
                self.value=profile.upgrade(state['profile'] or profile.defaults())
                if state['profile'] is None: self.value['blur']=copy.deepcopy(state['blur'])
                if self.config.is_file():
                    try:self.value=profile.upgrade(json.loads(self.config.read_text()))
                    except Exception as error:self.error({'error':{'message':'保存プロファイルを読み込めません: '+str(error)}})
                self.initialized=True;self.sync_form()
            else:
                self.applied=profile.upgrade(state['profile']) if state['profile'] else None; self.changed()
            issues=[]
            if getattr(self,'pending_result',None):issues.append(self.pending_result);self.pending_result=None
            if state['pending']:issues.append('中断があります。履歴と復元から復旧してください。')
            if state['legacy_pending']:issues.append('旧導入の中断があります。既存CLIで復旧してください。')
            if state['conflicts']:issues.append('外部変更を検出しました。適用前に競合を解消してください。')
            if state['identification']=='unidentified-fixed-values':issues.append('旧版の値は未判定です。編集用の既定値を表示しています。')
            self.notice.set_title(' '.join(issues) or '配置状態を確認しました。実読み込みは未確認です。');self.notice.set_revealed(True)
            self.apply_button.set_sensitive(not(state['pending'] or state['legacy_pending'] or state['conflicts']))
            self.overview_text.set_text(('通常テーマ: '+str(state['version']) if state['managed'] else '通常テーマ: 未導入')+'\nプロファイル: '+state['identification']+'\nGDM: 明示した管理者確認が必要\n'+state['runtime']['note'])
            self.update_apps(state['flatpak'])
            self.history_text.set_text('\n\n'.join(r['at']+'\n'+r['action']+' / '+r['status'] for r in state['history']) or '適用履歴はありません。')
        self.adapter.call('status',None,done)

    def update_apps(self,inventory):
        self.inventory=inventory
        child=self.app_rows.get_first_child()
        while child:
            nxt=child.get_next_sibling();self.app_rows.remove(child);child=nxt
        self.row_controls=[]
        statuses={'candidate':'未適用','already-managed':'管理中','deferred':'起動中・保留','conflict':'競合','skipped':'未対応／未判定'}
        modes={'follow':'共通設定に追従','custom':'個別設定','hold':'現在の適用を保持'}
        for row in inventory['apps']:
            app_id=row['app']
            if app_id not in self.value['flatpak'] and row.get('policy',{}).get('mode')!='hold':
                self.value['flatpak'][app_id]=copy.deepcopy(row['policy'])
            policy=self.value['flatpak'].get(app_id,{'mode':'hold'})
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
            w=button(app_id,lambda _,name=app_id:self.open_app(name));w.set_sensitive(row['toolkit'] in ('gtk3','gtk4'))
            box.append(w);box.append(label(statuses.get(row['status'],row['status'])+' · '+modes[policy['mode']]+(' · 再適用待ち' if row.get('needs_update') else '')+'\n'+row.get('reason',''),css_classes=['dim-label']))
            self.app_rows.append(box);self.row_controls.append(w)
        if not inventory['apps']:self.app_rows.append(label('Flatpakアプリはありません。' if inventory['available'] else 'Flatpakは導入されていません。'))

    def open_app(self,name):
        self.active_app=name;self.app_title.set_text(name);self.app_editor.set_visible(True)
        policy=self.value['flatpak'].get(name,{'mode':'hold'})
        self.updating=True;self.app_mode.set_selected(['follow','custom','hold'].index(policy['mode']))
        face=policy.get('surface',self.value['common']);self.app_scale.set_value(face['opacity']*100);self.app_color.set_text(face['color']);self.app_color.remove_css_class('error')
        self.app_custom.set_visible(policy['mode']=='custom');self.updating=False

    def app_mode_changed(self,*_):
        if self.updating or not self.active_app:return
        mode=['follow','custom','hold'][self.app_mode.get_selected()]
        old=self.value['flatpak'].get(self.active_app,{})
        self.value['flatpak'][self.active_app]={'mode':mode}
        if mode=='custom':self.value['flatpak'][self.active_app]['surface']=copy.deepcopy(old.get('surface',self.value['common']))
        self.open_app(self.active_app);self.changed()

    def app_surface_changed(self,key,value):
        if self.updating or not self.active_app:return
        self.value['flatpak'][self.active_app]['surface'][key]=value;self.changed()

    def validate_inputs(self):
        if self.common_color.has_css_class('error') or self.target_color.has_css_class('error') or self.app_color.has_css_class('error'):
            raise ValueError('素材色を #RRGGBB 形式に直してから進めてください。')

    def request(self):
        self.validate_inputs()
        return {'profile':profile.validate(self.value),'apps':[]}

    def review(self):
        if self.busy:return
        try: request=self.request()
        except ValueError as error:self.error({'error':{'message':str(error)}});return
        self.set_busy(True,'変更計画を確認しています')
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):self.error(response);return
            result=response['result'];token=result['manager']['token']
            self.plan=copy.deepcopy(request)
            d=Adw.AlertDialog(heading='変更内容を適用',body='通常テーマと追従・個別設定のFlatpak '+str(sum(r.get('status')=='planned' for r in result['manager']['apps']))+'件を変更します。\n保留 '+str(sum(r.get('status')=='deferred' for r in result['manager']['apps']))+'件。GDMは含みません。\nアプリの再起動や再ログインが必要です。')
            d.add_response('cancel','キャンセル');d.add_response('apply','適用');d.set_response_appearance('apply',Adw.ResponseAppearance.SUGGESTED)
            d.set_default_response('cancel');d.set_close_response('cancel')
            def selected(dialog,response):
                if response=='apply':self.perform('set',dict(request,plan_token=token))
            d.connect('response',selected);d.present(self)
        self.adapter.call('plan',request,done)

    def review_remove(self):
        if self.busy:return
        self.set_busy(True,'解除計画を確認しています')
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):self.error(response);return
            self.confirm_operation('remove','導入前へ戻す','通常テーマと管理中Flatpakを解除します。GDMと全バックアップを保持します。', {'plan_token':response['result']['manager']['token']})
        self.adapter.call('plan',None,done,operation='remove')

    def confirm_operation(self,action,title,body,request=None):
        d=Adw.AlertDialog(heading=title,body=body);d.add_response('cancel','キャンセル');d.add_response('yes',title)
        d.set_default_response('cancel');d.set_close_response('cancel')
        d.connect('response',lambda _,r:self.perform(action,request) if r=='yes' else None);d.present(self)

    def perform(self,action,request):
        if self.busy:return
        self.set_busy(True,'処理中です。完了・復旧までお待ちください')
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):self.error(response);return
            if action=='set':self.applied=copy.deepcopy(request['profile'])
            self.reload()
            deferred=[r for r in response.get('result',{}).get('manager',{}).get('apps',[]) if r.get('status')=='deferred']
            if deferred:self.pending_result='一部のFlatpakを保留しました: '+'、'.join(r['app']+'（'+r['reason']+'）' for r in deferred)
        self.adapter.call(action,request,done)

    def save_profile(self,*_):
        try:
            self.validate_inputs()
            data=profile.canonical(self.value)
            # Profile data is separate from the engine's appearance ownership.
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):
                raise ValueError('リンク先には保存できません。')
            self.config.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):
                raise ValueError('リンク先には保存できません。')
            fd,path=tempfile.mkstemp(prefix='.profile-',dir=self.config.parent)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.replace(path,self.config)
            finally:
                if os.path.exists(path):os.unlink(path)
            self.notice.set_title('プロファイルを保存しました。実環境には未適用です。')
        except Exception as error:self.error({'error':{'message':str(error)}})

    def cancel_edit(self,*_):
        self.value=copy.deepcopy(self.applied or profile.defaults());self.sync_form()

    def reset_defaults(self,*_):
        policies=copy.deepcopy(self.value.get('flatpak',{}));self.value=profile.defaults();self.value['flatpak']=policies;self.sync_form()

    def close_request(self,*_):
        if self.busy:
            self.notice.set_title('処理完了まで閉じずにお待ちください。中断時のjournalは保持されます。');return True
        if self.initialized and (self.value != (self.applied or profile.defaults()) or self.gdm_view.dirty):
            d=Adw.AlertDialog(heading='未適用の編集があります',body='保存していない編集は閉じると破棄します。実環境は変更しません。')
            d.add_response('cancel','編集を続ける');d.add_response('close','閉じる');d.set_close_response('cancel')
            def selected(_,r):
                if r=='close':self.initialized=False;self.close()
            d.connect('response',selected);d.present(self);return True
        return False


class Application(Adw.Application):
    def __init__(self,test_root=None):
        super().__init__(application_id=APP_ID,flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.test_root=test_root;self.window=None
        self.set_resource_base_path('/io/github/NBE03xxx/Hyalune/Settings')
    def do_activate(self):
        if self.window is None:self.window=Window(self,self.test_root)
        self.window.present()


def main():
    p=argparse.ArgumentParser();p.add_argument('--test-root',type=Path);a=p.parse_args()
    if os.getuid()==0 or os.geteuid()!=os.getuid():p.error('通常ユーザーで起動してください。')
    GLib.set_application_name('Hyalune 設定');Gtk.Window.set_default_icon_name(APP_ID)
    return Application(a.test_root).run([sys.argv[0]])
