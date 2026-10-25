# SPDX-License-Identifier: MIT
"""User-side GDM editor. Authentication is requested only on explicit operations."""
import base64
import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from gi.repository import Adw,Gdk,Gio,GLib,Gtk
from . import gdm_profile,profile

ENDPOINT=Path('/usr/local/libexec/hyalune-gdm-settings')

class Adapter:
    def __init__(self,private=False):self.private=private
    def call(self,request,done):
        if self.private:
            done({'ok':False,'error':{'code':'private-preview','message':'専用GUI検証から実GDMは変更しません。'}});return
        try:
            info=ENDPOINT.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('管理者所有のGDM処理を確認できません。')
            proc=Gio.Subprocess.new(['/usr/bin/pkexec','--disable-internal-agent',str(ENDPOINT)],Gio.SubprocessFlags.STDIN_PIPE|Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_PIPE)
            def finished(p,result):
                try:
                    _,stdout,stderr=p.communicate_utf8_finish(result);code=p.get_exit_status()
                    if code in (126,127):
                        done({'ok':False,'error':{'code':'authentication-cancelled' if code==126 else 'authorization-failed','message':'管理者認証を取り消しました。' if code==126 else '管理者認証を完了できませんでした。変更は開始していません。'}});return
                    response=json.loads(stdout)
                    if response.get('api')!='hyalune.gdm' or response.get('version')!=1:raise ValueError('未対応のGDM応答です。')
                    done(response)
                except Exception as error:done({'ok':False,'error':{'code':'gdm-adapter-failed','message':str(error)}})
            proc.communicate_utf8_async(json.dumps(request),None,finished)
        except FileNotFoundError:done({'ok':False,'error':{'code':'helper-missing','message':'GDM用の管理者処理が未導入です。導入手順を確認してください。'}})
        except Exception as error:done({'ok':False,'error':{'code':'helper-unavailable','message':str(error)}})

class View(Gtk.Box):
    def __init__(self,window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=14)
        self.window=window;self.adapter=Adapter(bool(window.test_root));self.value=gdm_profile.defaults();self.updating=False;self.current=None;self.dirty=False;self.saved_draft=False;self.preview_serial=0
        self.config=(Path(window.test_root)/'.config' if window.test_root else Path(GLib.get_user_config_dir()))/'hyalune/gdm.json'
        if self.config.is_file():
            try:self.value=gdm_profile.validate(json.loads(self.config.read_text()));self.saved_draft=True
            except (OSError,ValueError):pass
        self.append(self.label('ログイン画面だけに適用します。通常の外観とFlatpakの適用には含みません。'))
        self.state=self.label('状態は未確認です。確認操作を選んだときだけ管理者認証を求めます。');self.append(self.state)
        self.append(self.button('現在のGDM設定を確認',lambda _:self.run({'action':'status'},self.loaded)))
        self.append(self.button('管理者処理の導入手順',self.install_info))
        overlay=Gtk.Overlay();self.picture=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.COVER);self.picture.set_size_request(-1,180);overlay.set_child(self.picture)
        self.face=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8,halign=Gtk.Align.CENTER,valign=Gtk.Align.CENTER,margin_top=20,margin_bottom=20,margin_start=20,margin_end=20)
        self.face.add_css_class('hyalune-gdm-face');self.face.append(self.label('利用者',css_classes=['hyalune-gdm-primary']));self.face.append(Gtk.Entry(placeholder_text='パスワード',editable=False))
        overlay.add_overlay(self.face);overlay.add_css_class('hyalune-gdm-preview');self.append(overlay)
        self.append(self.label('素材と主な文字の参考表示です。認証画面の実描画・High Contrastは別途確認します。',css_classes=['dim-label']))
        self.provider=Gtk.CssProvider();Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),self.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        self.append(self.label('背景'))
        self.background=Gtk.DropDown.new_from_strings(['保存済みの背景を保持','現在のデスクトップ壁紙','Hyaluneの背景','画像を選択'])
        self.background.add_css_class('hyalune-target-selector');self.background.update_property([Gtk.AccessibleProperty.LABEL],['ログイン画面の背景']);self.background.connect('notify::selected',self.background_changed);self.append(self.background)
        self.background_note=self.label('保存済みの画像は実ログイン画面で確認してください。');self.append(self.background_note)
        self.alpha=window.add_scale(self,'ログイン画面の不透明度',lambda v:self.change_surface('opacity',v))
        self.color=window.color_control(self,'ログイン画面の素材色',lambda v:self.change_surface('color',v))
        self.text_toggle=Gtk.CheckButton(label='ユーザー名の文字色を指定');self.text_toggle.connect('toggled',self.text_changed);self.append(self.text_toggle)
        self.text=Gtk.Entry(visible=False,placeholder_text='#f4f6fa');self.text.update_property([Gtk.AccessibleProperty.LABEL],['ログイン画面のユーザー名の文字色']);self.text.connect('changed',self.text_changed);self.append(self.text)
        self.append(self.button('GDMの編集を保存',self.save))
        self.append(self.button('GDMの編集を取り消す',self.cancel))
        self.append(self.button('ログイン画面の変更内容を確認',lambda _:self.review()))
        self.append(self.button('GDMを解除して導入前へ戻す',lambda _:self.review(remove=True)))
        self.append(self.button('GDMの中断を復旧',lambda _:self.confirm_recover()))
        self.fill()

    @staticmethod
    def label(text,**props):return Gtk.Label(label=text,wrap=True,xalign=0,**props)
    @staticmethod
    def button(text,fn):
        b=Gtk.Button(label=text);b.connect('clicked',fn);return b
    def install_info(self,*_):
        dialog=Adw.AlertDialog(heading='GDM管理者処理の導入',body='信頼できる取得済みソースから、管理者が一度だけ実行します。\nsudo ./install.sh manager-gdm install\n\nGUI本体は通常ユーザーで動作します。導入だけではGDMを変更しません。')
        dialog.add_response('close','閉じる');dialog.present(self.window)
    def fill(self):
        self.preview_serial+=1
        self.updating=True;self.alpha.set_value(self.value['surface']['opacity']*100);self.color.set_text(self.value['surface']['color'])
        self.background.set_selected(['keep','desktop','bundled','image'].index(self.value['background']['mode']))
        self.text_toggle.set_active(self.value['text']['mode']=='custom');self.text.set_visible(self.text_toggle.get_active());self.text.set_text(self.value['text'].get('color','#f4f6fa'));self.updating=False;self.preview()
    def change_surface(self,key,value):
        if not self.updating:self.value['surface'][key]=value;self.dirty=True;self.preview()
    def text_changed(self,*_):
        if self.updating:return
        self.dirty=True;custom=self.text_toggle.get_active();self.text.set_visible(custom)
        self.value['text']={'mode':'custom','color':self.text.get_text()} if custom else {'mode':'standard'}
        self.preview()
    def preview(self):
        face=profile.rgba(self.value['surface']);text=self.value['text'].get('color','#f4f6fa')
        try:text=profile.surface({'color':text,'opacity':1})['color']
        except ValueError:text='#f4f6fa'
        self.provider.load_from_string('.hyalune-gdm-preview { background-image: linear-gradient(120deg,#436f77,#867080); border-radius:16px; } .hyalune-gdm-preview .hyalune-gdm-face { background-color:'+face+'; padding:20px; border-radius:18px; border:1px solid alpha(white,.22); } .hyalune-gdm-preview .hyalune-gdm-primary { color:'+text+'; }')
    def background_changed(self,*_):
        if self.updating:return
        self.preview_serial+=1
        mode=['keep','desktop','bundled','image'][self.background.get_selected()]
        if mode=='image':
            dialog=Gtk.FileDialog(title='GDMの静止背景画像を選択')
            filters=Gio.ListStore.new(Gtk.FileFilter);f=Gtk.FileFilter();f.set_name('画像');f.add_pixbuf_formats();filters.append(f);dialog.set_filters(filters)
            def selected(dialog,result):
                try:
                    file=dialog.open_finish(result);path=file.get_path()
                    if not path:raise ValueError('ローカル画像を選択してください。')
                    self.value['background']={'mode':'image','path':path};self.dirty=True;self.decode_preview(path)
                except GLib.Error:self.fill()
                except Exception as error:self.window.error({'error':{'message':str(error)}});self.fill()
            dialog.open(self.window,None,selected);return
        self.value['background']={'mode':mode};self.dirty=True
        if mode=='desktop':self.decode_preview()
        elif mode=='bundled':
            self.picture.set_filename(str(Path(__file__).resolve().parents[2]/'build/Hyalune-GDM/background.svg'));self.background_note.set_text('Hyaluneの背景を使います。')
        else:self.picture.set_paintable(None);self.background_note.set_text('保存済み画像を保持します。')
    def decode_preview(self,path=None):
        self.preview_serial+=1;serial=self.preview_serial
        script=Path(__file__).resolve().parents[2]/'tools/gdm-wallpaper.py'
        args=[sys.executable,'-B',str(script)]+(['--file',path] if path else [])
        p=Gio.Subprocess.new(args,Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_PIPE)
        def done(p,result):
            try:
                _,out,err=p.communicate_utf8_finish(result)
                if serial!=self.preview_serial:return
                data=json.loads(out)
                if 'error' in data:raise ValueError(data['error'])
                self.picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(base64.b64decode(data['png'],validate=True))))
                self.background_note.set_text(Path(path).name if path else '現在のデスクトップ壁紙')
            except Exception as error:self.window.error({'error':{'message':str(error)}})
        p.communicate_utf8_async(None,None,done)
    def run(self,request,done):
        if self.window.busy:return
        self.window.set_busy(True,'GDMの管理者処理を確認しています')
        def completed(response):
            self.window.set_busy(False)
            if not response.get('ok'):self.window.error(response);return
            done(response['result'])
        self.adapter.call(request,completed)
    def loaded(self,state):
        self.current=state
        self.state.set_text('中断があります。復旧を先に実行してください。' if state.get('pending') else ('競合: '+state['conflict'] if state.get('conflict') else 'GDMは管理中です。反映は次のログイン画面からです。' if state['managed'] else 'GDMは未導入です。'))
        if state.get('managed') and not state.get('profile'):self.state.set_text('現在のGDM材質値は未判定です。編集用の既定値を表示しています。')
        if self.dirty or self.saved_draft:self.state.set_text(self.state.get_text()+' 編集内容は保持しています。現在値へ戻すには「編集を取り消す」を選んでください。')
        if state.get('profile') and not self.dirty and not self.saved_draft:self.value=copy.deepcopy(state['profile']);self.fill()
    def review(self,remove=False):
        try:
            if self.color.has_css_class('error'):raise ValueError('素材色を直してください。')
            request={'action':'plan','operation':'remove' if remove else 'set'}
            if not remove:request['profile']=gdm_profile.validate(self.value)
        except ValueError as error:self.window.error({'error':{'message':str(error)}});return
        def planned(plan):
            dialog=Adw.AlertDialog(heading='GDMを解除' if remove else 'ログイン画面に適用',body='ログイン画面だけを変更します。通常テーマ・Flatpakは含みません。\n適用時にも管理者認証を求めます。次のログイン画面から反映し、自動ログアウト・再起動は行いません。')
            dialog.add_response('cancel','キャンセル');dialog.add_response('apply','解除' if remove else '適用');dialog.set_default_response('cancel');dialog.set_close_response('cancel')
            def selected(_,response):
                if response=='apply':
                    final={'action':'remove' if remove else 'set','plan_token':plan['plan_token']}
                    if not remove:final['profile']=request['profile']
                    self.run(final,lambda result:self.applied(result,remove))
            dialog.connect('response',selected);dialog.present(self.window)
        self.run(request,planned)
    def applied(self,result,remove=False):
        self.dirty=False
        if not remove:self.value['background']={'mode':'keep'};self.fill()
        self.state.set_text('GDMを解除しました。次のログイン画面で確認してください。' if remove else 'GDMを更新しました。次のログイン画面で表示と通常ログインを確認してください。')
    def save(self,*_):
        try:
            if self.color.has_css_class('error'):raise ValueError('素材色を直してください。')
            value=gdm_profile.validate(self.value)
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):raise ValueError('リンク先に保存できません。')
            self.config.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):raise ValueError('リンク先に保存できません。')
            fd,path=tempfile.mkstemp(prefix='.gdm-',dir=self.config.parent)
            try:
                with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.flush();os.fsync(f.fileno())
                os.replace(path,self.config)
            finally:
                if os.path.exists(path):os.unlink(path)
            self.dirty=False;self.saved_draft=True;self.state.set_text('GDMの編集を保存しました。実ログイン画面には未適用です。')
        except (OSError,ValueError) as error:self.window.error({'error':{'message':str(error)}})
    def cancel(self,*_):
        self.value=copy.deepcopy((self.current or {}).get('profile') or gdm_profile.defaults());self.dirty=False;self.saved_draft=False;self.fill()

    def confirm_recover(self):
        dialog=Adw.AlertDialog(heading='GDMの中断を復旧',body='GDM専用の保存記録で復旧します。通常テーマは変更しません。')
        dialog.add_response('cancel','キャンセル');dialog.add_response('recover','復旧');dialog.set_close_response('cancel');dialog.connect('response',lambda _,r:self.run({'action':'recover'},lambda result:self.state.set_text('GDMの復旧処理が完了しました。')) if r=='recover' else None);dialog.present(self.window)
