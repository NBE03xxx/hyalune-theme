// SPDX-License-Identifier: MIT
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import Gio from 'gi://Gio';import GLib from 'gi://GLib';import St from 'gi://St';import Shell from 'gi://Shell';
const root=GLib.getenv('HYALUNE_LIGHT_ROOT'),project=GLib.getenv('HYALUNE_LIGHT_PROJECT'),rows=[];
const wait=ms=>new Promise(r=>GLib.timeout_add(GLib.PRIORITY_DEFAULT,ms,()=>{r();return GLib.SOURCE_REMOVE;}));
function check(name,ok,details={}){rows.push({name,ok,...details});if(!ok)throw Error(name);}
function bg(a){const c=a.get_theme_node().get_background_color();return [c.red,c.green,c.blue,c.alpha];}
function fg(a){const c=a.get_theme_node().get_foreground_color();return [c.red,c.green,c.blue,c.alpha];}
function find(a,cls){if(a.has_style_class_name?.(cls))return a;for(const c of a.get_children()){const v=find(c,cls);if(v)return v;}return null;}
async function shot(name){const f=Gio.File.new_for_path(`${root}/${name}.png`).create(Gio.FileCreateFlags.PRIVATE,null);const s=new Shell.Screenshot();await new Promise((r,j)=>s.screenshot(false,f,(o,v)=>{try{o.screenshot_finish(v);f.close(null);r();}catch(e){j(e);}}));}
export default class Probe extends Extension{
 enable(){GLib.timeout_add(GLib.PRIORITY_DEFAULT,4500,()=>{this.run().catch(e=>{rows.push({error:String(e),stack:e.stack});this.finish(true);});return GLib.SOURCE_REMOVE;});}
 finish(failed=false){GLib.file_set_contents(`${root}/shell-result.json`,JSON.stringify({rows,failed},null,2));global.context.terminate();}
 async run(){
  if(!root||GLib.getenv('GLASS50_ISOLATED_PROBE')!=='1')throw Error('Private only');Main.overview.hide();
  const iface=new Gio.Settings({schema_id:'org.gnome.desktop.interface'}),a11y=new Gio.Settings({schema_id:'org.gnome.desktop.a11y.interface'});
  const ext=Main.extensionManager.lookup('glass50-blur@myglass.local').stateObj;check('Hyalune extension10 loaded',ext?.diagnostics.runtime_version===10);const prefs=ext.getSettings();prefs.set_boolean('effect-enabled',true);prefs.set_boolean('window-material-enabled',true);
  const menu=Main.panel.statusArea.quickSettings.menu;
  a11y.set_boolean('high-contrast',true);Main.setThemeStylesheet(null);Main.loadTheme();await wait(450);menu.open();await wait(400);let face=find(menu.actor,'quick-settings');const hc={bg:bg(face),fg:fg(face)};menu.close();
  Main.setThemeStylesheet(`${project}/build/Hyalune-Light/gnome-shell/gnome-shell.css`);Main.loadTheme();await wait(600);menu.open();await wait(500);face=find(menu.actor,'quick-settings');check('High Contrast native surface and foreground restored',bg(face).join()===hc.bg.join()&&fg(face).join()===hc.fg.join(),{reference:hc,current:{bg:bg(face),fg:fg(face)}});check('High Contrast effects stopped',ext.diagnostics.high_contrast_fallback&&!ext.diagnostics.blur?.active&&ext.diagnostics.window_material.active_windows===0);await shot('light-hc');menu.close();
  a11y.set_boolean('high-contrast',false);await wait(700);menu.open();await wait(1000);face=find(menu.actor,'quick-settings');check('Light restored after High Contrast',bg(face)[3]===199&&!ext.diagnostics.high_contrast_fallback,{diag:ext.diagnostics});check('Quick Settings Light blur active',ext.diagnostics.blur?.active,{diag:ext.diagnostics});check('Light blur brightness is neutral',ext._blur._blur._blur.brightness===1,{brightness:ext._blur._blur._blur.brightness});menu.close();await wait(700);
  const actors=global.get_window_actors().filter(a=>a.meta_window.get_title()?.includes('Hyalune Light'));
  check('native windows keep foreground opacity',actors.length>=1&&actors.every(a=>a.opacity===255));check('Light window blur active',ext.diagnostics.window_material.active_windows>=1,{diag:ext.diagnostics.window_material});check('window blur layers remain below foreground',Array.from(ext._windows._bindings).every(([a,b])=>a.get_previous_sibling()===b.anchor&&b.anchor.get_previous_sibling()===b.blur._layer));check('Light window blur brightness neutral',Array.from(ext._windows._bindings.values()).every(b=>b.blur._brightness===1));
  for(const a of actors){if(a.meta_window.get_title().includes('GTK3'))a.meta_window.move_frame(false,50,130);else a.meta_window.move_frame(false,720,160);}await wait(500);await shot('light-blur');
  a11y.set_string('reduced-motion','reduce');menu.open();await wait(700);check('Reduced Motion stops both effects',!ext.diagnostics.blur?.active&&ext.diagnostics.window_material.active_windows===0,{diag:ext.diagnostics});menu.close();a11y.set_string('reduced-motion','no-preference');await wait(600);check('effects resume when Reduced Motion clears',ext.diagnostics.window_material.active_windows>=1);
  prefs.set_boolean('effect-enabled',false);prefs.set_boolean('window-material-enabled',false);await wait(400);a11y.set_boolean('high-contrast',true);await wait(600);check('HC fallback works with both blur preferences off',ext.diagnostics.high_contrast_fallback);a11y.set_boolean('high-contrast',false);await wait(600);check('HC off restores Light with effects off',!ext.diagnostics.high_contrast_fallback&&!ext.diagnostics.blur?.active&&ext.diagnostics.window_material===null);
  iface.set_string('color-scheme','prefer-dark');Main.setThemeStylesheet(`${project}/build/Glass50-Material-Preview/gnome-shell/gnome-shell.css`);Main.loadTheme();prefs.set_boolean('effect-enabled',true);prefs.set_boolean('window-material-enabled',true);await wait(800);menu.open();await wait(700);check('Dark Quick Settings brightness preserved',Math.abs(ext._blur._blur._blur.brightness-.85)<0.000001);menu.close();await wait(500);check('Dark window brightness preserved',Array.from(ext._windows._bindings.values()).every(b=>b.blur._brightness===.85));
  iface.set_string('color-scheme','prefer-light');Main.setThemeStylesheet(`${project}/build/Hyalune-Light/gnome-shell/gnome-shell.css`);Main.loadTheme();await wait(700);check('Dark to Light window brightness refreshes',ext._windows._bindings.size>=1&&Array.from(ext._windows._bindings.values()).every(b=>b.blur._brightness===1));
  for(let i=0;i<3;i++){prefs.set_boolean('window-material-enabled',false);await wait(120);prefs.set_boolean('window-material-enabled',true);await wait(400);}check('repeat enable disable keeps foreground opaque',actors.every(a=>a.opacity===255)&&ext.diagnostics.window_material.active_windows>=1);prefs.set_boolean('window-material-enabled',false);prefs.set_boolean('effect-enabled',false);await wait(300);check('effect disable removes generated window layers',!global.window_group.get_children().some(a=>a._glass50WindowOwner));
  this.finish();
 }
 disable(){}
}
