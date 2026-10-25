// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';

// Cache only the owned backdrop, using the existing outer offscreen effect.
// One trailing repaint commits final damage; static scenes have no timer.
export class RefreshGate {
    constructor(repaint, {instrument = false} = {}) {
        this._repaint = repaint;
        this._telemetry = instrument ? {paint_calls: 0, incoming_dirty: 0, bypass: 0,
            invalidations: 0, trailing_callbacks: 0} : null;
        this._maxFps = 0;
        this._intervalUs = 0;
        this._lastUpdateUs = 0;
        this._pending = 0;
        this._dirty = true;
        this._disposed = false;
        this._updates = this._reused = 0;
    }

    setRefreshRate(fps) {
        if (![0, 15, 30, 60].includes(fps) || this._disposed)
            throw new Error('Invalid Glass50 backdrop refresh rate');
        this._maxFps = fps;
        this._intervalUs = fps ? 1e6 / fps : 0;
        this.invalidate();
        this._repaint();
    }

    invalidate() {
        if (this._telemetry) this._telemetry.invalidations++;
        this._cancelPending();
        this._lastUpdateUs = 0;
        this._dirty = true;
    }

    adjust(flags) {
        if (this._disposed) return flags;
        if (this._telemetry) {
            this._telemetry.paint_calls++;
            if (flags & Clutter.EffectPaintFlags.ACTOR_DIRTY) this._telemetry.incoming_dirty++;
            if (flags & Clutter.EffectPaintFlags.BYPASS_EFFECT) this._telemetry.bypass++;
        }
        if (flags & Clutter.EffectPaintFlags.BYPASS_EFFECT) {
            this.invalidate();
            return flags;
        }
        const now = GLib.get_monotonic_time();
        this._dirty ||= Boolean(flags & Clutter.EffectPaintFlags.ACTOR_DIRTY);
        if (!this._intervalUs || (this._dirty && now - this._lastUpdateUs >= this._intervalUs)) {
            if (this._dirty) {
                flags |= Clutter.EffectPaintFlags.ACTOR_DIRTY;
                this._updates++;
                this._lastUpdateUs = now;
                this._dirty = false;
                this._cancelPending();
            }
        } else {
            flags &= ~Clutter.EffectPaintFlags.ACTOR_DIRTY;
            this._reused++;
            if (this._dirty && !this._pending) {
                const delay = Math.max(1, Math.ceil((this._intervalUs - (now - this._lastUpdateUs)) / 1000));
                this._pending = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
                    this._pending = 0;
                    if (this._telemetry) this._telemetry.trailing_callbacks++;
                    if (!this._disposed) this._repaint();
                    return GLib.SOURCE_REMOVE;
                });
            }
        }
        return flags;
    }

    _cancelPending() {
        if (this._pending) GLib.source_remove(this._pending);
        this._pending = 0;
    }

    get diagnostics() {
        return {telemetry: this._telemetry ? {...this._telemetry} : null, max_fps: this._maxFps, updates: this._updates, reused: this._reused,
            dirty: this._dirty, pending_refresh: Boolean(this._pending), disposed: this._disposed};
    }

    destroy() {
        this._disposed = true;
        this._cancelPending();
        this._dirty = false;
        this._repaint = null;
    }
}
