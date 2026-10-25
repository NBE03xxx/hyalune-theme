// SPDX-License-Identifier: MIT
import Clutter from 'gi://Clutter';
import Shell from 'gi://Shell';
import Graphene from 'gi://Graphene';
import {RoundedMask} from './rounded-mask.js';

// Default contract: sibling actors. stageSource additionally permits a separate
// background subtree with translation-only stage coordinates; never clone an
// ancestor of the foreground. Foreground text and input stay untouched.
export class RoundedBackgroundBlur {
    constructor(source, foreground, {radius = 12, cornerRadius = 20, brightness = 1.0, resolutionScale = 1, stageSource = false, maxRefreshRate = 0, instrument = false} = {}) {
        if (![0, 15, 30, 60].includes(maxRefreshRate) || ![1, 0.5].includes(resolutionScale) || !Number.isInteger(radius) || radius < 0 || radius > 64 ||
            !Number.isFinite(cornerRadius) || cornerRadius < 0 ||
            !Number.isFinite(brightness) || brightness < 0 || brightness > 1)
            throw new Error('Invalid Glass50 rounded blur parameters');
        if (!source.get_parent() || !foreground.get_parent() || source === foreground ||
            source.contains(foreground) ||
            (!stageSource && source.get_parent() !== foreground.get_parent()))
            throw new Error('Glass50 prototype requires distinct sibling actors');
        this._instrument = Boolean(instrument);
        this._stageSource = Boolean(stageSource);
        this._source = source;
        this._foreground = foreground;
        this._radius = radius;
        this._cornerRadius = cornerRadius;
        this._brightness = brightness;
        this._resolutionScale = resolutionScale;
        this._maxRefreshRate = maxRefreshRate;
        this._layer = null;
        this._capture = null;
        this._clone = null;
        this._mask = null;
        this._blur = null;
        this._requested = false;
        this._destroyed = false;
        this._connections = [
            [source, source.connect('destroy', () => this.destroy())],
            [foreground, foreground.connect('destroy', () => this.destroy())],
            [source, source.connect('notify::allocation', () => this._sync())],
            [foreground, foreground.connect('notify::allocation', () => this._sync())],
        ];
    }

    setEnabled(enabled) {
        if (this._destroyed)
            throw new Error('Glass50 rounded blur has been destroyed');
        this._requested = Boolean(enabled);
        if (this._requested)
            this._sync();
        else
            this._dropLayer();
    }

    _sync() {
        if (!this._requested || this._destroyed)
            return;
        const parent = this._foreground.get_parent();
        if (!parent || (!this._stageSource && parent !== this._source.get_parent()) ||
            this._source.contains(this._foreground)) {
            // Reparenting outside our prototype contract falls back to theme only.
            this.setEnabled(false);
            return;
        }
        const [width, height] = this._foreground.get_size();
        if (width <= 0 || height <= 0) {
            this._dropLayer();
            return;
        }
        if (!Number.isInteger(width) || !Number.isInteger(height) ||
            this._foreground.get_resource_scale() !== 1) {
            // Only integer boxes on resource scale 1 have a verified guard mapping.
            this.setEnabled(false);
            return;
        }
        const [x, y] = this._foreground.get_position();
        let [sx, sy] = this._source.get_position();
        if (this._stageSource) {
            if (this._source.width <= 0 || this._source.height <= 0) {
                this.setEnabled(false);
                return;
            }
            // transform_stage_point rejects the native zero-size menu container.
            // Relative actor transforms also handle that fixed-layout container.
            const origin = actor => actor.apply_relative_transform_to_point(global.stage,
                new Graphene.Point3D());
            const translationOnly = actor => {
                const p = origin(actor);
                const x = actor.apply_relative_transform_to_point(global.stage,
                    new Graphene.Point3D({x: 1}));
                const y = actor.apply_relative_transform_to_point(global.stage,
                    new Graphene.Point3D({y: 1}));
                return [p.x, p.y, x.x, x.y, y.x, y.y].every(Number.isFinite) &&
                    Math.abs(x.x - p.x - 1) < 0.0001 && Math.abs(x.y - p.y) < 0.0001 &&
                    Math.abs(y.x - p.x) < 0.0001 && Math.abs(y.y - p.y - 1) < 0.0001;
            };
            if (!translationOnly(parent) || !translationOnly(this._source) ||
                this._source.get_resource_scale() !== 1) {
                this.setEnabled(false);
                return;
            }
            const a = origin(this._source);
            const b = origin(parent);
            [sx, sy] = [a.x - b.x, a.y - b.y];
        }
        const padding = this._radius * 2;
        if (!this._layer) {
            try {
                this._layer = new Clutter.Actor({reactive: false, clip_to_allocation: true});
                this._capture = new Clutter.Actor({reactive: false, clip_to_allocation: true});
                this._clone = new Clutter.Clone({source: this._source, reactive: false});
                this._capture.add_child(this._clone);
                this._layer.add_child(this._capture);
                this._blur = new Shell.BlurEffect({mode: Shell.BlurMode.ACTOR,
                    radius: Math.round(this._radius * this._resolutionScale), brightness: this._brightness});
                this._capture.add_effect_with_name('glass50-rounded-blur', this._blur);
                this._mask = new RoundedMask(width, height, this._cornerRadius, {maxRefreshRate: this._maxRefreshRate, instrument: this._instrument});
                this._layer.add_effect_with_name('glass50-rounded-mask', this._mask);
                parent.insert_child_below(this._layer, this._foreground);
            } catch (error) {
                this._requested = false;
                this._dropLayer();
                throw error;
            }
        }
        this._layer.set_position(x, y);
        this._layer.set_size(width, height);
        this._capture.set_position(-padding, -padding);
        this._capture.set_size((width + padding * 2) * this._resolutionScale,
            (height + padding * 2) * this._resolutionScale);
        this._capture.set_scale(1 / this._resolutionScale, 1 / this._resolutionScale);
        this._clone.set_scale(this._resolutionScale, this._resolutionScale);
        this._clone.set_position((padding + sx - x) * this._resolutionScale,
            (padding + sy - y) * this._resolutionScale);
        this._mask.setGeometry(width, height, this._cornerRadius);
    }

    _dropLayer() {
        if (!this._layer)
            return;
        if (this._blur)
            this._capture.remove_effect(this._blur);
        if (this._mask) {
            this._mask.destroy();
            this._layer.remove_effect(this._mask);
        }
        this._layer.destroy();
        this._layer = this._capture = this._clone = this._mask = this._blur = null;
    }

    get diagnostics() {
        return {stage_source: this._stageSource, resolution_scale: this._resolutionScale, signal_connections: this._connections.length,
            resource_scale: this._layer?.get_resource_scale() ?? null, layer_size: this._layer?.get_size() ?? null,
            capture_size: this._capture?.get_size() ?? null,
            refresh: this._mask?.diagnostics ?? null,
            mask_target_size: this._mask?.targetSnapshot ?? null,
            mask_texture_size: this._mask?.targetSnapshot?.slice(1) ?? null};
    }

    get enabled() {
        return this._layer !== null;
    }

    destroy() {
        if (this._destroyed)
            return;
        this._destroyed = true;
        this._requested = false;
        const connections = this._connections;
        this._connections = [];
        for (const [object, id] of connections)
            object.disconnect(id);
        this._dropLayer();
        this._source = this._foreground = null;
    }
}
