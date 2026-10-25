// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import {assertEffectContext} from '../glass50-blur@myglass.local/effects/runtime-context.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
let phase=0,tick=0,total=0,ext,wm,settings,files,back,mouse,keys,cycles=0,children=[],frames=[],events=[],signal=0,shotBusy=false,shots=0;
const ids=new WeakMap();let nextId=0;
function id(o){if(!o)return null;if(!ids.has(o))ids.set(o,++nextId);return ids.get(o);}
const root=GLib.getenv('GLASS50_PROBE_OUTPUT');
const save=()=>GLib.file_set_contents(`${root}/progress.json`,JSON.stringify({phase,cycles,events,frames},null,2));
export function init(){
 if((GLib.getenv('GLASS50_ISOLATED_PROBE')!=='1'&&GLib.getenv('GLASS50_MANAGED_PROBE')!=='1')||GLib.getenv('GSETTINGS_BACKEND')!=='keyfile')throw Error('Private only');
 if(GLib.getenv('GLASS50_MANAGED_PROBE')==='1'){
  const path=`${GLib.get_home_dir()}/.local/state/glass50/installer-material-v1/runtime.json`;
  const [,original]=GLib.file_get_contents(path);let rejected=0,legacy=false;
  const legacyPath=path.replace('/runtime.json','/t16-runtime.json');
  try{
   assertEffectContext(true);GLib.unlink(path);
   try{assertEffectContext(true);}catch(_){rejected++;}
   GLib.file_set_contents(path,JSON.stringify({format:1,target:'desktop',shell_major:49}));
   try{assertEffectContext(true);}catch(_){rejected++;}
   GLib.unlink(path);GLib.file_set_contents(legacyPath,JSON.stringify({format:1,target:'t16-trial',host:'unfixed',root:'/unfixed'}));
   assertEffectContext(true);legacy=true;
  }finally{GLib.unlink(legacyPath);GLib.file_set_contents(path,original);}
  assertEffectContext(true);events.push({event:'managed-context-guard',rejected,legacy});
 }
 GLib.timeout_add(GLib.PRIORITY_DEFAULT,25,()=>{try{step();}catch(e){events.push({error:String(e)});finish();return GLib.SOURCE_REMOVE;}return phase===99?GLib.SOURCE_REMOVE:GLib.SOURCE_CONTINUE;});
}
function sample(label){
 const a=files?.meta_window;const b=wm?._bindings.get(files);
 return {label,us:GLib.get_monotonic_time(),phase,cycle:cycles,binding:id(b),layer:id(b?.blur._layer),enabled:b?.blur.enabled??false,source:b?.source.actor.visible??false,opacity:files?.opacity,reason:wm?._reason,source_reason:b?.source.diagnostics.reason,commit:wm?._commit.diagnostics,
 layers_behind:[...(wm?._bindings??[])].every(([a,b])=>a.get_previous_sibling()===b.anchor&&b.anchor.get_previous_sibling()===b.blur._layer),paints:b?.blur._mask?.diagnostics?.refresh?.mask_telemetry?.content_paints,
 actors:global.window_group.get_children().filter(x=>typeof x.get_meta_window==='function').map(x=>({id:id(x),type:x.meta_window?.get_window_type(),app:x.meta_window?.get_wm_class(),mapped:x.mapped,opacity:x.opacity})),frame:a?[a.get_frame_rect().x,a.get_frame_rect().y]:null};
}
function shot(label){
 if(shotBusy||shots>=16)return;shotBusy=true;
 const name=`${String(shots++).padStart(2,'0')}-${label}`;
 const s=new Shell.Screenshot(),f=Gio.File.new_for_path(`${root}/${name}.png`).create(Gio.FileCreateFlags.PRIVATE,null);
 s.screenshot(false,f,(o,r)=>{try{o.screenshot_finish(r);}finally{f.close(null);shotBusy=false;}});
}
function finish(){
 phase=99;if(signal){global.stage.disconnect(signal);signal=0;}save();
 const d=ext?.diagnostics;settings?.set_boolean('window-material-enabled',false);settings?.set_boolean('effect-enabled',false);
 for(const c of children)c.force_exit();
 mouse?.run_dispose();keys?.run_dispose();
 const visibleFrames=frames.filter(f=>f.phase===5||f.phase===55||f.phase===6);
 const before=events.find(e=>e.event==='baseline');
 const [,metaBytes]=GLib.file_get_contents(`${root}/extension/metadata.json`);
 const expectedVersion=JSON.parse(new TextDecoder().decode(metaBytes)).version;
 const checks={
  runtime_version:d?.runtime_version===expectedVersion,
  menus_opened:events.filter(e=>e.event==='menu-open'&&e.actors.some(a=>a.type!==0)).length===4,
  four_cycles:cycles===4,
  recorded_frames:visibleFrames.length>=8,
  material_continuous:visibleFrames.every(f=>f.enabled&&f.source),
  binding_retained:visibleFrames.every(f=>f.binding===before?.binding),
  no_rebuild_for_popup:!events.some(e=>e.event==='stop'&&(e.phase===5||e.phase===6)),
  foreground_opacity:visibleFrames.every(f=>f.opacity===255),
  layers_behind_foreground:visibleFrames.every(f=>f.layers_behind),
  closed_layers_behind:events.filter(e=>e.event==='menu-closed').length===4&&events.filter(e=>e.event==='menu-closed').every(e=>e.layers_behind&&!e.actors.some(a=>a.type===9)),
  click_dismissed:events.filter(e=>e.event==='click-dismiss').length===2,
  settled_scene_updates:events.filter(e=>e.event==='menu-closed').every(e=>!e.commit.pending&&e.commit.requests===e.commit.completed&&e.commit.retained_bindings===0&&!e.commit.error),
  normal_restack:events.some(e=>e.event==='normal-restack'&&e.active===2&&e.changed),
  normal_return:events.some(e=>e.event==='normal-return'&&e.active===2),
  disable_cleanup:events.some(e=>e.event==='disable-cleanup'&&e.owned===0&&e.disabled),
  reenable:events.some(e=>e.event==='reenable'&&e.active===2),
  extension_cleanup:events.some(e=>e.event==='extension-cleanup'&&e.owned===0&&e.clean),
  no_errors:!events.some(e=>'error' in e),
 };
 if(GLib.getenv('GLASS50_MANAGED_PROBE')==='1')checks.managed_context_guard=events.some(e=>e.event==='managed-context-guard'&&e.rejected===2&&e.legacy);
 GLib.file_set_contents(`${root}/report.json`,JSON.stringify({events,frames,cycles,checks,final:d},null,2));
 Main.setThemeStylesheet(null);Main.loadTheme();global.context.terminate();
}
function step(){
 tick++;total++;if(tick%10===0)GLib.file_set_contents(`${root}/stage.json`,JSON.stringify({phase,tick,pointer:global.get_pointer(),overview:Main.overview.visible}));if(total>1300){events.push({error:'test timeout'});finish();return;}
 if(phase===0&&tick>=80){
  const iface=new Gio.Settings({schema_id:'org.gnome.desktop.interface'});iface.set_string('color-scheme','prefer-dark');
  const cfg=GLib.getenv('XDG_CONFIG_HOME');GLib.mkdir_with_parents(`${cfg}/gtk-4.0`,448);GLib.file_set_contents(`${cfg}/gtk-4.0/gtk.css`,`@import url("file://${root}/material.css");\n`);
  Main.setThemeStylesheet(`${root}/build/Glass50-Material-Preview/gnome-shell/gnome-shell.css`);Main.loadTheme();Main.overview.hide();phase=1;tick=0;
 }else if(phase===1){
  ext=Main.extensionManager.lookup('glass50-blur@myglass.local')?.stateObj;if(!ext)return;
  settings=ext.getSettings();settings.set_boolean('window-material-enabled',true);settings.set_boolean('effect-enabled',true);settings.set_boolean('diagnostics-enabled',true);wm=ext._windows;
  const stop=wm._stop.bind(wm);wm._stop=()=>{events.push({event:'stop',...sample('stop')});stop();};
  const drop=wm._drop.bind(wm);wm._drop=a=>{if(wm._bindings.has(a))events.push({event:'drop',who:id(a),...sample('drop')});drop(a);};
  children.push(Gio.Subprocess.new(['env',`HOME=${root}/home`,'ADW_DISABLE_PORTAL=1','python3',`${root}/backdrop.py`],Gio.SubprocessFlags.NONE));
  children.push(Gio.Subprocess.new(['env',`HOME=${root}/home`,'ADW_DISABLE_PORTAL=1','nautilus','--new-window',`${root}/home/Showcase`],Gio.SubprocessFlags.NONE));phase=2;tick=0;
 }else if(phase===2){
  const as=global.get_window_actors();files=as.find(a=>a.meta_window.get_wm_class()==='org.gnome.Nautilus');back=as.find(a=>a.meta_window.get_wm_class()==='local.myglass.ContextBackdrop');if(!files||!back)return;
  Main.overview.hide();back.meta_window.move_resize_frame(true,350,130,1100,850);files.meta_window.move_resize_frame(true,260,200,900,680);phase=3;tick=0;
 }else if(phase===3&&tick>=60){
  back.meta_window.move_frame(false,350,130);files.meta_window.move_frame(false,260,200);files.meta_window.activate(global.get_current_time());files.meta_window.raise();
  mouse=Clutter.get_default_backend().get_default_seat().create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);keys=Clutter.get_default_backend().get_default_seat().create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
  mouse.notify_absolute_motion(GLib.get_monotonic_time(),800,650);phase=4;tick=0;
 }else if(phase===4&&tick>=80){
  if(wm.diagnostics.active_windows!==2)throw Error('2 active windows required');
  events.push({event:'baseline',...sample('baseline')});shot('baseline');
  signal=global.stage.connect('after-paint',()=>{if(phase===5||phase===55||phase===6||phase===8){frames.push(sample('frame'));if(phase===5&&cycles===0&&frames.length<4)shot('transition');}});
  phase=45;tick=0;const f=files.meta_window.get_frame_rect();mouse.notify_absolute_motion(GLib.get_monotonic_time(),f.x+650,f.y+480);
 }else if(phase===45&&tick>=12){
  const f=files.meta_window.get_frame_rect(),p=global.get_pointer();events.push({event:'pointer',actual:p.slice(0,2),expected:[f.x+650,f.y+480]});
  if(Math.abs(p[0]-f.x-650)>3||Math.abs(p[1]-f.y-480)>3)throw Error('Pointer did not reach owned Files window');
  phase=5;tick=0;mouse.notify_button(GLib.get_monotonic_time(),3,Clutter.ButtonState.PRESSED);
  events.push({event:'right-press',...sample('press')});
 }else if(phase===5&&tick===2){mouse.notify_button(GLib.get_monotonic_time(),3,Clutter.ButtonState.RELEASED);}
 else if(phase===5&&tick>=36){events.push({event:'menu-open',...sample('menu-open')});shot('menu-open');
  if(cycles%2===0){mouse.notify_absolute_motion(GLib.get_monotonic_time(),...(cycles===0?[500,700]:[1550,1050]));phase=55;tick=0;}
  else{keys.notify_keyval(GLib.get_monotonic_time(),Clutter.KEY_Escape,Clutter.KeyState.PRESSED);phase=6;tick=0;}}
 else if(phase===55&&tick>=10){events.push({event:'click-dismiss',pointer:global.get_pointer().slice(0,2),cycle:cycles});mouse.notify_button(GLib.get_monotonic_time(),1,Clutter.ButtonState.PRESSED);phase=6;tick=0;}
 else if(phase===6&&tick===2){if(cycles%2===0)mouse.notify_button(GLib.get_monotonic_time(),1,Clutter.ButtonState.RELEASED);else keys.notify_keyval(GLib.get_monotonic_time(),Clutter.KEY_Escape,Clutter.KeyState.RELEASED);}
 else if(phase===6&&tick>=36){events.push({event:'menu-closed',...sample('closed')});shot('closed-'+cycles);cycles++;if(cycles>=4){phase=8;tick=0;}else{phase=45;tick=0;mouse.notify_absolute_motion(GLib.get_monotonic_time(),910,680);}}
 else if(phase===8&&tick>=40&&!shotBusy){
  events.push({event:'before-normal',binding:id(wm._bindings.get(files))});
  back.meta_window.activate(global.get_current_time());back.meta_window.raise();phase=9;tick=0;
 }else if(phase===9&&tick>=60){
  const prior=events.find(e=>e.event==='before-normal').binding;
  events.push({event:'normal-restack',active:wm.diagnostics.active_windows,changed:id(wm._bindings.get(files))!==prior});
  files.meta_window.activate(global.get_current_time());files.meta_window.raise();phase=10;tick=0;
 }else if(phase===10&&tick>=60){
  events.push({event:'normal-return',active:wm.diagnostics.active_windows});settings.set_boolean('window-material-enabled',false);phase=11;tick=0;
 }else if(phase===11&&tick>=12){
  events.push({event:'disable-cleanup',owned:global.window_group.get_children().filter(a=>a._glass50WindowOwner).length,disabled:!ext._windows});
  settings.set_boolean('window-material-enabled',true);wm=ext._windows;phase=12;tick=0;
 }else if(phase===12&&tick>=60){
  events.push({event:'reenable',active:wm.diagnostics.active_windows});Main.extensionManager.disableExtension('glass50-blur@myglass.local');phase=13;tick=0;
 }else if(phase===13&&tick>=40){
  const d=ext.diagnostics;events.push({event:'extension-cleanup',owned:global.window_group.get_children().filter(a=>a._glass50WindowOwner).length,clean:!d.window_material&&!d.pending_sync&&!d.diagnostic_timer});finish();
 }
}
