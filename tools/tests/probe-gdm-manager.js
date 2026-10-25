// SPDX-License-Identifier: MIT
// Independent style scene only; no GDM client, PAM or account authentication.
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import St from 'gi://St';import Gio from 'gi://Gio';import GLib from 'gi://GLib';import Clutter from 'gi://Clutter';import Shell from 'gi://Shell';
const root=GLib.getenv('HYALUNE_GDM_MANAGER_RENDER');const rows=[];
const wait=ms=>new Promise(resolve=>GLib.timeout_add(GLib.PRIORITY_DEFAULT,ms,()=>{resolve();return GLib.SOURCE_REMOVE;}));
function check(name,ok,details={}){rows.push({name,ok,...details});if(!ok)throw Error(name);}
function color(a){const c=a.get_theme_node().get_foreground_color();return [c.red,c.green,c.blue,c.alpha];}
async function capture(name){const file=Gio.File.new_for_path(`${root}/${name}.png`).create(Gio.FileCreateFlags.PRIVATE,null);const s=new Shell.Screenshot();await new Promise((resolve,reject)=>s.screenshot(false,file,(o,r)=>{try{o.screenshot_finish(r);file.close(null);resolve();}catch(e){reject(e);}}));}
export default class Preview extends Extension {
 enable(){GLib.timeout_add(GLib.PRIORITY_DEFAULT,2200,()=>{this.run().catch(e=>{rows.push({error:String(e)});this.finish(true);});return GLib.SOURCE_REMOVE;});}
 finish(failed=false){GLib.file_set_contents(`${root}/report.json`,JSON.stringify({rows,failed},null,2));if(failed)global.context.terminate_with_error(new Error('GDM render failed'));else global.context.terminate();}
 async run(){
  if(!root||GLib.getenv('GSETTINGS_BACKEND')!=='keyfile')throw Error('Private style scene only');
  const res=Gio.Resource.load(`${root}/candidate.gresource`);res._register();Main.overview.hide();
  const scene=new St.Widget({name:'lockDialogGroup',layout_manager:new Clutter.BinLayout(),width:1280,height:800});Main.uiGroup.add_child(scene);
  const dialog=new St.Widget({style_class:'login-dialog',layout_manager:new Clutter.BinLayout(),width:1280,height:800});scene.add_child(dialog);
  const surface=new St.BoxLayout({style_class:'login-dialog-user-selection-box',vertical:true,x_align:Clutter.ActorAlign.CENTER,y_align:Clutter.ActorAlign.CENTER});dialog.add_child(surface);
  const view=new St.ScrollView({style_class:'login-dialog-user-list-view'});surface.add_child(view);const list=new St.BoxLayout({style_class:'login-dialog-user-list',vertical:true,width:360});view.set_child(list);
  const user=new St.Button({style_class:'login-dialog-user-list-item',reactive:true,can_focus:true});list.add_child(user);const row=new St.BoxLayout({style_class:'user-widget horizontal'});user.set_child(row);row.add_child(new St.Icon({icon_name:'avatar-default-symbolic',icon_size:64}));const name=new St.Label({style_class:'user-widget-label',text:'Hyalune Preview',y_align:Clutter.ActorAlign.CENTER});row.add_child(name);
  const warning=new St.Label({style_class:'login-dialog-message-warning',text:'標準の警告色を保持'});surface.add_child(warning);
  const prompt=new St.BoxLayout({style_class:'login-dialog-prompt-layout',vertical:true,x_align:Clutter.ActorAlign.CENTER,y_align:Clutter.ActorAlign.CENTER,visible:false});dialog.add_child(prompt);
  const profile=new St.BoxLayout({style_class:'user-widget vertical',vertical:true});const authName=new St.Label({style_class:'user-widget-label',text:'Hyalune Preview'});profile.add_child(authName);prompt.add_child(profile);const entry=new St.Entry({style_class:'login-dialog-prompt-entry',hint_text:'パスワード',can_focus:true,width:360});entry.clutter_text.set_password_char('●');prompt.add_child(entry);
  const set=file=>St.ThemeContext.get_for_stage(global.stage).set_theme(new St.Theme({application_stylesheet:Gio.File.new_for_uri(`resource:///org/gnome/shell/theme/${file}`)}));
  set('gdm-high-contrast.css');user.add_style_pseudo_class('insensitive');await wait(250);const hcColor=color(name),hcAlpha=surface.get_theme_node().get_background_color().alpha;user.remove_style_pseudo_class('insensitive');
  set('gdm.css');user.grab_key_focus();await wait(600);
  check('custom GDM material alpha',Math.abs(surface.get_theme_node().get_background_color().alpha-120)<=1);
  check('primary username custom color',color(name).join()==='223,250,255,255',{color:color(name)});
  check('foreground actor opacity retained',surface.opacity===255&&name.opacity===255);
  check('username keyboard focus preserved',global.stage.key_focus===user);
  check('warning color not custom primary',color(warning).join()!=='223,250,255,255',{color:color(warning)});
  user.add_style_pseudo_class('hover');await wait(100);check('hover surface still clear',user.get_theme_node().get_background_color().alpha===0);user.remove_style_pseudo_class('hover');
  user.add_style_pseudo_class('insensitive');await wait(100);check('disabled username not forced to custom color',color(name).join()!=='223,250,255,255');user.remove_style_pseudo_class('insensitive');await capture('gdm-custom-list');
  surface.hide();prompt.show();entry.grab_key_focus();await wait(400);check('prompt custom alpha',Math.abs(prompt.get_theme_node().get_background_color().alpha-120)<=1);check('prompt primary label color',color(authName).join()==='223,250,255,255',{color:color(authName),profile_pseudo:profile.get_style_pseudo_class(),prompt_pseudo:prompt.get_style_pseudo_class()});check('password entry focus and foreground unchanged',global.stage.key_focus===entry.clutter_text&&entry.opacity===255);await capture('gdm-custom-prompt');
  set('gdm-high-contrast.css');surface.show();prompt.hide();user.grab_key_focus();await wait(400);check('High Contrast retains native surface',surface.get_theme_node().get_background_color().alpha===hcAlpha,{alpha:surface.get_theme_node().get_background_color().alpha,reference:hcAlpha});check('High Contrast does not inherit custom text',color(name).join()!=='223,250,255,255');await capture('gdm-high-contrast');
  scene.destroy();res._unregister();this.finish();
 }
 disable(){}
}
