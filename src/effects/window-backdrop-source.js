// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Graphene from 'gi://Graphene';
import {assertEffectContext} from './runtime-context.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Private-headless prototype: compose the background and visible native windows
// without cloning the zero-size WindowGroup or any Shell menu/foreground.
export class WindowBackdropSource {
    constructor({allowVmSession = false, belowWindow = null, stableOrder = false} = {}) {
        assertEffectContext(allowVmSession);
        this._group = global.window_group;
        this._belowWindow = belowWindow;
        this._stableOrder = stableOrder;
        this._entries = new Map();
        this._connections = [];
        this._pending = 0;
        this._destroyed = false;
        this._reason = 'initializing';
        // A mapped, zero-opacity actor has a real allocation. Clutter.Clone
        // overrides the source paint opacity when painting this owned subtree.
        this.actor = new Clutter.Actor({name:'glass50-window-backdrop-source', opacity:0,
            width:global.stage.width, height:global.stage.height, reactive:false, clip_to_allocation:true});
        Main.uiGroup.insert_child_below(this.actor,this._group);
        const watch = (obj,signal,callback) => this._connections.push([obj,obj.connect(signal,callback)]);
        watch(this._group,'child-added',(_group,child)=>{this._watch(child);this._queue();});
        watch(this._group,'child-removed',(_group,child)=>{this._remove(child);this._queue();});
        watch(global.display,'restacked',()=>this._queue());
        watch(global.workspace_manager,'active-workspace-changed',()=>this._queue());
        watch(Main.layoutManager,'monitors-changed',()=>this._queue());
        for (const child of this._group.get_children()) this._watch(child);
        this._sync();
    }
    _watch(child) {
        if (this._entries.has(child)) return;
        const entry = {clone:null,signals:[]};
        for (const prop of ['allocation','visible','mapped','opacity','scale-x','scale-y','translation-x','translation-y'])
            entry.signals.push(child.connect(`notify::${prop}`,()=>this._queue()));
        this._entries.set(child,entry);
    }
    _remove(child) {
        const entry=this._entries.get(child);
        if (!entry) return;
        for (const id of entry.signals) child.disconnect(id);
        entry.clone?.destroy();
        this._entries.delete(child);
    }
    _queue() {
        if (this._destroyed || this._pending) return;
        this._pending=GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE,()=>{
            this._pending=0;this._sync();return GLib.SOURCE_REMOVE;
        });
    }
    _sync() {
        if (this._destroyed) return;
        this.actor.set_size(global.stage.width,global.stage.height);
        let supported=Main.layoutManager.monitors.length===1 && this.actor.get_resource_scale()===1;
        let previous=null;
        for (const child of this._group.get_children()) {
            const entry=this._entries.get(child);
            if (child === this._belowWindow) break;
            // The owner of a window backdrop is explicit. Never capture our
            // target's own layer, and only clone earlier windows' layers.
            const owner = child._glass50WindowOwner;
            if (child._glass50WindowAnchor || owner === this._belowWindow && owner) {
                entry.clone?.hide();
                continue;
            }
            const isBackground=child===Main.layoutManager._backgroundGroup;
            const isOwnedBackdrop=owner && typeof owner.get_meta_window==='function';
            if (!isBackground && !isOwnedBackdrop && typeof child.get_meta_window!=='function') {
                if (child.visible) supported=false;
                continue;
            }
            const [width,height]=child.get_size();
            const point=child.apply_relative_transform_to_point(Main.uiGroup,new Graphene.Point3D());
            const valid=[point.x,point.y,width,height].every(Number.isInteger) && width>0 && height>0 &&
                child.scale_x===1 && child.scale_y===1 && child.translation_x===0 && child.translation_y===0 &&
                child.rotation_angle_x===0 && child.rotation_angle_y===0 && child.rotation_angle_z===0;
            if (child.visible && !valid) supported=false;
            if (!valid) {entry.clone?.hide();continue;}
            if (!entry.clone) {
                entry.clone=new Clutter.Clone({source:child,reactive:false});
                this.actor.add_child(entry.clone);
            }
            entry.clone.set_position(point.x,point.y);
            entry.clone.set_size(width,height);
            entry.clone.opacity=child.opacity;
            const native = isOwnedBackdrop ? owner.get_meta_window() : child.get_meta_window?.();
            entry.clone.visible=child.visible && child.mapped && (!native || native.is_on_all_workspaces() ||
                native.get_workspace() === global.workspace_manager.get_active_workspace());
            if (!this._stableOrder || !entry.ordered || entry.clone.get_previous_sibling() !== previous) {
                this.actor.set_child_above_sibling(entry.clone,previous); entry.ordered = true;
            }
            previous=entry.clone;
        }
        this._reason=supported?'ready':'unsupported-scene';
        // Entries above a per-window cutoff must not retain old visible clones
        // when the native stacking order changes.
        if (this._belowWindow) {
            const children=this._group.get_children(), index=children.indexOf(this._belowWindow);
            for (const child of children.slice(index < 0 ? 0 : index))
                this._entries.get(child)?.clone?.hide();
            if (index < 0) supported=false;
        }
        this.actor.visible=supported;
    }
    get diagnostics() {
        return {reason:this._reason,entries:this._entries.size,
            clones:[...this._entries.values()].filter(e=>e.clone).length,
            connections:this._connections.length+[...this._entries.values()].reduce((n,e)=>n+e.signals.length,0),
            pending_sync:Boolean(this._pending),size:this.actor?.get_size()??null};
    }
    destroy() {
        if (this._destroyed) return;
        this._destroyed=true;
        if (this._pending) GLib.source_remove(this._pending);
        this._pending=0;
        for (const [obj,id] of this._connections) obj.disconnect(id);
        this._connections=[];
        for (const child of [...this._entries.keys()]) this._remove(child);
        this.actor.destroy();this.actor=null;this._reason='destroyed';
        this._belowWindow=null;
    }
}
