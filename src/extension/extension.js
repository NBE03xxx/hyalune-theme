// SPDX-License-Identifier: MIT
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {assertEffectContext} from './effects/runtime-context.js';
import {QuickSettingsBlur} from './effects/quick-settings-blur.js';
import {WindowMaterial} from './effects/window-material.js';
import {WindowBackdropSource} from './effects/window-backdrop-source.js';

export default class Glass50BlurExtension extends Extension {
    enable() {
        assertEffectContext(true);
        this._settings=this.getSettings();
        this._pending=0;
        this._diagnosticTimer=0;this._diagnosticSamples=0;
        this._windows=null;
        this._lifecycle={sync_calls:0,source_builds:0,source_drops:0};
        this._menu=Main.panel.statusArea.quickSettings.menu;
        this._menuId=this._menu.connect('open-state-changed',()=>this._queue());
        this._settingsId=this._settings.connect('changed::effect-enabled',()=>this._queue());
        this._refreshId=this._settings.connect('changed::limit-background-refresh',()=>this._queue());
        this._context=St.ThemeContext.get_for_stage(global.stage);
        this._themeId=this._context.connect('changed',()=>this._queue());
        this._diagnosticsId=this._settings.connect('changed::diagnostics-enabled',()=>{
            this._configureWindows();this._configureDiagnostics();this._queue();
        });
        this._windowSettingsId=this._settings.connect('changed::window-material-enabled',()=>this._configureWindows());
        this._configureWindows();this._configureDiagnostics();this._sync();
    }
    _configureWindows() {
        this._windows?.destroy();this._windows=null;
        if (this._settings.get_boolean('window-material-enabled'))
            this._windows=new WindowMaterial({allowVmSession:true,instrument:this._settings.get_boolean('diagnostics-enabled')});
    }
    _configureDiagnostics() {
        this._stopDiagnostics();this._diagnosticSamples=0;
        if (!this._settings.get_boolean('diagnostics-enabled')) return;
        // Journal only; never trigger a repaint or inspect the native window tree.
        this._diagnosticTimer=GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT,1,()=>{
            console.log(`Glass50 diagnostics ${JSON.stringify({version:1,us:GLib.get_monotonic_time(),...this.diagnostics})}`);
            this._diagnosticSamples++;
            if (this._diagnosticSamples>=120) {this._diagnosticTimer=0;return GLib.SOURCE_REMOVE;}
            return GLib.SOURCE_CONTINUE;
        });
    }
    _stopDiagnostics() {
        if (this._diagnosticTimer) GLib.source_remove(this._diagnosticTimer);
        this._diagnosticTimer=0;
    }
    _queue() {
        if (this._pending) return;
        this._pending=GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE,()=>{
            this._pending=0;this._sync();return GLib.SOURCE_REMOVE;
        });
    }
    _sync() {
        this._lifecycle.sync_calls++;
        this._stop();
        if (!this._settings.get_boolean('effect-enabled') || !this._menu.isOpen) return;
        const path=Main.getThemeStylesheet()?.get_path()??'';
        if (!['Glass50-Dark','Glass50-Material-Preview'].some(name=>path.endsWith(`/${name}/gnome-shell/gnome-shell.css`))) return;
        try {
            this._lifecycle.source_builds++;
            this._source=new WindowBackdropSource({allowVmSession:true});
            this._blur=new QuickSettingsBlur(this._menu,this._source.actor,
                {allowVmSession:true,clipSource:true,resolutionScale:0.5,instrument:this._settings.get_boolean('diagnostics-enabled'),maxRefreshRate:this._settings.get_boolean('limit-background-refresh')?30:0});
            this._blur.setEnabled(true);
            if (path.includes('/Glass50-Material-Preview/') && this._blur.diagnostics.active)
                this._blur._blur._blur.brightness=0.85;
        } catch(error) {
            this._stop();
            console.error(`Glass50 preview fell back to the existing theme: ${error}`);
        }
    }
    _stop() {
        if (this._source) this._lifecycle.source_drops++;
        this._blur?.destroy();this._blur=null;
        this._source?.destroy();this._source=null;
    }
    get diagnostics() {
        return {runtime_version:7,window_update_strategy:"owned-commit",lifecycle:{...this._lifecycle},window_material:this._windows?.diagnostics??null,diagnostics_setting:this._settings?.get_boolean('diagnostics-enabled')??false,
            diagnostics_connection:Boolean(this._diagnosticsId),diagnostic_timer:Boolean(this._diagnosticTimer),diagnostic_samples:this._diagnosticSamples,enabled_setting:this._settings?.get_boolean('effect-enabled')??false,
            refresh_limited_setting:this._settings?.get_boolean('limit-background-refresh')??true,refresh_connection:Boolean(this._refreshId),
            settings_connection:Boolean(this._settingsId),menu_connection:Boolean(this._menuId),pending_sync:Boolean(this._pending),source:this._source?.diagnostics??null,
            blur:this._blur?.diagnostics??null};
    }
    disable() {
        this._windows?.destroy();this._windows=null;
        if (this._windowSettingsId) this._settings.disconnect(this._windowSettingsId);
        this._windowSettingsId=0;
        this._stopDiagnostics();
        if (this._diagnosticsId) this._settings.disconnect(this._diagnosticsId);
        this._diagnosticsId=0;
        if (this._pending) GLib.source_remove(this._pending);
        this._pending=0;
        if (this._menuId) this._menu.disconnect(this._menuId);
        this._menuId=0;this._menu=null;
        if (this._themeId) this._context.disconnect(this._themeId);
        this._themeId=0;this._context=null;
        if (this._refreshId) this._settings.disconnect(this._refreshId);
        this._refreshId=0;
        if (this._settingsId) this._settings.disconnect(this._settingsId);
        this._settingsId=0;
        this._stop();
        this._settings=null;
    }
}
