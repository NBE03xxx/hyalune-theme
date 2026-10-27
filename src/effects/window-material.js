// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import {WindowMaterialCommit} from './window-material-commit.js';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {assertEffectContext} from './runtime-context.js';
import {WindowBackdropSource} from './window-backdrop-source.js';
import {RoundedBackgroundBlur} from './rounded-background-blur.js';

const themeIsMaterial = () => ['Hyalune','Glass50-Material-Preview','Hyalune-Light'].some(name =>
    (Main.getThemeStylesheet()?.get_path() ?? '').endsWith(`/${name}/gnome-shell/gnome-shell.css`));

export class WindowMaterial {
    constructor({allowVmSession = false, instrument = false, appFilter = null} = {}) {
        assertEffectContext(allowVmSession);
        this._allowVmSession = allowVmSession;
        this._instrument = instrument;
        this._appFilter = appFilter;
        this._bindings = new Map();
        this._commit = new WindowMaterialCommit(this._bindings, allowVmSession);
        this._watches = new Map();
        this._connections = [];
        this._pending = 0;
        this._destroyed = false;
        this._order = [];
        this._nativeOrder = [];
        this._reason = 'initializing';
        this._interface = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
        this._a11y = new Gio.Settings({schema_id: 'org.gnome.desktop.a11y.interface'});
        const watch = (object, signal) => this._connections.push([object, object.connect(signal, () => this._queue())]);
        watch(global.display, 'window-created');
        this._connections.push([global.display, global.display.connect('restacked', () => {
            // Mutter moves native actors past our non-native siblings even when
            // their relative order is unchanged (for example a popup closing).
            // Restore the owned layers before the next paint, without dropping
            // their textures or allowing them to cover the foreground.
            let repaired = false;
            for (const [actor, binding] of this._bindings)
                repaired = this._placeBehind(actor, binding) || repaired;
            if (repaired) this._commit.cancel();
            this._queue();
        })]);
        watch(global.workspace_manager, 'active-workspace-changed');
        watch(Main.overview, 'showing');watch(Main.overview, 'hidden');
        watch(Main.sessionMode, 'updated');watch(Main.layoutManager, 'monitors-changed');
        watch(this._interface, 'changed::color-scheme');watch(this._a11y, 'changed::high-contrast');
        watch(this._a11y, 'changed::reduced-motion');
        watch(St.ThemeContext.get_for_stage(global.stage), 'changed');
        this._queue();
    }

    _queue() {
        if (this._destroyed || this._pending) return;
        this._pending = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
            this._pending = 0;this._sync();return GLib.SOURCE_REMOVE;
        });
    }

    _eligible(actor) {
        const window = actor.get_meta_window();
        if (!window) return false;
        if (window.get_window_type() !== Meta.WindowType.NORMAL || window.is_fullscreen()) return false;
        const gtkApp = window.get_gtk_application_id?.();
        const app = gtkApp || window.get_wm_class?.() || '';
        if (this._appFilter) return this._appFilter(app, window);
        return Boolean(gtkApp) || /^(org\.gnome\.|local\.myglass\.|nm-connection-editor|gnome-terminal|Gnome-terminal)/.test(app);
    }

    _fallback() {
        if (!themeIsMaterial()) return 'theme';
        if (Main.overview.visible || Main.sessionMode.isLocked) return 'overview-or-locked';
        if (Main.layoutManager.monitors.length !== 1 || global.stage.get_resource_scale() !== 1) return 'monitor-scale';
        if (!['prefer-dark','prefer-light'].includes(this._interface.get_string('color-scheme'))) return 'not-dark';
        if (this._a11y.get_boolean('high-contrast')) return 'high-contrast';
        if (this._a11y.get_string('reduced-motion') !== 'no-preference') return 'reduced-motion';
        return null;
    }

    _watch(actor) {
        if (this._watches.has(actor)) return;
        const ids = [];
        for (const property of ['allocation', 'visible', 'mapped', 'opacity', 'scale-x', 'scale-y', 'translation-x', 'translation-y'])
            ids.push(actor.connect(`notify::${property}`, () => this._queue()));
        ids.push(actor.connect('destroy', () => {
            this._drop(actor);this._watches.delete(actor);this._queue();
        }));
        this._watches.set(actor, ids);
    }

    _drop(actor) {
        const binding = this._bindings.get(actor);
        if (!binding) return;
        this._bindings.delete(actor);
        binding.blur.destroy();binding.anchor.destroy();binding.source.destroy();
    }

    _stop() {
        this._commit.cancel();
        // Drop upper captures before their lower sources. No recursive graph
        // survives a restack; recreate in the new bottom-to-top native order.
        for (const actor of [...this._bindings.keys()].reverse()) this._drop(actor);
    }

    _placeBehind(actor, binding) {
        const parent = actor.get_parent();
        if (parent !== global.window_group || binding.anchor.get_parent() !== parent) return false;
        let repaired = false;
        if (actor.get_previous_sibling() !== binding.anchor) {
            parent.set_child_below_sibling(binding.anchor, actor);
            repaired = true;
        }
        const layer = binding.blur._layer;
        if (layer?.get_parent() === parent && binding.anchor.get_previous_sibling() !== layer) {
            parent.set_child_below_sibling(layer, binding.anchor);
            repaired = true;
        }
        return repaired;
    }

    _sync() {
        if (this._destroyed) return;
        const actors = global.window_group.get_children().filter(a => typeof a.get_meta_window === 'function');
        const sceneChanged = actors.length !== this._nativeOrder.length ||
            actors.some((actor, index) => actor !== this._nativeOrder[index]);
        this._nativeOrder = actors;
        const alive = new Set(actors);
        for (const [actor, ids] of this._watches) {
            if (alive.has(actor)) continue;
            this._drop(actor);
            for (const id of ids) actor.disconnect(id);
            this._watches.delete(actor);
        }
        for (const actor of actors) this._watch(actor);
        const reason = this._fallback();
        const scheme = this._interface.get_string('color-scheme');
        if (this._scheme !== scheme) {this._stop();this._scheme = scheme;}
        // Popup menus have no material binding and cannot change the dependency
        // order between glass windows. Keep existing captures while they map.
        const order = actors.filter(actor => this._eligible(actor));
        const reordered = order.length !== this._order.length || order.some((a, i) => a !== this._order[i]);
        if (reason || reordered) this._stop();
        // Refresh finite offscreen caches after popup map/unmap as well.
        // Keeping a binding does not imply its captured pixels are current.
        else if (sceneChanged) this._commit.cancel();
        this._order = order;
        this._reason = reason ?? 'ready';
        if (reason) return;
        for (const actor of actors) {
            const window = actor.get_meta_window();
            if (!window || !actor.get_parent()) {this._drop(actor);continue;}
            const frame = window.get_frame_rect();
            const stable = actor.visible && actor.mapped && actor.opacity === 255 && !window.minimized &&
                (window.is_on_all_workspaces() || window.get_workspace() === global.workspace_manager.get_active_workspace()) &&
                actor.scale_x === 1 && actor.scale_y === 1 && actor.translation_x === 0 && actor.translation_y === 0 &&
                [frame.x, frame.y, frame.width, frame.height].every(Number.isInteger) && frame.width > 0 && frame.height > 0;
            if (!this._eligible(actor) || !stable) {this._drop(actor);continue;}
            try {
                let binding = this._bindings.get(actor);
                const corner = window.maximized_horizontally || window.maximized_vertically ? 0 : 16;
                if (binding && binding.corner !== corner) {this._drop(actor);binding = null;}
                if (!binding) {
                    const source = new WindowBackdropSource({allowVmSession: this._allowVmSession, belowWindow: actor, stableOrder: true});
                    const anchor = new Clutter.Actor({name: 'glass50-window-material-anchor', reactive: false});
                    anchor._glass50WindowOwner = actor;anchor._glass50WindowAnchor = true;
                    global.window_group.insert_child_below(anchor, actor);
                    const blur = new RoundedBackgroundBlur(source.actor, anchor, {radius: 24, cornerRadius: corner,
                        brightness: this._interface.get_string('color-scheme') === 'prefer-light' ? 1.0 : 0.85, resolutionScale: 0.5, stageSource: true, maxRefreshRate: 30, instrument: this._instrument});
                    binding = {source, anchor, blur, corner};this._bindings.set(actor, binding);
                    // A newly inserted native sibling is allocated on the next
                    // stage frame. Retry once after allocation rather than
                    // leaving the primitive's scale fallback disabled forever.
                    this._queue();
                }
                binding.source.actor.set_clip(frame.x - 48, frame.y - 48, frame.width + 96, frame.height + 96);
                binding.anchor.set_position(frame.x, frame.y);binding.anchor.set_size(frame.width, frame.height);
                binding.blur.setEnabled(binding.source.actor.visible);
                if (binding.blur._layer) binding.blur._layer._glass50WindowOwner = actor;
                this._placeBehind(actor, binding);
            } catch (error) {
                this._drop(actor);this._reason = 'error';
                console.error(`Glass50 window material fell back: ${error}`);
            }
        }
        this._commit.update();
    }

    get diagnostics() {
        return {scene_commit: this._commit.diagnostics, reason: this._reason, pending: Boolean(this._pending), connections: this._connections.length,
            watched_windows: this._watches.size, bound_windows: this._bindings.size,
            active_windows: [...this._bindings.values()].filter(b => b.blur.enabled).length,
            windows: [...this._bindings.values()].map(b => ({frame: [...b.anchor.get_position(), ...b.anchor.get_size()],
                active: b.blur.enabled, anchor_scale: b.anchor.get_resource_scale(), source_scale: b.source.actor.get_resource_scale(),
                source: b.source.diagnostics, blur: b.blur.diagnostics}))};
    }

    destroy() {
        if (this._destroyed) return;
        this._destroyed = true;
        if (this._pending) GLib.source_remove(this._pending);
        this._pending = 0;this._stop();this._commit.destroy();
        for (const [actor, ids] of this._watches) for (const id of ids) actor.disconnect(id);
        this._watches.clear();
        for (const [object, id] of this._connections) object.disconnect(id);
        this._connections = [];this._order = [];this._nativeOrder = [];
    }
}
