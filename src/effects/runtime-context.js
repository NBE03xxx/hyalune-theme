// SPDX-License-Identifier: MIT
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
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

// A custom Shell stylesheet overrides the native High Contrast sheet. Keep a
// temporary, memory-only native theme while HC is active; never change dconf.
// This also works with both blur preferences off.
export class MaterialAccessibility {
    constructor() {
        this._context = St.ThemeContext.get_for_stage(global.stage);
        this._settings = St.Settings.get();
        this._owned = null;
        this._pending = 0;
        this._themeId = this._context.connect('changed', () => this._queue());
        this._contrastId = this._settings.connect('notify::high-contrast', () => this._queue());
        this._queue();
    }

    _queue() {
        if (this._pending) return;
        this._pending = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._pending = 0;
            this._sync();
            return GLib.SOURCE_REMOVE;
        });
    }

    _sync() {
        const path = Main.getThemeStylesheet()?.get_path() ?? '';
        const material = ['/Hyalune/gnome-shell/gnome-shell.css', '/Glass50-Material-Preview/gnome-shell/gnome-shell.css',
            '/Hyalune-Light/gnome-shell/gnome-shell.css'].some(suffix => path.endsWith(suffix));
        const wanted = material && this._settings.high_contrast;
        const current = this._context.get_theme();
        if (wanted && current !== this._owned) {
            const styles = current?.get_custom_stylesheets() ?? [];
            const native = new St.Theme({application_stylesheet: Gio.File.new_for_uri(
                'resource:///org/gnome/shell/theme/gnome-shell-high-contrast.css')});
            for (const file of styles) native.load_stylesheet(file);
            this._owned = native;
            this._context.set_theme(native);
        } else if (!wanted && this._owned) {
            if (current === this._owned) Main.loadTheme();
            this._owned = null;
        }
    }

    get active() { return this._context?.get_theme() === this._owned && this._owned !== null; }

    destroy() {
        if (this._pending) GLib.source_remove(this._pending);
        this._pending = 0;
        this._context.disconnect(this._themeId);
        this._settings.disconnect(this._contrastId);
        if (this._owned && this._context.get_theme() === this._owned) Main.loadTheme();
        this._owned = null;
    }
}

// The existing extension owns the watcher. The child uses the manager's shared
// lock/journal; no shell command, privileged endpoint or second daemon.
export class AppearanceSync {
    constructor(iface) {
        this._iface = iface;
        this._stopped = false;
        this._timer = 0;
        this._child = null;
        this._dirty = false;
        this._retries = 0;
        this.last = {status: 'starting'};
        this._signal = iface.connect('changed::color-scheme', () => {
            this._retries = 0;
            this._queue(450);
        });
        this._shell = Gio.Settings.new('org.gnome.shell');
        this._shellSignals = ['enabled-extensions', 'disabled-extensions', 'disable-user-extensions']
            .map(key => this._shell.connect(`changed::${key}`, () => this._queue(500)));
        this._startup = Main.layoutManager.connect('startup-complete', () => this._queue(500));
        this._queue(700);
    }

    _queue(delay) {
        if (this._stopped) return;
        this._dirty = true;
        if (this._child) return;
        if (this._timer) GLib.source_remove(this._timer);
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
            this._timer = 0;
            this._run();
            return GLib.SOURCE_REMOVE;
        });
    }

    _run() {
        if (this._stopped) return;
        this._dirty = false;
        const path = GLib.build_filenamev([GLib.get_home_dir(),
            '.local/share/hyalune/settings/app/tools/manage-settings.py']);
        if (!GLib.file_test(path, GLib.FileTest.IS_REGULAR)) {
            this.last = {status: 'paused', reason: 'manager-not-installed'};
            return;
        }
        const argv = ['python3', '-B', path, 'sync'];
        if (GLib.getenv('GLASS50_ISOLATED_PROBE') === '1' && GLib.getenv('GSETTINGS_BACKEND') === 'keyfile')
            argv.push('--test-root', GLib.get_home_dir());
        try {
            const proc = Gio.Subprocess.new(argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            this._child = proc;
            proc.communicate_utf8_async(null, null, (child, result) => {
                this._child = null;
                let response;
                try {
                    const [, out] = child.communicate_utf8_finish(result);
                    response = JSON.parse(out);
                    if (response.api !== 'hyalune.settings' || response.version !== 1)
                        throw new Error('Unsupported appearance response');
                } catch (_) {
                    response = {ok: false, error: {code: 'sync-response-failed'}};
                }
                if (this._stopped) return;
                this.last = response.ok ? {status: response.result.status ?? 'applied', reason: response.result.reason ?? null} :
                    {status: 'paused', reason: response.error?.code ?? 'sync-failed'};
                if (this._dirty) {
                    this._queue(150);
                } else if (!response.ok && ['stale-sync', 'resource-busy', 'private-shell-active'].includes(response.error?.code) && this._retries++ < 3) {
                    this._queue(1500);
                } else if (response.ok && response.result.manager?.apps?.some(row =>
                    row.status === 'deferred' && row.reason?.startsWith('起動中'))) {
                    this._queue(10000);
                } else if (!response.ok) {
                    console.warn(`Hyalune appearance sync paused: ${this.last.reason}`);
                }
            });
        } catch (_) {
            this._child = null;
            this.last = {status: 'paused', reason: 'sync-launch-failed'};
        }
    }

    destroy() {
        this._stopped = true;
        if (this._timer) GLib.source_remove(this._timer);
        this._timer = 0;
        this._iface.disconnect(this._signal);
        for (const id of this._shellSignals) this._shell.disconnect(id);
        this._shell = null;
        Main.layoutManager.disconnect(this._startup);
        // Reap a started child normally: killing a transaction midway would
        // unnecessarily create a pending journal. No further job is queued.
        this._iface = null;
    }
}
