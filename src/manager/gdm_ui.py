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
from .i18n import _, message
from . import gdm_profile,profile

ENDPOINT=Path('/usr/local/libexec/hyalune-gdm-settings')

class Adapter:
    def __init__(self,private=False):self.private=private
    def call(self,request,done):
        if self.private:
            done({'ok':False,'error':{'code':'private-preview','message':_('The private GUI test cannot change the real GDM.')}});return
        try:
            info=ENDPOINT.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError(_('Cannot verify the administrator-owned GDM helper.'))
            proc=Gio.Subprocess.new(['/usr/bin/pkexec','--disable-internal-agent',str(ENDPOINT)],Gio.SubprocessFlags.STDIN_PIPE|Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_PIPE)
            def finished(p,result):
                try:
                    unused,stdout,stderr=p.communicate_utf8_finish(result);code=p.get_exit_status()
                    if code in (126,127):
                        done({'ok':False,'error':{'code':'authentication-cancelled' if code==126 else 'authorization-failed','message':_('Administrator authentication was cancelled.') if code==126 else _('Administrator authentication could not be completed. No changes have started.')}});return
                    response=json.loads(stdout)
                    if response.get('api')!='hyalune.gdm' or response.get('version')!=1:raise ValueError(_('Unsupported GDM response.'))
                    done(response)
                except Exception as error:done({'ok':False,'error':{'code':'gdm-adapter-failed','message':str(error)}})
            proc.communicate_utf8_async(json.dumps(request),None,finished)
        except FileNotFoundError:done({'ok':False,'error':{'code':'helper-missing','message':_('The GDM administrator helper is not installed. See the installation instructions.')}})
        except Exception as error:done({'ok':False,'error':{'code':'helper-unavailable','message':str(error)}})

class View(Gtk.Box):
    def __init__(self,window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=14)
        self.window=window;self.adapter=Adapter(bool(window.test_root));self.value=gdm_profile.defaults();self.updating=False;self.current=None;self.dirty=False;self.saved_draft=False;self.preview_serial=0
        self.config=(Path(window.test_root)/'.config' if window.test_root else Path(GLib.get_user_config_dir()))/'hyalune/gdm.json'
        if self.config.is_file():
            try:self.value=gdm_profile.validate(json.loads(self.config.read_text()));self.saved_draft=True
            except (OSError,ValueError):pass
        self.append(self.label(_('Applies only to the login screen. It is separate from desktop appearance and Flatpak changes.')))
        self.state=self.label(_('Status has not been checked. Administrator authentication is requested only when you choose to check it.'));self.append(self.state)
        self.append(self.button(_('Check Current GDM Settings'),lambda unused:self.run({'action':'status'},self.loaded)))
        self.append(self.button(_('Helper Installation Instructions'),self.install_info))
        overlay=Gtk.Overlay();self.picture=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.COVER);self.picture.set_size_request(-1,180);overlay.set_child(self.picture)
        self.face=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8,halign=Gtk.Align.CENTER,valign=Gtk.Align.CENTER,margin_top=20,margin_bottom=20,margin_start=20,margin_end=20)
        self.face.add_css_class('hyalune-gdm-face');self.face.append(self.label(_('User'),css_classes=['hyalune-gdm-primary']));self.face.append(Gtk.Entry(placeholder_text=_('Password'),editable=False))
        overlay.add_overlay(self.face);overlay.add_css_class('hyalune-gdm-preview');self.append(overlay)
        self.append(self.label(_('A preview of the material and primary text. Verify the actual login screen and High Contrast separately.'),css_classes=['dim-label']))
        self.provider=Gtk.CssProvider();Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),self.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        self.append(self.label(_('Background')))
        self.background=Gtk.DropDown.new_from_strings([_('Keep Saved Background'),_('Current Desktop Wallpaper'),_('Hyalune Background'),_('Choose an Image')])
        self.background.add_css_class('hyalune-target-selector');self.background.update_property([Gtk.AccessibleProperty.LABEL],[_('Login screen background')]);self.background.connect('notify::selected',self.background_changed);self.append(self.background)
        self.background_note=self.label(_('Check the saved image on the actual login screen.'));self.append(self.background_note)
        self.alpha=window.add_scale(self,_('Login Screen Opacity'),lambda v:self.change_surface('opacity',v))
        self.color=window.color_control(self,_('Login Screen Material Color'),lambda v:self.change_surface('color',v))
        self.text_toggle=Gtk.CheckButton(label=_('Customize Username Text Color'));self.text_toggle.connect('toggled',self.text_changed);self.append(self.text_toggle)
        self.text=Gtk.Entry(visible=False,placeholder_text='#f4f6fa');self.text.update_property([Gtk.AccessibleProperty.LABEL],[_('Login screen username text color')]);self.text.connect('changed',self.text_changed);self.append(self.text)
        self.append(self.button(_('Save GDM Draft'),self.save))
        self.append(self.button(_('Discard GDM Edits'),self.cancel))
        self.append(self.button(_('Review Login Screen Changes'),lambda unused:self.review()))
        self.append(self.button(_('Remove GDM Theme and Restore Previous Settings'),lambda unused:self.review(remove=True)))
        self.append(self.button(_('Recover Interrupted GDM Operation'),lambda unused:self.confirm_recover()))
        self.fill()

    @staticmethod
    def label(text,**props):return Gtk.Label(label=text,wrap=True,xalign=0,**props)
    @staticmethod
    def button(text,fn):
        b=Gtk.Button(label=text);b.connect('clicked',fn);return b
    def install_info(self,*unused):
        dialog=Adw.AlertDialog(heading=_('Install GDM Administrator Helper'),body=_('An administrator runs this once from a trusted source checkout.\nsudo ./install.sh manager-gdm install\n\nThe GUI runs as a regular user. Installing the helper alone does not change GDM.'))
        dialog.add_response('close',_('Close'));dialog.present(self.window)
    def fill(self):
        self.preview_serial+=1
        self.updating=True;self.alpha.set_value(self.value['surface']['opacity']*100);self.color.set_text(self.value['surface']['color'])
        self.background.set_selected(['keep','desktop','bundled','image'].index(self.value['background']['mode']))
        self.text_toggle.set_active(self.value['text']['mode']=='custom');self.text.set_visible(self.text_toggle.get_active());self.text.set_text(self.value['text'].get('color','#f4f6fa'));self.updating=False;self.preview()
    def change_surface(self,key,value):
        if not self.updating:self.value['surface'][key]=value;self.dirty=True;self.preview()
    def text_changed(self,*unused):
        if self.updating:return
        self.dirty=True;custom=self.text_toggle.get_active();self.text.set_visible(custom)
        self.value['text']={'mode':'custom','color':self.text.get_text()} if custom else {'mode':'standard'}
        self.preview()
    def preview(self):
        face=profile.rgba(self.value['surface']);text=self.value['text'].get('color','#f4f6fa')
        try:text=profile.surface({'color':text,'opacity':1})['color']
        except ValueError:text='#f4f6fa'
        self.provider.load_from_string('.hyalune-gdm-preview { background-image: linear-gradient(120deg,#436f77,#867080); border-radius:16px; } .hyalune-gdm-preview .hyalune-gdm-face { background-color:'+face+'; padding:20px; border-radius:18px; border:1px solid alpha(white,.22); } .hyalune-gdm-preview .hyalune-gdm-primary { color:'+text+'; }')
    def background_changed(self,*unused):
        if self.updating:return
        self.preview_serial+=1
        mode=['keep','desktop','bundled','image'][self.background.get_selected()]
        if mode=='image':
            dialog=Gtk.FileDialog(title=_('Choose a Static GDM Background Image'))
            filters=Gio.ListStore.new(Gtk.FileFilter);f=Gtk.FileFilter();f.set_name(_('Images'));f.add_pixbuf_formats();filters.append(f);dialog.set_filters(filters)
            def selected(dialog,result):
                try:
                    file=dialog.open_finish(result);path=file.get_path()
                    if not path:raise ValueError(_('Choose a local image.'))
                    self.value['background']={'mode':'image','path':path};self.dirty=True;self.decode_preview(path)
                except GLib.Error:self.fill()
                except Exception as error:self.window.error({'error':{'message':str(error)}});self.fill()
            dialog.open(self.window,None,selected);return
        self.value['background']={'mode':mode};self.dirty=True
        if mode=='desktop':self.decode_preview()
        elif mode=='bundled':
            self.picture.set_filename(str(Path(__file__).resolve().parents[2]/'build/Hyalune-GDM/background.svg'));self.background_note.set_text(_('Uses the Hyalune background.'))
        else:self.picture.set_paintable(None);self.background_note.set_text(_('Keeps the saved image.'))
    def decode_preview(self,path=None):
        self.preview_serial+=1;serial=self.preview_serial
        script=Path(__file__).resolve().parents[2]/'tools/gdm-wallpaper.py'
        args=[sys.executable,'-B',str(script)]+(['--file',path] if path else [])
        p=Gio.Subprocess.new(args,Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_PIPE)
        def done(p,result):
            try:
                unused,out,err=p.communicate_utf8_finish(result)
                if serial!=self.preview_serial:return
                data=json.loads(out)
                if 'error' in data:raise ValueError(data['error'])
                self.picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(base64.b64decode(data['png'],validate=True))))
                self.background_note.set_text(Path(path).name if path else _('Current Desktop Wallpaper'))
            except Exception as error:self.window.error({'error':{'message':str(error)}})
        p.communicate_utf8_async(None,None,done)
    def run(self,request,done):
        if self.window.busy:return
        self.window.set_busy(True,_('Checking the GDM administrator helper'))
        def completed(response):
            self.window.set_busy(False)
            if not response.get('ok'):self.window.error(response);return
            done(response['result'])
        self.adapter.call(request,completed)
    def loaded(self,state):
        self.current=state
        self.state.set_text(_('An operation was interrupted. Run recovery first.') if state.get('pending') else (_('Conflict: {details}').format(details=message(state['conflict'])) if state.get('conflict') else _('GDM is managed. Changes take effect on the next login screen.') if state['managed'] else _('The GDM theme is not installed.')))
        if state.get('managed') and not state.get('profile'):self.state.set_text(_('The current GDM material values are unknown. Defaults are shown for editing.'))
        if self.dirty or self.saved_draft:self.state.set_text(self.state.get_text()+_(' Edits are retained. Choose Discard Edits to return to the current values.'))
        if state.get('profile') and not self.dirty and not self.saved_draft:self.value=copy.deepcopy(state['profile']);self.fill()
    def review(self,remove=False):
        try:
            if self.color.has_css_class('error'):raise ValueError(_('Correct the material color.'))
            request={'action':'plan','operation':'remove' if remove else 'set'}
            if not remove:request['profile']=gdm_profile.validate(self.value)
        except ValueError as error:self.window.error({'error':{'message':str(error)}});return
        def planned(plan):
            dialog=Adw.AlertDialog(heading=_('Remove GDM Theme') if remove else _('Apply to Login Screen'),body=_('Only the login screen will be changed. The desktop theme and Flatpak apps are not included.\nAdministrator authentication is also required when applying. Changes take effect on the next login screen. You will not be logged out and GDM will not be restarted automatically.'))
            dialog.add_response('cancel',_('Cancel'));dialog.add_response('apply',_('Remove') if remove else _('Apply'));dialog.set_default_response('cancel');dialog.set_close_response('cancel')
            def selected(unused,response):
                if response=='apply':
                    final={'action':'remove' if remove else 'set','plan_token':plan['plan_token']}
                    if not remove:final['profile']=request['profile']
                    self.run(final,lambda result:self.applied(result,remove))
            dialog.connect('response',selected);dialog.present(self.window)
        self.run(request,planned)
    def applied(self,result,remove=False):
        self.dirty=False
        if not remove:self.value['background']={'mode':'keep'};self.fill()
        self.state.set_text(_('GDM theme removed. Check the next login screen.') if remove else _('GDM updated. Check its appearance and normal login on the next login screen.'))
    def save(self,*unused):
        try:
            if self.color.has_css_class('error'):raise ValueError(_('Correct the material color.'))
            value=gdm_profile.validate(self.value)
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):raise ValueError(_('Cannot save to a symbolic link.'))
            self.config.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):raise ValueError(_('Cannot save to a symbolic link.'))
            fd,path=tempfile.mkstemp(prefix='.gdm-',dir=self.config.parent)
            try:
                with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.flush();os.fsync(f.fileno())
                os.replace(path,self.config)
            finally:
                if os.path.exists(path):os.unlink(path)
            self.dirty=False;self.saved_draft=True;self.state.set_text(_('GDM draft saved. It has not been applied to the login screen.'))
        except (OSError,ValueError) as error:self.window.error({'error':{'message':str(error)}})
    def cancel(self,*unused):
        self.value=copy.deepcopy((self.current or {}).get('profile') or gdm_profile.defaults());self.dirty=False;self.saved_draft=False;self.fill()

    def confirm_recover(self):
        dialog=Adw.AlertDialog(heading=_('Recover Interrupted GDM Operation'),body=_('Recover using the saved GDM records. The desktop theme will not be changed.'))
        dialog.add_response('cancel',_('Cancel'));dialog.add_response('recover',_('Recover'));dialog.set_close_response('cancel');dialog.connect('response',lambda unused,r:self.run({'action':'recover'},lambda result:self.state.set_text(_('GDM recovery completed.'))) if r=='recover' else None);dialog.present(self.window)
