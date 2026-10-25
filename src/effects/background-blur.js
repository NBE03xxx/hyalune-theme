// SPDX-License-Identifier: MIT
import Shell from 'gi://Shell';

// Experimental primitive only. It does not select Shell surfaces or clip corners.
// The caller owns its lifetime and must disable it for accessibility/fallbacks.
export class BackgroundBlur {
    constructor(actor, {radius = 12, brightness = 1.0} = {}) {
        if (!Number.isInteger(radius) || radius < 0 || radius > 64 ||
            !Number.isFinite(brightness) || brightness < 0 || brightness > 1)
            throw new Error('Invalid Glass50 blur parameters');
        this._actor = actor;
        this._radius = radius;
        this._brightness = brightness;
        this._effect = null;
        this._name = 'glass50-phase4-background';
        this._destroyId = actor.connect('destroy', () => {
            this._actor = null;
            this._effect = null;
            this._destroyId = 0;
        });
    }

    setEnabled(enabled) {
        if (!this._actor)
            throw new Error('Glass50 blur actor has been destroyed');
        if (enabled && !this._effect) {
            if (this._actor.get_effect(this._name))
                throw new Error('Glass50 blur effect name is already in use');
            const effect = new Shell.BlurEffect({
                mode: Shell.BlurMode.BACKGROUND,
                radius: this._radius,
                brightness: this._brightness,
            });
            this._actor.add_effect_with_name(this._name, effect);
            this._effect = effect;
        } else if (!enabled && this._effect) {
            // Remove only our exact effect, even if another owner changes the name.
            this._actor.remove_effect(this._effect);
            this._effect = null;
        }
    }

    get enabled() {
        return this._effect !== null;
    }

    destroy() {
        if (this._actor) {
            this.setEnabled(false);
            this._actor.disconnect(this._destroyId);
        }
        this._destroyId = 0;
        this._actor = null;
        this._effect = null;
    }
}
