#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run against the INSTALLED app inside a VM-private Wayland session."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import time
root=Path(os.environ['HYALUNE_MANAGER_PROBE']);home=Path(os.environ['HYALUNE_MANAGER_HOME'])
app_root=home/'.local/share/hyalune/settings/app';sys.path.insert(0,str(app_root/'src'))
from manager import app,profile
from gi.repository import GLib,Gio,Gtk
assert os.environ['GSETTINGS_BACKEND']=='keyfile'
checks=[];stage=0;deadline=time.monotonic()+60
application=app.Application(home)

def check(name,value):
 checks.append({'name':name,'passed':bool(value)});assert value,name

def shot(name):
 (root/(name+'.request')).write_text('capture')


def descendants(widget):
 yield widget
 child=widget.get_first_child()
 while child:
  yield from descendants(child)
  child=child.get_next_sibling()


def save_node(widget, name="target-popup"):
 # Gsk's concrete render-node subclasses do not all have GI wrappers. Use the
 # public C serialization API; this is a private VM diagnostic, never live UI.
 import ctypes
 from ctypes import c_void_p,c_size_t,c_char_p
 gtk=ctypes.CDLL('libgtk-4.so.1');glib=ctypes.CDLL('libglib-2.0.so.0')
 capsule=ctypes.pythonapi.PyCapsule_GetPointer;capsule.argtypes=[ctypes.py_object,c_char_p];capsule.restype=c_void_p
 snap=Gtk.Snapshot.new();Gtk.WidgetPaintable.new(widget).snapshot(snap,widget.get_width(),widget.get_height())
 gtk.gtk_snapshot_to_node.argtypes=[c_void_p];gtk.gtk_snapshot_to_node.restype=c_void_p
 gtk.gsk_render_node_serialize.argtypes=[c_void_p];gtk.gsk_render_node_serialize.restype=c_void_p
 gtk.gsk_render_node_unref.argtypes=[c_void_p]
 glib.g_bytes_get_data.argtypes=[c_void_p,ctypes.POINTER(c_size_t)];glib.g_bytes_get_data.restype=c_void_p;glib.g_bytes_unref.argtypes=[c_void_p]
 node=gtk.gtk_snapshot_to_node(capsule(snap.__gpointer__,None));assert node
 data=gtk.gsk_render_node_serialize(node);length=c_size_t();ptr=glib.g_bytes_get_data(data,ctypes.byref(length))
 text=ctypes.string_at(ptr,length.value).decode();glib.g_bytes_unref(data);gtk.gsk_render_node_unref(node)
 (root/(name+'.node')).write_text(text)
 return text

def tick():
 global stage,baseline
 try:
  if time.monotonic()>deadline:raise TimeoutError('GUI probe timeout at stage '+str(stage))
  w=application.window
  if not w or w.busy or not w.initialized:return True
  if stage==0:
   check('installed app starts with appearance page',w.stack.get_visible_child_name()=='appearance')
   check('initial view hides details and target controls',not w.details.get_visible() and not w.target_form.get_visible())
   check('existing panel override summarized', 'パネル' in w.summary.get_text())
   check('GUI is normal user',os.getuid()!=0)
   check('Flatpak page has explicit name',dict(app.PAGES)['apps']=='Flatpakアプリ')
   check('per-app editor stays hidden until a target is chosen',not w.app_editor.get_visible())
   check('GDM state is not queried on application startup',w.gdm_view.current is None)
   baseline=copy.deepcopy(w.value);shot('initial');stage=1
  elif stage==1:
   if not(root/'initial.done').exists():return True
   # Real virtual keyboard activation: focus the disclosure, press Space.
   check('disclosure can receive keyboard focus',w.details_toggle.grab_focus())
   (root/'space.request').write_text('space');stage=2
  elif stage==2:
   if not w.details.get_visible():return True
   check('keyboard opens details without creating values',w.value==baseline)
   check('opening details still requires target choice',not w.target_form.get_visible())
   w.target.grab_focus();w.target.activate();stage=2.1
  elif stage==2.1:
   popup=next((child for child in descendants(w.target) if isinstance(child,Gtk.Popover)),None)
   if not popup or not popup.get_mapped():return True
   check('target chooser opens native popover',popup.get_mapped())
   contents=next(child for child in descendants(popup) if child.get_css_name()=='contents')
   settings=Gtk.Settings.get_default()
   (root/'popup-structure.json').write_text(json.dumps({'scheme':str(settings.get_property('gtk-interface-color-scheme')),'contrast':str(settings.get_property('gtk-interface-contrast')),'dark':app.Adw.StyleManager.get_default().get_dark(),'widgets':[{'type':type(child).__name__,'css':child.get_css_name(),'classes':list(child.get_css_classes()),'parent':child.get_parent().get_css_name() if child.get_parent() else None} for child in descendants(w.target)]},indent=2))
   node=save_node(contents)
   check('target chooser background is alpha 0.8','rgba(26,26,28,0.8)' in node)
   check('chooser foreground widget opacity remains one',contents.get_opacity()==1 and all(child.get_opacity()==1 for child in descendants(contents) if isinstance(child,Gtk.Label)))
   shot('target-popup');stage=2.2
  elif stage==2.2:
   if not(root/'target-popup.done').exists():return True
   (root/'escape.request').write_text('Escape');stage=2.3
  elif stage==2.3:
   popup=next(child for child in descendants(w.target) if isinstance(child,Gtk.Popover))
   if popup.get_mapped():return True
   check('Escape closes target chooser without editing profile',w.value==baseline)
   w.target.remove_css_class('hyalune-target-selector');w.target.activate();stage=2.4
  elif stage==2.4:
   popup=next(child for child in descendants(w.target) if isinstance(child,Gtk.Popover))
   if not popup.get_mapped():return True
   contents=next(child for child in descendants(popup) if child.get_css_name()=='contents')
   node=save_node(contents,'unrelated-dropdown')
   check('unrelated dropdown retains native opaque style','rgba(26,26,28,0.8)' not in node and 'color: rgb(' in node)
   popup.popdown();w.target.add_css_class('hyalune-target-selector')
   Gtk.Settings.get_default().set_property('gtk-interface-contrast',Gtk.InterfaceContrast.MORE);stage=2.5
  elif stage==2.5:
   check('contrast media preference follows display setting',w.chrome_provider.get_property('prefers-contrast')==Gtk.InterfaceContrast.MORE)
   w.target.activate();stage=2.6
  elif stage==2.6:
   popup=next(child for child in descendants(w.target) if isinstance(child,Gtk.Popover))
   if not popup.get_mapped():return True
   contents=next(child for child in descendants(popup) if child.get_css_name()=='contents');node=save_node(contents,'high-contrast-dropdown')
   check('High Contrast restores native opaque style','rgba(26,26,28,0.8)' not in node and 'color: rgb(' in node)
   popup.popdown();Gtk.Settings.get_default().set_property('gtk-interface-contrast',Gtk.InterfaceContrast.NO_PREFERENCE);stage=2.7
  elif stage==2.7:
   w.target.set_selected(1);w.target_scale.set_value(47);stage=3
  elif stage==3:
   check('only selected target editor is shown',w.target_form.get_visible() and w.selected_target()=='panel')
   check('editing panel retains common material',w.value['overrides']['panel']['opacity']==.47 and w.value['common']==baseline['common'])
   candidates=[r for r in w.current['flatpak']['apps'] if r['toolkit'] in ('gtk3','gtk4')]
   if candidates:
    name=candidates[0]['app'];w.open_app(name);w.app_mode.set_selected(1);w.app_scale.set_value(73)
    saved=copy.deepcopy(w.value['flatpak'][name]);w.app_editor.set_visible(False)
    check('closing per-app editor retains custom values',w.value['flatpak'][name]==saved and saved['surface']['opacity']==.73)
    w.value['flatpak'].pop(name,None)
   changed=copy.deepcopy(w.value);w.details_toggle.set_active(False)
   check('closing details retains all overrides',w.value==changed)
   w.details_toggle.set_active(True);shot('details');stage=4
  elif stage==4:
   if not(root/'details.done').exists():return True
   w.inherit();check('common inheritance is an explicit draft edit','panel' not in w.value['overrides'])
   w.cancel_edit();check('cancel restores applied profile',w.value==baseline)
   w.common_scale.set_value(63);w.save_profile();check('saved profile is separate from applied profile',w.value!=w.applied and json.loads(w.config.read_text())['common']['opacity']==.63)
   w.cancel_edit();w.details_toggle.set_active(False);w.set_default_size(540,760);stage=5
  elif stage==5:
   if not w.split.get_collapsed():return True
   check('narrow window collapses navigation',w.split.get_collapsed());shot('narrow');stage=6
  elif stage==6:
   if not(root/'narrow.done').exists():return True
   w.set_default_size(1000,760);w.review();stage=7
  elif stage==7:
   # Review must be cancellable without invoking set.
   dialog=w.get_visible_dialog()
   if not dialog:return True
   check('review opens explicit confirmation',isinstance(dialog,app.Adw.AlertDialog));shot('confirmation');stage=8
  elif stage==8:
   if not(root/'confirmation.done').exists():return True
   w.get_visible_dialog().close();check('review cancellation leaves ownership unchanged',json.loads((home/'.local/state/glass50/installer-material-v1/active.json').read_text())['manager']['profile']==baseline)
   w.common_scale.set_value(66);w.review();stage=9
  elif stage==9:
   dialog=w.get_visible_dialog()
   if not dialog:return True
   def find_apply(widget):
    if isinstance(widget,Gtk.Button) and widget.get_label()=='適用':return widget
    child=widget.get_first_child()
    while child:
     found=find_apply(child)
     if found:return found
     child=child.get_next_sibling()
   apply_button=find_apply(dialog);check('native apply button exists',apply_button is not None)
   apply_button.activate();stage=10
  elif stage==10:
   if w.current['profile']['common']['opacity']!=.66:return True
   check('GUI applies through asynchronous JSON adapter',w.current['profile']['common']['opacity']==.66 and w.applied['common']['opacity']==.66)
   w.perform('undo',None);stage=11
  elif stage==11:
   if w.current['profile']!=baseline:return True
   check('GUI undo restores previous profile and ownership snapshots',json.loads((home/'.local/state/glass50/installer-material-v1/active.json').read_text())['manager']['profile']==baseline)
   w.value=copy.deepcopy(w.applied)
   v=w.gdm_view
   class FakeGdm:
    def __init__(self):self.requests=[]
    def call(self,request,done):
     self.requests.append(copy.deepcopy(request))
     GLib.idle_add(lambda:(done({'ok':False,'error':{'code':'authentication-cancelled','message':'管理者認証を取り消しました。'}}),False)[1])
   v.adapter=FakeGdm();native=copy.deepcopy(w.value);v.alpha.set_value(44);v.text_toggle.set_active(True);v.text.set_text('#e5faff')
   check('GDM editing is separate from ordinary draft',w.value==native and v.value['surface']['opacity']==.44)
   check('GDM text input appears only after opting in',v.text.get_visible() and v.value['text']['mode']=='custom')
   w.stack.set_visible_child_name('gdm');w.content_page.set_title('ログイン画面');w.header_apply.set_visible(False)
   v.run({'action':'status'},v.loaded);stage=12
  elif stage==12:
   check('GDM authentication cancellation is visible and has no set call','取り消しました' in w.notice.get_title() and [r['action'] for r in w.gdm_view.adapter.requests]==['status'])
   v=w.gdm_view;v.save();check('GDM draft save is separate from applied native profile',json.loads(v.config.read_text())['surface']['opacity']==.44 and not v.dirty and w.current['profile']==baseline)
   shot('gdm-editor');stage=13
  elif stage==13:
   if not(root/'gdm-editor.done').exists():return True
   v=w.gdm_view
   class SuccessGdm:
    def __init__(self):self.requests=[]
    def call(self,request,done):
     self.requests.append(copy.deepcopy(request))
     result={'plan_token':'private-fixture-token','operation':'update'} if request['action']=='plan' else {'committed':True,'restart_required':True}
     GLib.idle_add(lambda:(done({'ok':True,'result':result}),False)[1])
   v.adapter=SuccessGdm();v.review();stage=14
  elif stage==14:
   dialog=w.get_visible_dialog()
   if not dialog:return True
   check('GDM confirmation has its own explicit scope',dialog.get_heading()=='ログイン画面に適用')
   apply_button=next(child for child in descendants(dialog) if isinstance(child,Gtk.Button) and child.get_label()=='適用')
   apply_button.activate();stage=15
  elif stage==15:
   v=w.gdm_view
   if len(v.adapter.requests)<2:return True
   check('GDM apply uses separate plan/set with token',[r['action'] for r in v.adapter.requests]==['plan','set'] and v.adapter.requests[-1]['plan_token']=='private-fixture-token')
   check('GDM apply preserves native theme ownership',json.loads((home/'.local/state/glass50/installer-material-v1/active.json').read_text())['manager']['profile']==baseline)
   w.initialized=False;application.quit()
   (root/'ui-result.json').write_text(json.dumps({'status':'passed','checks':checks},ensure_ascii=False,indent=2));return False
  return True
 except Exception as error:
  (root/'ui-result.json').write_text(json.dumps({'status':'failed','stage':stage,'error':str(error),'checks':checks},ensure_ascii=False,indent=2));application.quit();return False
GLib.timeout_add(200,tick)
application.run([sys.argv[0]])
assert (root/'ui-result.json').exists() and json.loads((root/'ui-result.json').read_text())['status']=='passed'
