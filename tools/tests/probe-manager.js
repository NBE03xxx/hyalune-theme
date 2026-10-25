// SPDX-License-Identifier: MIT
// Private VM bus only: screenshot and virtual keyboard, never normal Shell.
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import GLib from 'gi://GLib';import Gio from 'gi://Gio';import Shell from 'gi://Shell';import Clutter from 'gi://Clutter';
export default class Probe extends Extension {
 enable(){
  this.root=GLib.getenv('HYALUNE_MANAGER_PROBE');
  if(!this.root||GLib.getenv('GSETTINGS_BACKEND')!=='keyfile')throw Error('Private probe only');
  Main.overview.hide();this.keys=Clutter.get_default_backend().get_default_seat().create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
  this.timer=GLib.timeout_add(GLib.PRIORITY_DEFAULT,150,()=>{this.poll();return GLib.SOURCE_CONTINUE;});
 }
 poll(){
  for(const name of ['initial','details','narrow','confirmation','target-popup','gdm-editor']){
   const request=`${this.root}/${name}.request`;
   if(GLib.file_test(request,GLib.FileTest.EXISTS)&&!this.pending){
    GLib.unlink(request);this.pending=true;
    const f=Gio.File.new_for_path(`${this.root}/${name}.png`).replace(null,false,Gio.FileCreateFlags.PRIVATE,null);
    new Shell.Screenshot().screenshot(false,f,(o,r)=>{try{o.screenshot_finish(r);f.close(null);GLib.file_set_contents(`${this.root}/${name}.done`,'ok');}catch(e){GLib.file_set_contents(`${this.root}/capture-error`,String(e));}this.pending=false;});
   }
  }
  if(GLib.file_test(`${this.root}/space.request`,GLib.FileTest.EXISTS)){
   GLib.unlink(`${this.root}/space.request`);const t=GLib.get_monotonic_time();this.keys.notify_keyval(t,Clutter.KEY_space,Clutter.KeyState.PRESSED);this.keys.notify_keyval(t,Clutter.KEY_space,Clutter.KeyState.RELEASED);
  }
  if(GLib.file_test(`${this.root}/escape.request`,GLib.FileTest.EXISTS)){
   GLib.unlink(`${this.root}/escape.request`);const t=GLib.get_monotonic_time();this.keys.notify_keyval(t,Clutter.KEY_Escape,Clutter.KeyState.PRESSED);this.keys.notify_keyval(t,Clutter.KEY_Escape,Clutter.KeyState.RELEASED);
  }
 }
 disable(){if(this.timer)GLib.source_remove(this.timer);this.keys?.run_dispose();}
}
