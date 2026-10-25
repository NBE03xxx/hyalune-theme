// SPDX-License-Identifier: MIT
import Cogl from 'gi://Cogl';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import {RefreshGate} from './refresh-gate.js';

// This shader only masks alpha. Native Shell.BlurEffect still performs the blur.
export const RoundedMask = GObject.registerClass(
class Glass50RoundedMask extends Shell.GLSLEffect {
    _init(width, height, radius, {maxRefreshRate = 0, instrument = false} = {}) {
        super._init();
        this._telemetry = instrument ? {content_paints: 0, target_paints: 0, texture_creations: 0,
            last_texture_size: null, geometry_changes: 0} : null;
        this._refreshGate = new RefreshGate(() => this.queue_repaint(), {instrument});
        this._refreshGate.setRefreshRate(maxRefreshRate);
        this._geometry = null;
        this._sizeLocation = this.get_uniform_location('glass50_size');
        this._radiusLocation = this.get_uniform_location('glass50_radius');
        this._bufferLocation = this.get_uniform_location('glass50_buffer_size');
        this._offsetLocation = this.get_uniform_location('glass50_buffer_offset');
        this.setGeometry(width, height, radius);
    }

    vfunc_paint(node, context, flags) {
        super.vfunc_paint(node, context, this._refreshGate.adjust(flags));
    }

    vfunc_paint_node(node, context, flags) {
        if (this._telemetry) this._telemetry.content_paints++;
        super.vfunc_paint_node(node, context, flags);
    }

    vfunc_create_texture(context, width, height) {
        const texture = super.vfunc_create_texture(context, width, height);
        if (this._telemetry && texture) {
            this._telemetry.texture_creations++;
            this._telemetry.last_texture_size = [width, height];
        }
        return texture;
    }

    get targetSnapshot() { return this._lastTarget ? [...this._lastTarget] : null; }

    setRefreshRate(fps) { this._refreshGate.setRefreshRate(fps); }
    get diagnostics() { return {...this._refreshGate.diagnostics, mask_telemetry: this._telemetry ? {...this._telemetry} : null}; }
    destroy() { this._refreshGate.destroy(); }

    vfunc_build_pipeline() {
        this.add_glsl_snippet(Cogl.SnippetHook.FRAGMENT,
            'uniform vec2 glass50_size; uniform float glass50_radius; ' +
            'uniform vec2 glass50_buffer_size; uniform vec2 glass50_buffer_offset;', `
            vec2 p = cogl_tex_coord_in[0].st * glass50_buffer_size - glass50_buffer_offset;
            vec2 q = abs(p - glass50_size * 0.5) -
                (glass50_size * 0.5 - vec2(glass50_radius));
            float distance = length(max(q, vec2(0.0))) +
                min(max(q.x, q.y), 0.0) - glass50_radius;
            float feather = max(fwidth(distance), 0.0001);
            float coverage = 1.0 - smoothstep(-feather, 0.0, distance);
            // Preserve premultiplied alpha at the native offscreen composite.
            cogl_color_out *= coverage;
            `, false);
    }

    vfunc_paint_target(node, paintContext) {
        if (this._telemetry) this._telemetry.target_paints++;
        const [valid, width, height] = this.get_target_size();
        if (!valid || this.get_actor().get_resource_scale() !== 1)
            return; // Verified prototype range; keep the foreground theme readable.
        if (valid) {
            if (!this._lastTarget || this._lastTarget[1] !== width || this._lastTarget[2] !== height)
                this._lastTarget = [true, width, height];
            const scale = this.get_actor().get_resource_scale();
            // Shell 50's offscreen target adds a 3px guard at integer geometry.
            // Its native origin is -2 logical pixels; use the real texture size.
            this.set_uniform_float(this._bufferLocation, 2, [width / scale, height / scale]);
            const guard = 2 * Math.ceil(scale) / scale;
            this.set_uniform_float(this._offsetLocation, 2, [guard, guard]);
        }
        super.vfunc_paint_target(node, paintContext);
    }

    setGeometry(width, height, radius) {
        if (![width, height, radius].every(Number.isFinite) || width <= 0 || height <= 0 || radius < 0)
            throw new Error('Invalid Glass50 rounded mask geometry');
        const geometry = [width, height, radius];
        if (this._geometry?.every((value, index) => value === geometry[index])) return;
        if (this._telemetry) this._telemetry.geometry_changes++;
        this._geometry = geometry;
        this._refreshGate.invalidate();
        this.set_uniform_float(this._sizeLocation, 2, [width, height]);
        this.set_uniform_float(this._radiusLocation, 1, [Math.min(radius, width / 2, height / 2)]);
        this.queue_repaint();
    }
});
