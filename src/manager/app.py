# SPDX-License-Identifier: MIT
"""Hyalune Settings. Draft edits never write live theme settings."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk
from .i18n import _, message
from . import profile

APP_ID = 'io.github.NBE03xxx.Hyalune.Settings'
ROOT = Path(__file__).resolve().parents[2]
PAGES = [('overview',_('Overview')), ('appearance',_('Appearance')), ('blur',_('Blur')), ('gdm',_('Login Screen')), ('apps',_('Flatpak Apps')), ('history',_('History and Restore'))]
TARGET_NAMES = {'panel': _('Panel'), 'shell': _('Menus and Dialogs'),
                'gtk3': _('GTK3 Windows'), 'gtk4': _('GTK4 Windows')}
HISTORY_NAMES = {'apply': _('Install'), 'update': _('Update'), 'remove': _('Remove'),
                 'recover': _('Recover'), 'undo': _('Undo'), 'committed': _('Completed'),
                 'rolled-back': _('Rolled Back'), 'recovered': _('Recovered')}


def label(text='', **kwargs):
    return Gtk.Label(label=text, wrap=True, xalign=0, **kwargs)


def button(text, callback, suggested=False):
    b = Gtk.Button(label=text); b.connect('clicked', callback)
    if suggested: b.add_css_class('suggested-action')
    return b


class Adapter:
    def __init__(self, test_root=None):
        self.test_root = test_root

    def call(self, action, request, callback, operation=None):
        argv = [sys.executable, str(ROOT/'tools/manage-settings.py'), action]
        if self.test_root: argv += ['--test-root', str(self.test_root)]
        if operation: argv += ['--operation', operation]
        try:
            process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
            def done(proc, result):
                try:
                    unused, stdout, stderr = proc.communicate_utf8_finish(result)
                    value = json.loads(stdout)
                    if value.get('api') != 'hyalune.settings' or value.get('version') != 1:
                        raise ValueError(_('Unsupported operation response.'))
                    callback(value)
                except Exception as error:
                    callback({'ok':False,'error':{'code':'adapter-failed','message':str(error)}})
            process.communicate_utf8_async(json.dumps(request) if request else None, None, done)
        except Exception as error:
            callback({'ok':False,'error':{'code':'launch-failed','message':str(error)}})


class Window(Adw.ApplicationWindow):
    def __init__(self, application, test_root=None):
        super().__init__(application=application, title=_('Hyalune Settings'), default_width=1000, default_height=760)
        self.set_size_request(360, 480)
        self.adapter = Adapter(test_root); self.test_root = test_root
        self.value = profile.defaults(); self.applied = None; self.current = None
        self.initialized = False; self.updating = False; self.busy = False
        self.selected_apps = set(); self.plan = None; self.row_controls = []
        self.config = (Path(test_root)/'.config' if test_root else Path(GLib.get_user_config_dir()))/'hyalune/profile.json'
        self.connect('close-request', self.close_request)
        self.split = Adw.NavigationSplitView(min_sidebar_width=190, max_sidebar_width=230)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 720sp'))
        bp.add_setter(self.split, 'collapsed', True); self.add_breakpoint(bp)
        self.set_content(self.split)
        side = Adw.ToolbarView(); side.add_top_bar(Adw.HeaderBar())
        nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, margin_top=12, margin_start=8, margin_end=8)
        nav.add_css_class('navigation-sidebar')
        for key, text in PAGES:
            row = Gtk.ListBoxRow(); row.page_key = key
            row.set_child(label(text, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)); nav.append(row)
        nav.connect('row-selected', self.navigate); side.set_content(nav)
        self.split.set_sidebar(Adw.NavigationPage.new(side, _('Hyalune Settings')))
        content = Adw.ToolbarView(); self.header = Adw.HeaderBar()
        self.refresh = button(_('Reload'), lambda unused: self.reload()); self.header.pack_end(self.refresh)
        self.header_apply = button(_('Review Changes'), lambda unused: self.review(), True); self.header.pack_end(self.header_apply)
        content.add_top_bar(self.header)
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.notice = Adw.Banner(title=_('Checking status'), revealed=True); layout.append(self.notice)
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        layout.append(self.stack); content.set_content(layout)
        self.content_page = Adw.NavigationPage.new(content, _('Appearance'))
        self.split.set_content(self.content_page)
        self.pages = {}
        for key, text in PAGES:
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            clamp = Adw.Clamp(maximum_size=670, tightening_threshold=520)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=22, margin_bottom=28,
                          margin_start=24, margin_end=24)
            title = label(text); title.add_css_class('title-1'); box.append(title)
            clamp.set_child(box); scroll.set_child(clamp); self.stack.add_named(scroll, key); self.pages[key]=box
        self.make_appearance(); self.make_other_pages()
        self._watch_timer = 0; self._watch_closed = False; self._state_monitor = None
        self._interface = Gio.Settings.new('org.gnome.desktop.interface')
        self._interface_signal = self._interface.connect('changed::color-scheme',lambda *unused:self.queue_reload())
        home = Path(test_root) if test_root else Path(GLib.get_home_dir())
        folder = home/'.local/state/glass50/installer-material-v1'
        if folder.is_dir():
            self._state_monitor = Gio.File.new_for_path(str(folder)).monitor_directory(Gio.FileMonitorFlags.NONE,None)
            self._state_monitor.connect('changed',lambda _m,f,_other,_event:self.queue_reload() if f.get_basename()=='active.json' else None)
        nav.select_row(nav.get_row_at_index(1))
        self.reload()

    def navigate(self, nav, row):
        if row:
            self.stack.set_visible_child_name(row.page_key)
            self.content_page.set_title(dict(PAGES)[row.page_key]); self.split.set_show_content(True)
            self.header_apply.set_visible(row.page_key not in ('gdm','history'))

    def set_busy(self, value, text=''):
        self.busy = value; self.stack.set_sensitive(not value); self.refresh.set_sensitive(not value)
        self.header_apply.set_sensitive(not value)
        if text: self.notice.set_title(text); self.notice.set_revealed(True)
        if value: self.get_application().hold()
        else: self.get_application().release()

    def error(self, result):
        self.notice.set_title(message(result.get('error',{}).get('message',_('The operation failed.'))))
        self.notice.set_revealed(True)

    def make_appearance(self):
        box = self.pages['appearance']
        box.append(label(_('Adjust the common material, check the preview, then apply.')))
        self.variant_selector = Gtk.DropDown.new_from_strings(['Hyalune Dark', 'Hyalune Light'])
        self.variant_selector.add_css_class('hyalune-target-selector')
        self.variant_selector.update_property([Gtk.AccessibleProperty.LABEL], [_('Appearance mode')])
        self.variant_selector.connect('notify::selected', self.change_variant)
        box.append(self.variant_selector)
        box.append(label(_('Automatically follows the Ubuntu appearance setting. Use Apply to activate the mode and material edited here. The login screen is managed separately.'), css_classes=['dim-label']))
        self.preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=4, margin_bottom=4)
        self.preview.add_css_class('hyalune-preview')
        self.preview_panel = label(_('Hyalune  •  Panel preview'), margin_top=14, margin_bottom=14, margin_start=16, margin_end=16)
        self.preview_panel.add_css_class('hyalune-panel'); self.preview.append(self.preview_panel)
        self.preview_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=22, margin_end=22, margin_bottom=24, margin_top=8)
        self.preview_card.add_css_class('hyalune-card')
        self.preview_card.append(label(_('Glass Material Preview'), margin_top=16, margin_start=16, margin_end=16))
        controls = Gtk.Box(spacing=10, margin_start=16, margin_end=16, margin_bottom=16)
        controls.append(Gtk.Button(label=_('Standard Button'))); controls.append(Gtk.Switch(active=True, valign=Gtk.Align.CENTER))
        self.preview_card.append(controls); self.preview.append(self.preview_card); box.append(self.preview)
        box.append(label(_('This preview uses real GTK widgets to illustrate the material. It does not reproduce the Shell or GDM screen or actual blur.'), css_classes=['dim-label']))
        self.common_scale = self.add_scale(box, _('Common Opacity'), lambda v:self.change_surface('common','opacity',v))
        self.common_color = self.color_control(box, _('Material Color'), lambda v:self.change_surface('common','color',v))
        self.summary = label(_('Panel override: 38%. Login screen: 32%, managed separately.')); box.append(self.summary)
        self.details_toggle = Gtk.ToggleButton(label=_('Adjust Individual Parts')); box.append(self.details_toggle)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, visible=False)
        box.append(self.details)
        self.details_toggle.connect('toggled', lambda b:self.details.set_visible(b.get_active()))
        self.target = Gtk.DropDown.new_from_strings([_('Select a Target'), *TARGET_NAMES.values()])
        self.target.add_css_class('hyalune-target-selector')
        self.target.update_property([Gtk.AccessibleProperty.LABEL], [_('Override target')])
        self.target.connect('notify::selected', self.select_target); self.details.append(self.target)
        self.target_form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, visible=False); self.details.append(self.target_form)
        self.target_scale = self.add_scale(self.target_form, _('Target Opacity'), self.target_opacity)
        self.target_color = self.color_control(self.target_form, _('Target Material Color'), self.target_color_changed)
        self.target_form.append(button(_('Use Common Settings for This Target'), self.inherit))
        self.edit_state = label(''); box.append(self.edit_state)
        actions = Gtk.Box(spacing=10, orientation=Gtk.Orientation.VERTICAL)
        self.apply_button = button(_('Review and Apply Changes'), lambda unused:self.review(), True); actions.append(self.apply_button)
        actions.append(button(_('Save Profile'), self.save_profile))
        actions.append(button(_('Discard Edits'), self.cancel_edit))
        actions.append(button(_('Reset Draft to Hyalune Defaults'), self.reset_defaults))
        box.append(actions)
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        # Fixed app chrome, independent of the unapplied preview's material.
        self.chrome_provider = Gtk.CssProvider()
        # Custom providers have their own media-query preferences. Follow the
        # display settings with one-way bindings; never write desktop settings.
        settings = Gtk.Settings.get_for_display(Gdk.Display.get_default())
        self.chrome_bindings = [settings.bind_property(source, self.chrome_provider, target, GObject.BindingFlags.SYNC_CREATE)
                                for source, target in [('gtk-interface-color-scheme','prefers-color-scheme'),
                                                       ('gtk-interface-contrast','prefers-contrast')]]
        self.chrome_provider.load_from_path(str(Path(__file__).with_name('style.css')))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.chrome_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        self.sync_form()

    def add_scale(self, box, title, callback):
        box.append(label(title))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        scale.set_draw_value(True); scale.set_value_pos(Gtk.PositionType.RIGHT); scale.set_digits(0)
        scale.update_property([Gtk.AccessibleProperty.LABEL],[title])
        scale.connect('value-changed', lambda w:callback(round(w.get_value()/100,2)) if not self.updating else None)
        box.append(scale); return scale

    def color_control(self, box, title, callback):
        row = Gtk.Box(spacing=10, orientation=Gtk.Orientation.VERTICAL)
        choose = Gtk.CheckButton(label=_('Adjust {target}').format(target=title)); row.append(choose)
        entry = Gtk.Entry(placeholder_text='#1a1a1c', visible=False)
        entry.update_property([Gtk.AccessibleProperty.LABEL],[_('{target} (#RRGGBB)').format(target=title)])
        row.append(entry); box.append(row)
        choose.connect('toggled', lambda b:entry.set_visible(b.get_active()))
        def changed(w):
            if not self.updating:
                try: color = profile.surface({'opacity':.56,'color':w.get_text()})['color']
                except ValueError: w.add_css_class('error'); return
                w.remove_css_class('error'); callback(color)
        entry.connect('changed', changed)
        # Hiding the entry retains the selected color. Returning to default is
        # the explicit default/common action, never the disclosure checkbox.
        return entry

    def change_variant(self, *unused):
        if self.updating: return
        self.value = profile.select_variant(self.value, 'light' if self.variant_selector.get_selected() else 'dark')
        self.sync_form()

    def change_surface(self, scope, field, value):
        self.value[scope][field] = value; self.changed()

    def selected_target(self):
        i = self.target.get_selected()
        return list(profile.TARGETS)[i-1] if 1 <= i <= len(profile.TARGETS) else None

    def select_target(self, *unused):
        key = self.selected_target(); self.target_form.set_visible(bool(key))
        if key:
            self.updating=True; v=profile.effective(self.value,key)
            self.target_scale.set_value(v['opacity']*100); self.target_color.set_text(v['color']); self.updating=False
            self.target_color.remove_css_class('error')

    def target_opacity(self, alpha):
        key = self.selected_target()
        if key:
            self.value['overrides'].setdefault(key, copy.deepcopy(self.value['common']))['opacity']=alpha; self.changed()

    def target_color_changed(self, color):
        key = self.selected_target()
        if key:
            self.value['overrides'].setdefault(key, copy.deepcopy(self.value['common']))['color']=color; self.changed()

    def inherit(self, *unused):
        key=self.selected_target()
        if key: self.value['overrides'].pop(key,None); self.select_target(); self.changed()

    def changed(self):
        self.plan=None
        if hasattr(self,'app_scope_note'): self.app_scope_note.set_visible(profile.variant(self.value)=='light')
        self.summary.set_text(_('Overrides: {targets}. Login screen managed separately (default: 32%).').format(
            targets=_(', ').join(TARGET_NAMES[k] for k in self.value['overrides']) or _('None')))
        dirty = self.applied is None or self.value != self.applied
        self.edit_state.set_text(_('There are unapplied edits. Saving alone does not apply them to your desktop.') if dirty else _('These values match the last installed profile. Verify the loaded appearance separately.'))
        ink='#111214' if profile.variant(self.value)=='light' else '#f4f6fa'
        edge='alpha(black,.22)' if profile.variant(self.value)=='light' else 'alpha(white,.22)'
        p=profile.rgba(profile.effective(self.value,'panel')); c=profile.rgba(self.value['common'])
        self.provider.load_from_string('''
.hyalune-preview { background-image: linear-gradient(135deg, #286c83, #8c5965 48%%, #c0ad79); border-radius: 18px; }
.hyalune-preview .hyalune-panel { background-color: %s; color: %s; border-radius: 14px; }
.hyalune-preview .hyalune-card { background-color: %s; color: %s; border-radius: 16px; border: 1px solid %s; }
''' % (p,ink,c,ink,edge))

    def sync_form(self):
        self.updating=True
        self.variant_selector.set_selected(1 if profile.variant(self.value)=='light' else 0)
        self.common_scale.set_value(self.value['common']['opacity']*100); self.common_color.set_text(self.value['common']['color'])
        self.common_color.remove_css_class('error')
        if hasattr(self,'blur_switches'):
            for k,w in self.blur_switches.items(): w.set_active(self.value['blur'][k])
        self.updating=False; self.select_target(); self.changed()
        if getattr(self,'active_app',None):
            visible=self.app_editor.get_visible();self.open_app(self.active_app);self.app_editor.set_visible(visible)

    def make_other_pages(self):
        self.overview_text=label(_('Checking')); self.pages['overview'].append(self.overview_text)
        self.pages['overview'].append(button(_('Reload Installation Status'),lambda unused:self.reload()))
        b=self.pages['blur']; b.append(label(_('Choose Quick Settings and window effects separately. Changes take effect only when you apply them.')))
        self.blur_switches={}
        for key,title in [('quick_settings',_('Quick Settings Blur')),('windows',_('Window Material Effects'))]:
            row=Adw.SwitchRow(title=title); b.append(row); self.blur_switches[key]=row
            row.connect('notify::active',lambda w,unused,k=key:self.change_blur(k,w.get_active()))
        b.append(label(_('Blur is also available in Light mode within the extension’s supported conditions. It stops for High Contrast, Reduced Motion, and unsupported scales. Installed or enabled effects may not be actively rendering.')))
        b.append(button(_('Review and Apply Changes'),lambda unused:self.review(),True))
        from .gdm_ui import View
        self.gdm_view=View(self);self.pages['gdm'].append(self.gdm_view)
        apps=self.pages['apps']; apps.append(label(_('Apps following common settings are updated each time you apply changes. Running apps and conflicting targets are deferred; apps are never closed automatically.')))
        self.app_scope_note=label(_('GTK3 Flatpak apps use their standard appearance in Light mode. Custom material values are retained.'),css_classes=['dim-label'],visible=profile.variant(self.value)=='light');apps.append(self.app_scope_note)
        apps.append(button(_('Scan Again'),lambda unused:self.reload())); self.app_rows=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8); apps.append(self.app_rows)
        self.app_editor=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,visible=False);apps.append(self.app_editor)
        self.app_title=label('');self.app_editor.append(self.app_title);self.active_app=None
        self.app_mode=Gtk.DropDown.new_from_strings([_('Follow Common Settings'),_('Custom Settings'),_('Keep Current Appearance')])
        self.app_mode.add_css_class('hyalune-target-selector');self.app_mode.update_property([Gtk.AccessibleProperty.LABEL],[_('Flatpak appearance policy')])
        self.app_mode.connect('notify::selected',self.app_mode_changed);self.app_editor.append(self.app_mode)
        self.app_custom=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,visible=False);self.app_editor.append(self.app_custom)
        self.app_scale=self.add_scale(self.app_custom,_('App Opacity'),lambda v:self.app_surface_changed('opacity',v))
        self.app_color=self.color_control(self.app_custom,_('App Material Color'),lambda v:self.app_surface_changed('color',v))
        self.app_editor.append(button(_('Close App Settings'),lambda unused:self.app_editor.set_visible(False)))
        apps.append(button(_('Review and Apply Changes'),lambda unused:self.review(),True))
        h=self.pages['history']; h.append(label(_('Removing the theme includes managed Flatpak apps. GDM is a separate operation. The settings app and backups are retained.')))
        h.append(button(_('Undo Last Apply'),lambda unused:self.confirm_operation('undo',_('Undo Last Apply'),_('Restore the theme, settings, and affected Flatpak apps to their state before the last update using the saved records. Stops if current values differ from the recorded state.'))))
        h.append(button(_('Recover Interrupted Operation'),lambda unused:self.confirm_operation('recover',_('Recover Interrupted Operation'),_('Recover using the existing journal.'))))
        h.append(button(_('Remove Theme and Restore Previous Settings'),lambda unused:self.review_remove()))
        self.history_text=label(''); h.append(self.history_text)

    def change_blur(self,key,value):
        if not self.updating: self.value['blur'][key]=value; self.changed()

    def reload(self, passive=False):
        if self.busy:return
        self.set_busy(True,'' if passive else _('Checking installation and Flatpak apps'))
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):
                if not passive:self.error(response)
                return
            state=response['result']; self.current=state
            if not self.initialized:
                self.applied=profile.upgrade(state['profile']) if state['profile'] else None
                self.value=profile.upgrade(state['profile'] or profile.defaults())
                if state['profile'] is None: self.value['blur']=copy.deepcopy(state['blur'])
                if self.config.is_file():
                    try:self.value=profile.upgrade(json.loads(self.config.read_text()))
                    except Exception as error:self.error({'error':{'message':_('Cannot read the saved profile: {details}').format(details=message(str(error)))}})
                self.initialized=True;self.sync_form()
            else:
                clean = self.applied is not None and self.value == self.applied
                self.applied=profile.upgrade(state['profile']) if state['profile'] else None
                if clean and self.applied is not None:
                    self.value=copy.deepcopy(self.applied);self.sync_form()
                else:self.changed()
            issues=[]
            if getattr(self,'pending_result',None):issues.append(self.pending_result);self.pending_result=None
            if state['pending']:issues.append(_('An operation was interrupted. Recover it from History and Restore.'))
            if state['legacy_pending']:issues.append(_('A legacy installation was interrupted. Recover it using the existing CLI.'))
            if state['conflicts']:issues.append(_('External changes detected. Resolve the conflicts before applying.'))
            if state.get('external_color_scheme'):issues.append(_('The GNOME appearance setting has changed. Apply to use the mode selected here.'))
            if state.get('extensions_globally_disabled'):issues.append(_('GNOME extensions are globally disabled, so appearance synchronization is paused. Enable them in Extensions to resume.'))
            if state['identification']=='unidentified-fixed-values':issues.append(_('The legacy material values are unknown. Defaults are shown for editing.'))
            if not passive:
                self.notice.set_title(' '.join(issues) or _('Installation status checked. The loaded appearance has not been verified.'));self.notice.set_revealed(True)
            self.apply_button.set_sensitive(not(state['pending'] or state['legacy_pending'] or state['conflicts']))
            identification = {'managed-profile': _('Saved profile'), 'fixed-release': _('Known defaults'),
                              'unidentified-fixed-values': _('Unknown legacy values'), 'not-installed': _('Not installed')}
            self.overview_text.set_text(_('Desktop theme: {version}\nProfile: {profile}\nGDM: Explicit administrator check required\n{note}').format(
                version=str(state['version']) if state['managed'] else _('Not installed'),
                profile=identification.get(state['identification'], state['identification']), note=message(state['runtime']['note'])))
            self.update_apps(state['flatpak'])
            self.history_text.set_text('\n\n'.join(r['at']+'\n'+HISTORY_NAMES.get(r['action'],r['action'])+' / '+HISTORY_NAMES.get(r['status'],r['status']) for r in state['history']) or _('No apply history.'))
        self.adapter.call('status',None,done)

    def queue_reload(self):
        if self._watch_closed or self._watch_timer:return
        def tick():
            if self.busy:return True
            self._watch_timer=0;self.reload(passive=True);return False
        self._watch_timer=GLib.timeout_add(700,tick)

    def stop_watch(self):
        if self._watch_closed:return
        self._watch_closed=True
        if self._watch_timer:GLib.source_remove(self._watch_timer)
        self._watch_timer=0
        self._interface.disconnect(self._interface_signal)
        if self._state_monitor:self._state_monitor.cancel();self._state_monitor=None

    def update_apps(self,inventory):
        self.inventory=inventory
        child=self.app_rows.get_first_child()
        while child:
            nxt=child.get_next_sibling();self.app_rows.remove(child);child=nxt
        self.row_controls=[]
        statuses={'candidate':_('Not applied'),'already-managed':_('Managed'),'deferred':_('Running / Deferred'),'conflict':_('Conflict'),'skipped':_('Unsupported / Unknown')}
        modes={'follow':_('Follow Common Settings'),'custom':_('Custom Settings'),'hold':_('Keep Current Appearance')}
        for row in inventory['apps']:
            app_id=row['app']
            if app_id not in self.value['flatpak'] and row.get('policy',{}).get('mode')!='hold':
                self.value['flatpak'][app_id]=copy.deepcopy(row['policy'])
            policy=self.value['flatpak'].get(app_id,{'mode':'hold'})
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
            w=button(app_id,lambda unused,name=app_id:self.open_app(name));w.set_sensitive(row['toolkit'] in ('gtk3','gtk4'))
            box.append(w);box.append(label(statuses.get(row['status'],row['status'])+' · '+modes[policy['mode']]+(_(' · Update pending') if row.get('needs_update') else '')+'\n'+'\n'.join(message(row[k]) for k in ('reason','rendering_note') if row.get(k)),css_classes=['dim-label']))
            self.app_rows.append(box);self.row_controls.append(w)
        if not inventory['apps']:self.app_rows.append(label(_('No Flatpak apps found.') if inventory['available'] else _('Flatpak is not installed.')))

    def open_app(self,name):
        self.active_app=name;self.app_title.set_text(name+(_(' — Standard GTK3 appearance in Light mode (custom values retained)') if profile.variant(self.value)=='light' and any(r['app']==name and r['toolkit']=='gtk3' for r in self.inventory['apps']) else ''));self.app_editor.set_visible(True)
        policy=self.value['flatpak'].get(name,{'mode':'hold'})
        self.updating=True;self.app_mode.set_selected(['follow','custom','hold'].index(policy['mode']))
        face=policy.get('surface',self.value['common']);self.app_scale.set_value(face['opacity']*100);self.app_color.set_text(face['color']);self.app_color.remove_css_class('error')
        self.app_custom.set_visible(policy['mode']=='custom');self.updating=False

    def app_mode_changed(self,*unused):
        if self.updating or not self.active_app:return
        mode=['follow','custom','hold'][self.app_mode.get_selected()]
        old=self.value['flatpak'].get(self.active_app,{})
        self.value['flatpak'][self.active_app]={'mode':mode}
        if mode=='custom':self.value['flatpak'][self.active_app]['surface']=copy.deepcopy(old.get('surface',self.value['common']))
        self.open_app(self.active_app);self.changed()

    def app_surface_changed(self,key,value):
        if self.updating or not self.active_app:return
        self.value['flatpak'][self.active_app]['surface'][key]=value;self.changed()

    def validate_inputs(self):
        if self.common_color.has_css_class('error') or self.target_color.has_css_class('error') or self.app_color.has_css_class('error'):
            raise ValueError(_('Enter material colors in #RRGGBB format before continuing.'))

    def request(self):
        self.validate_inputs()
        return {'profile':profile.validate(self.value),'apps':[]}

    def review(self):
        if self.busy:return
        try: request=self.request()
        except ValueError as error:self.error({'error':{'message':str(error)}});return
        self.set_busy(True,_('Checking planned changes'))
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):self.error(response);return
            result=response['result'];token=result['manager']['token']
            self.plan=copy.deepcopy(request)
            scope_notes='\n'.join(sorted({message(r['note']) for r in result['manager']['apps'] if r.get('note')}))
            d=Adw.AlertDialog(heading=_('Apply Changes'),body=_('The desktop theme will be changed.\nFlatpak apps using common or custom settings: {count}.\nDeferred: {deferred}. GDM is not included.\nRestart apps or log in again as needed.').format(
                count=sum(r.get('status')=='planned' for r in result['manager']['apps']),
                deferred=sum(r.get('status')=='deferred' for r in result['manager']['apps']))+('\n'+scope_notes if scope_notes else ''))
            d.add_response('cancel',_('Cancel'));d.add_response('apply',_('Apply'));d.set_response_appearance('apply',Adw.ResponseAppearance.SUGGESTED)
            d.set_default_response('cancel');d.set_close_response('cancel')
            def selected(dialog,response):
                if response=='apply':self.perform('set',dict(request,plan_token=token))
            d.connect('response',selected);d.present(self)
        self.adapter.call('plan',request,done)

    def review_remove(self):
        if self.busy:return
        self.set_busy(True,_('Checking removal plan'))
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):self.error(response);return
            self.confirm_operation('remove',_('Restore Previous Settings'),_('Remove the desktop theme and managed Flatpak styling. GDM and all backups are retained.'), {'plan_token':response['result']['manager']['token']})
        self.adapter.call('plan',None,done,operation='remove')

    def confirm_operation(self,action,title,body,request=None):
        d=Adw.AlertDialog(heading=title,body=body);d.add_response('cancel',_('Cancel'));d.add_response('yes',title)
        d.set_default_response('cancel');d.set_close_response('cancel')
        d.connect('response',lambda unused,r:self.perform(action,request) if r=='yes' else None);d.present(self)

    def perform(self,action,request):
        if self.busy:return
        self.set_busy(True,_('Working. Please wait for completion or recovery.'))
        def done(response):
            self.set_busy(False)
            if not response.get('ok'):self.error(response);return
            if action=='set':self.applied=copy.deepcopy(request['profile'])
            self.reload()
            deferred=[r for r in response.get('result',{}).get('manager',{}).get('apps',[]) if r.get('status')=='deferred']
            if deferred:self.pending_result=_('Some Flatpak apps were deferred: {apps}').format(
                apps=_(', ').join(_('{app} ({reason})').format(app=r['app'],reason=message(r['reason'])) for r in deferred))
        self.adapter.call(action,request,done)

    def save_profile(self,*unused):
        try:
            self.validate_inputs()
            data=profile.canonical(self.value)
            # Profile data is separate from the engine's appearance ownership.
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):
                raise ValueError(_('Cannot save through a symbolic link.'))
            self.config.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if any(p.is_symlink() for p in (self.config,*self.config.parents)):
                raise ValueError(_('Cannot save through a symbolic link.'))
            fd,path=tempfile.mkstemp(prefix='.profile-',dir=self.config.parent)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.replace(path,self.config)
            finally:
                if os.path.exists(path):os.unlink(path)
            self.notice.set_title(_('Profile saved. It has not been applied to your desktop.'))
        except Exception as error:self.error({'error':{'message':str(error)}})

    def cancel_edit(self,*unused):
        self.value=copy.deepcopy(self.applied or profile.defaults());self.sync_form()

    def reset_defaults(self,*unused):
        self.value=profile.reset_material(self.value);self.sync_form()

    def close_request(self,*unused):
        if self.busy:
            self.notice.set_title(_('Keep this window open until the operation completes. The journal is retained if interrupted.'));return True
        if self.initialized and (self.value != (self.applied or profile.defaults()) or self.gdm_view.dirty):
            d=Adw.AlertDialog(heading=_('Unapplied Edits'),body=_('Unsaved edits will be discarded when you close this window. Your desktop will not be changed.'))
            d.add_response('cancel',_('Keep Editing'));d.add_response('close',_('Close'));d.set_close_response('cancel')
            def selected(unused,r):
                if r=='close':self.initialized=False;self.close()
            d.connect('response',selected);d.present(self);return True
        self.stop_watch()
        return False


class Application(Adw.Application):
    def __init__(self,test_root=None):
        super().__init__(application_id=APP_ID,flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.test_root=test_root;self.window=None
        self.set_resource_base_path('/io/github/NBE03xxx/Hyalune/Settings')
    def do_activate(self):
        if self.window is None:self.window=Window(self,self.test_root)
        self.window.present()


def main():
    p=argparse.ArgumentParser();p.add_argument('--test-root',type=Path);a=p.parse_args()
    if os.getuid()==0 or os.geteuid()!=os.getuid():p.error(_('Run as a regular user.'))
    GLib.set_application_name(_('Hyalune Settings'));Gtk.Window.set_default_icon_name(APP_ID)
    return Application(a.test_root).run([sys.argv[0]])
