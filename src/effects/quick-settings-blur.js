// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Graphene from 'gi://Graphene';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {assertEffectContext} from './runtime-context.js';
import {RoundedBackgroundBlur} from './rounded-background-blur.js';

const BLUR_RADIUS = 12;

// GNOME 50 adapter restricted to the verified VM; explicit normal-session preview required.
// The native box/grid/input hierarchy and CSS remain owned by Shell.
export class QuickSettingsBlur {
    constructor(menu, source, {resolutionScale = 0.5, maxRefreshRate = 30, allowVmSession = false, instrument = false, clipSource = false} = {}) {
        assertEffectContext(allowVmSession);
        if (!menu.box || !menu._boxPointer || !menu.actor ||
            menu._boxPointer.get_parent() !== menu.actor || source.contains(menu.actor))
            throw new Error('Unsupported Quick Settings structure');
        this._instrument = Boolean(instrument);
        this._menu = menu;
        this._source = source;
        // Opt-in only for the caller's exclusively owned backdrop subtree.
        this._clipSource = Boolean(clipSource);
        this._sourceClip = this._originalSourceClip = null;
        this._sourceDestroyed = false;
        this._resolutionScale = resolutionScale;
        this._maxRefreshRate = maxRefreshRate;
        this._interface = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
        this._a11y = new Gio.Settings({schema_id: 'org.gnome.desktop.a11y.interface'});
        this._connections = [];
        this._submenuConnections = new Map();
        this._anchor = this._blur = null;
        this._requested = false;
        this._destroyed = false;
        this._reason = 'disabled';
        this._error = null;
        this._pending = 0;
        const watch = (object, signal, callback = () => this._queueSync()) =>
            this._connections.push([object, object.connect(signal, callback)]);
        watch(menu, 'open-state-changed');
        for (const actor of [menu.box, menu._boxPointer, menu.actor]) {
            watch(actor, 'notify::allocation');
            watch(actor, 'destroy', () => this.destroy());
        }
        for (const property of ['scale-x', 'scale-y', 'translation-x', 'translation-y', 'opacity'])
            watch(menu._boxPointer, `notify::${property}`);
        watch(menu.box, 'style-changed');
        const watchSubmenu = actor => {
            this._submenuConnections.set(actor, actor.connect('notify::visible', () => this._queueSync()));
        };
        for (const actor of menu._overlay.get_children()) watchSubmenu(actor);
        watch(menu._overlay, 'child-added', (_overlay, actor) => watchSubmenu(actor));
        watch(menu._overlay, 'child-removed', (_overlay, actor) => {
            const id = this._submenuConnections.get(actor);
            if (id) actor.disconnect(id);
            this._submenuConnections.delete(actor);
            this._queueSync();
        });
        watch(this._interface, 'changed::color-scheme');
        watch(this._a11y, 'changed::high-contrast');
        watch(this._a11y, 'changed::reduced-motion');
        watch(Main.overview, 'showing');
        watch(Main.overview, 'hidden');
        watch(Main.sessionMode, 'updated');
        watch(Main.layoutManager, 'monitors-changed');
        watch(source, 'notify::visible');
        watch(source, 'notify::allocation');
        watch(source, 'destroy', () => {
            this._sourceDestroyed = true;
            this.destroy();
        });
    }

    setEnabled(enabled) {
        if (this._destroyed)
            throw new Error('Quick Settings blur has been destroyed');
        this._requested = Boolean(enabled);
        this._sync();
    }

    _fallbackReason() {
        const pointer = this._menu._boxPointer;
        if (!this._requested) return 'disabled';
        if (!this._menu.isOpen) return 'menu-closed';
        if (this._a11y.get_boolean('high-contrast')) return 'high-contrast';
        if (this._interface.get_string('color-scheme') !== 'prefer-dark') return 'not-dark';
        if (this._a11y.get_string('reduced-motion') !== 'no-preference') return 'reduced-motion';
        if (this._menu._overlay.get_children().some(actor => actor.visible)) return 'submenu';
        if (Main.overview.visible || Main.sessionMode.isLocked) return 'overview-or-locked';
        if (pointer.scale_x !== 1 || pointer.scale_y !== 1 || pointer.translation_x !== 0 ||
            pointer.translation_y !== 0 || pointer.opacity !== 255) return 'transition';
        if (pointer.get_parent() !== this._menu.actor || this._source.contains(this._menu.actor))
            return 'structure';
        if (!this._source.visible) return 'background-unavailable';
        if (this._menu.box.get_resource_scale() !== 1) return 'resource-scale';
        return null;
    }

    _queueSync() {
        if (this._destroyed || this._pending) return;
        // Never mutate the fixed-layout child list during native allocation/style traversal.
        this._pending = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._pending = 0;
            this._sync();
            return GLib.SOURCE_REMOVE;
        });
    }

    _sync() {
        if (this._destroyed) return;
        // Diagnostics describe this sync, rather than an earlier transient failure.
        this._error = null;
        let reason = this._fallbackReason();
        const box = this._menu.box;
        const [width, height] = box.get_transformed_size();
        const point = box.apply_relative_transform_to_point(this._menu.actor, new Graphene.Point3D());
        const [x, y] = [point.x, point.y];
        if (!reason && (![x, y, width, height].every(Number.isInteger) || width <= 0 || height <= 0))
            reason = 'geometry';
        if (reason) {
            this._reason = reason;
            this._drop();
            return;
        }
        try {
            let clip = null;
            if (this._clipSource) {
                const origin = actor => actor.apply_relative_transform_to_point(global.stage, new Graphene.Point3D());
                const a = origin(box), b = origin(this._source);
                const padding = BLUR_RADIUS * 2;
                clip = [a.x - b.x - padding, a.y - b.y - padding,
                    width + padding * 2, height + padding * 2];
                // Stage coordinates can be fractional during native transitions.
                // Use the existing geometry fallback before allocating capture actors.
                if (!clip.every(Number.isInteger)) {
                    this._reason = 'geometry';
                    this._drop();
                    return;
                }
            }
            if (!this._anchor) {
                this._anchor = new Clutter.Actor({name: 'glass50-quick-settings-anchor', reactive: false});
                this._menu.actor.insert_child_below(this._anchor, this._menu._boxPointer);
                this._blur = new RoundedBackgroundBlur(this._source, this._anchor,
                    {radius: BLUR_RADIUS, resolutionScale: this._resolutionScale, stageSource: true, maxRefreshRate: this._maxRefreshRate, instrument: this._instrument,
                        cornerRadius: box.get_theme_node().get_border_radius(St.Corner.TOPLEFT)});
            }
            this._anchor.set_position(x, y);
            this._anchor.set_size(width, height);
            if (clip) {
                if (!this._sourceClip)
                    this._originalSourceClip = this._source.has_clip ? this._source.get_clip() : null;
                if (!this._sourceClip || clip.some((value, i) => value !== this._sourceClip[i]))
                    this._source.set_clip(...clip);
                this._sourceClip = clip;
            }
            this._blur.setEnabled(true);
            this._reason = this._blur.enabled ? 'active' : 'unsupported-source';
            if (!this._blur.enabled) this._drop();
        } catch (error) {
            this._error = String(error);
            this._reason = 'error';
            this._drop();
        }
    }

    _drop() {
        this._blur?.destroy();
        this._blur = null;
        this._anchor?.destroy();
        this._anchor = null;
        if (this._sourceClip && !this._sourceDestroyed) {
            if (this._originalSourceClip) this._source.set_clip(...this._originalSourceClip);
            else this._source.remove_clip();
        }
        this._sourceClip = this._originalSourceClip = null;
    }

    get diagnostics() {
        return {requested: this._requested, active: this._blur?.enabled ?? false,
            source_clipping_requested: this._clipSource, source_clip: this._sourceClip ? [...this._sourceClip] : null,
            reason: this._reason, error: this._error, connections: this._connections.length,
            submenu_connections: this._submenuConnections.size, pending_sync: Boolean(this._pending),
            bounds: this._anchor ? [...this._anchor.get_position(), ...this._anchor.get_size()] : null,
            blur: this._blur?.diagnostics ?? null};
    }

    destroy() {
        if (this._destroyed) return;
        this._destroyed = true;
        if (this._pending) GLib.source_remove(this._pending);
        this._pending = 0;
        for (const [object, id] of this._connections) object.disconnect(id);
        this._connections = [];
        for (const [actor, id] of this._submenuConnections) actor.disconnect(id);
        this._submenuConnections.clear();
        this._drop();
        this._menu = this._source = null;
        this._reason = 'destroyed';
    }
}
