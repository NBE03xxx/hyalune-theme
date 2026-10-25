// SPDX-License-Identifier: MIT
import GLib from 'gi://GLib';
import * as Config from 'resource:///org/gnome/shell/misc/config.js';

// Installation and runtime share the same OS/Shell/session contract. Display
// scale, monitor count and accessibility fallbacks remain effect-specific.
// Preserve the existing call-site flag; true now permits a managed user session.
export function assertEffectContext(allowVmSession = false) {
    const supported = GLib.get_os_info('ID') === 'ubuntu' && GLib.get_os_info('VERSION_ID') === '26.04' &&
        /^50\.\d+(?:\.\d+)?$/.test(Config.PACKAGE_VERSION) && Boolean(global.context.get_wayland_compositor());
    if (!supported) throw new Error('Glass50 effects require Ubuntu 26.04 / GNOME Shell 50.x / Wayland');
    const isolated = GLib.getenv('GLASS50_ISOLATED_PROBE') === '1' && GLib.getenv('GSETTINGS_BACKEND') === 'keyfile';
    if (isolated) return;
    if (allowVmSession) {
        const state = GLib.build_filenamev([GLib.get_home_dir(), '.local/state/glass50/installer-material-v1']);
        for (const name of ['runtime.json', 't16-runtime.json']) {
            try {
                const [, data] = GLib.file_get_contents(`${state}/${name}`);
                const marker = JSON.parse(new TextDecoder().decode(data));
                if (marker.format === 1 && (name === 'runtime.json' && marker.target === 'desktop' && marker.shell_major === 50 ||
                    name === 't16-runtime.json' && marker.target === 't16-trial')) return;
            } catch (_) { /* Missing/invalid ownership marker leaves theme-only fallback. */ }
        }
    }
    throw new Error('Glass50 effects require an explicitly managed user-session installation');
}
