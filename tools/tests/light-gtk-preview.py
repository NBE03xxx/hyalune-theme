# SPDX-License-Identifier: MIT
"""Private window fixtures for Light effect testing."""
import ctypes,json,os,pathlib,sys,gi
kind=sys.argv[1];root=pathlib.Path(os.environ['HYALUNE_LIGHT_ROOT']);project=pathlib.Path(os.environ['HYALUNE_LIGHT_PROJECT'])
gi.require_version('Gtk','4.0' if kind=='4' else '3.0')
from gi.repository import Gtk,GLib,Gdk,Gio
print('GTK'+kind+' imported',flush=True)
if kind=='4':Gtk.init()
if kind=='4':
 gi.require_version('Adw','1');from gi.repository import Adw
 print('Adw init',flush=True);Adw.init();print('Adw ready',flush=True);Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
else:Gtk.init([])
settings=Gtk.Settings.get_default()
if kind=='3':settings.set_property('gtk-theme-name','Adwaita')
print('GTK'+kind+' display ready',flush=True)
provider=Gtk.CssProvider();provider.load_from_path(str(project/('build/Hyalune-Light/gtk-4.0/material.css' if kind=='4' else 'build/Hyalune-Light/gtk-3.0/gtk.css')))
if kind=='4':
 from gi.repository import GObject
 settings.bind_property('gtk-interface-color-scheme',provider,'prefers-color-scheme',GObject.BindingFlags.SYNC_CREATE)
 settings.bind_property('gtk-interface-contrast',provider,'prefers-contrast',GObject.BindingFlags.SYNC_CREATE)
 Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_USER)
else:
 settings.set_property('gtk-application-prefer-dark-theme',False)
 Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_USER)
if kind=='4':
 application=Gtk.Application(application_id='local.hyalune.LightProbe',flags=Gio.ApplicationFlags.NON_UNIQUE);application.register(None)
window=(Gtk.ApplicationWindow(application=application,title='Hyalune Light · GTK4',default_width=590,default_height=420) if kind=='4' else Gtk.Window(title='Hyalune Light · GTK'+kind,default_width=590,default_height=420))
if kind=='3':window.set_visual(window.get_screen().get_rgba_visual())
header=Gtk.HeaderBar();
if kind=='3':header.set_show_close_button(True);header.set_title('Hyalune Light · GTK3')
else:header.set_show_title_buttons(True)
window.set_titlebar(header)
box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14,margin_start=18,margin_end=18,margin_top=18,margin_bottom=18)
label=Gtk.Label(label='日本語の可読性：淡いガラスと濃い文字',xalign=0);box.append(label) if kind=='4' else box.pack_start(label,False,False,0)
widgets=[]
for title in ['標準ボタン','無効なボタン','選択中の操作']:
 b=Gtk.ToggleButton(label=title) if title=='選択中の操作' else Gtk.Button(label=title)
 if title=='無効なボタン':b.set_sensitive(False)
 if title=='選択中の操作':b.set_active(True)
 box.append(b) if kind=='4' else box.pack_start(b,False,False,0);widgets.append(b)
entry=Gtk.Entry(text='長いラベルと入力・キーボードフォーカス');box.append(entry) if kind=='4' else box.pack_start(entry,False,False,0)
if kind=='4':window.set_child(box);window.present()
else:window.add(box);window.show_all()
print('GTK'+kind+' presented',flush=True)
rows=[]
def save():
 print('state',kind,window.get_mapped(),window.get_width() if kind=='4' else window.get_allocated_width(),box.get_width() if kind=='4' else box.get_allocated_width(),flush=True)
 entry.grab_focus()
 if kind=='4':
  # Public C rendering API serializes the actual GTK render tree.
  gtk=ctypes.CDLL('libgtk-4.so.1');glib=ctypes.CDLL('libglib-2.0.so.0');ptr=ctypes.c_void_p;size=ctypes.c_size_t;char=ctypes.c_char_p
  capsule=ctypes.pythonapi.PyCapsule_GetPointer;capsule.argtypes=[ctypes.py_object,char];capsule.restype=ptr
  snap=Gtk.Snapshot.new();box.get_parent().snapshot_child(box,snap)
  gtk.gtk_snapshot_to_node.argtypes=[ptr];gtk.gtk_snapshot_to_node.restype=ptr;gtk.gsk_render_node_serialize.argtypes=[ptr];gtk.gsk_render_node_serialize.restype=ptr;gtk.gsk_render_node_unref.argtypes=[ptr]
  glib.g_bytes_get_data.argtypes=[ptr,ctypes.POINTER(size)];glib.g_bytes_get_data.restype=ptr;glib.g_bytes_unref.argtypes=[ptr]
  node=gtk.gtk_snapshot_to_node(capsule(snap.__gpointer__,None));assert node, 'GTK snapshot is empty';data=gtk.gsk_render_node_serialize(node);length=size();buf=glib.g_bytes_get_data(data,ctypes.byref(length));text=ctypes.string_at(buf,length.value).decode();(root/'gtk4.node').write_text(text);glib.g_bytes_unref(data);gtk.gsk_render_node_unref(node)
  color=label.get_color();rows.append({'name':'GTK4 dark opaque label','passed':color.red<.2 and color.alpha==1,'color':str(color)})
  rows.append({'name':'GTK4 material media follows Light','passed':provider.get_property('prefers-color-scheme')==Gtk.InterfaceColorScheme.LIGHT})
  rows.append({'name':'GTK4 overlay alpha rendered','passed':'0.153846' in text or '0.153847' in text})
  rows.append({'name':'GTK4 focus reaches entry','passed':window.get_focus() is not None})
 else:
  c=label.get_style_context().get_color(Gtk.StateFlags.NORMAL);rows.append({'name':'GTK3 dark opaque label','passed':c.red<.4 and c.alpha==1,'color':str(c)})
  rows.append({'name':'GTK3 focus reaches entry','passed':window.get_focus()==entry})
  disabled=widgets[1].get_style_context().get_color(Gtk.StateFlags.INSENSITIVE);rows.append({'name':'GTK3 disabled distinguished','passed':str(disabled)!=str(c),'color':str(disabled)})
 (root/('gtk'+kind+'-result.json')).write_text(json.dumps(rows,indent=2));return False
GLib.timeout_add(3500,save)
loop=GLib.MainLoop();GLib.timeout_add_seconds(32,lambda:(loop.quit(),False)[1]);loop.run()
