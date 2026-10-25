// SPDX-License-Identifier: MIT
import GLib from 'gi://GLib';
import {assertEffectContext} from './runtime-context.js';

// Finite commits outside a paint cycle for the VM material preview.
export class WindowMaterialCommit {
    constructor(bindings, allowVmSession = false) {
        assertEffectContext(allowVmSession);
        this._bindings = bindings;
        this._ids = new WeakMap(); this._nextId = 0;
        this._signature = null; this._version = 0; this._completedVersion = 0;
        this._passVersion = 0; this._list = []; this._index = 0;
        this._idle = 0; this._paint = 0; this._delay = 0; this._destroyed = false;
        this._passes = 0; this._repaints = 0; this._error = null;
    }
    _id(object) {
        if (!this._ids.has(object)) this._ids.set(object, ++this._nextId);
        return this._ids.get(object);
    }
    update() {
        if (this._destroyed) return;
        const state = [...this._bindings.entries()].map(([actor, binding]) => [
            this._id(actor), this._id(binding), this._id(binding.blur._layer ?? binding),
            ...binding.anchor.get_position(), ...binding.anchor.get_size(), binding.corner,
            binding.source.actor.visible, binding.blur.enabled]);
        const signature = JSON.stringify(state);
        if (signature === this._signature) return;
        this._signature = signature; this._version++;
        if (!this._idle && !this._paint && !this._delay) this._begin();
    }
    _begin(confirm = false) {
        this._confirm = confirm; this._passRepaints = 0;
        this._passVersion = this._version;
        this._list = global.window_group.get_children().map(a => this._bindings.get(a)).filter(Boolean);
        this._index = 0;
        if (!this._list.length) {this._completedVersion = this._version; return;}
        this._passes++; this._schedule();
    }
    _schedule() {
        if (this._destroyed || this._idle || this._paint || this._delay) return;
        this._idle = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._idle = 0;
            try {this._step();} catch (e) {this._error = String(e); this.cancel();}
            return false;
        });
    }
    _step() {
        let binding;
        while (this._index < this._list.length) {
            const item = this._list[this._index++];
            if ([...this._bindings.values()].includes(item) && item.blur.enabled) {binding = item; break;}
        }
        if (!binding) {
            this._list = [];
            if (this._version !== this._passVersion) this._begin();
            else if (!this._confirm && this._passRepaints) this._begin(true);
            else this._completedVersion = this._passVersion;
            return;
        }
        // Let the lower offscreen finish a stage frame before refreshing the
        // next dependent capture. No periodic timer survives a static scene.
        this._paint = global.stage.connect('after-paint', () => {
            global.stage.disconnect(this._paint); this._paint = 0;
            // Nested 30fps caches may have trailing refreshes after this frame.
            // Wait two owned refresh intervals, then commit the next dependency.
            const mask = binding.blur._mask;
            if (!mask || ![...this._bindings.values()].includes(binding)) {this._schedule(); return;}
            const fps = mask.diagnostics.max_fps;
            this._delay = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2 * Math.ceil(1000 / (fps || 60)), () => {
                this._delay = 0; this._schedule(); return GLib.SOURCE_REMOVE;
            });
        });
        binding.source.actor.queue_redraw();
        binding.blur._capture.queue_redraw();
        binding.blur._blur.queue_repaint();
        binding.blur._mask._refreshGate.invalidate();
        binding.blur._mask.queue_repaint();
        this._repaints++; this._passRepaints++;
    }
    cancel() {
        if (this._idle) GLib.source_remove(this._idle);
        if (this._paint) global.stage.disconnect(this._paint);
        if (this._delay) GLib.source_remove(this._delay);
        this._idle = this._paint = this._delay = 0; this._list = [];
        this._signature = null; this._completedVersion = this._version;
    }
    get diagnostics() {
        return {pending: Boolean(this._idle || this._paint || this._delay), idle: Boolean(this._idle),
            paint_signal: Boolean(this._paint), delay: Boolean(this._delay), retained_bindings: this._list.length,
            requests: this._version, completed: this._completedVersion,
            passes: this._passes, repaints: this._repaints, error: this._error};
    }
    destroy() {this.cancel(); this._destroyed = true; this._bindings = null;}
}
