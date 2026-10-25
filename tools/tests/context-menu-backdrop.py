# SPDX-License-Identifier: MIT
import os
assert (os.environ.get("GLASS50_ISOLATED_PROBE")=="1" or os.environ.get("GLASS50_MANAGED_PROBE")=="1") and os.environ.get("GSETTINGS_BACKEND")=="keyfile"
import gi,sys
from pathlib import Path
gi.require_version('Gtk','4.0');gi.require_version('Adw','1')
from gi.repository import Gtk,Adw,Gio
app=Adw.Application(application_id='local.myglass.ContextBackdrop',flags=Gio.ApplicationFlags.NON_UNIQUE)
def activate(app):
 w=Adw.ApplicationWindow(application=app,title='Glass50 context backdrop',default_width=1100,default_height=850)
 view=Adw.ToolbarView();view.add_top_bar(Adw.HeaderBar());a=Gtk.DrawingArea(hexpand=True,vexpand=True)
 def draw(area,c,width,height):
  c.set_source_rgb(1,1,1);c.paint()
  for x in range(0,width,18):c.set_source_rgb(0,0,0);c.rectangle(x,0,9,height);c.fill()
  c.set_source_rgb(.05,.4,.8);c.rectangle(0,height//2,width,70);c.fill()
  c.set_source_rgb(1,1,1);c.set_font_size(36);c.move_to(24,height//2+49);c.show_text('Glass50: clear text stays in front')
 a.set_draw_func(draw);view.set_content(a);w.set_content(view);w.present()
app.connect('activate',activate);app.run([])
