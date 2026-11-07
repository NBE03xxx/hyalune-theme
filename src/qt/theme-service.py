#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only session service for the Qt decoration's current Shell-theme policy."""
import json
from pathlib import Path

from gi.repository import Gio, GLib

NAME = 'io.github.NBE03xxx.Hyalune.QtAppearance'
OBJECT = '/io/github/NBE03xxx/Hyalune/QtAppearance'
SHELL = 'org.gnome.Shell'
SHELL_OBJECT = '/org/gnome/Shell'
EXTENSIONS = 'org.gnome.Shell.Extensions'
USER_THEMES = 'user-theme@gnome-shell-extensions.gcampax.github.com'
THEMES = {'Hyalune', 'Glass50-Dark', 'Glass50-Material-Preview', 'Hyalune-Light'}
XML = f'''<node><interface name="{NAME}">
<method name="IsActive"><arg name="active" type="b" direction="out"/></method>
<method name="GetState"><arg name="active" type="b" direction="out"/><arg name="reason" type="s" direction="out"/></method>
<method name="Quit"/>
<signal name="ActiveChanged"><arg name="active" type="b"/></signal>
</interface></node>'''


def user_theme_settings():
    source = Gio.SettingsSchemaSource.get_default()
    for root in [Path.home()/'.local/share/gnome-shell/extensions', Path('/usr/share/gnome-shell/extensions')]:
        directory = root / USER_THEMES / 'schemas'
        if (directory/'gschemas.compiled').is_file():
            source = Gio.SettingsSchemaSource.new_from_directory(str(directory), source, False)
            break
    schema = source.lookup('org.gnome.shell.extensions.user-theme', True)
    return Gio.Settings.new_full(schema, None, None) if schema else None


class ThemeService:
    def __init__(self, bus, loop):
        self.bus = bus
        self.loop = loop
        self.active = False
        self.reason = 'starting'
        self.generation = 0
        self.theme = user_theme_settings()
        self.shell = Gio.Settings.new('org.gnome.shell')
        self.a11y = Gio.Settings.new('org.gnome.desktop.a11y.interface')
        for settings, keys in [(self.shell, ['enabled-extensions', 'disabled-extensions', 'disable-user-extensions']),
                               (self.a11y, ['high-contrast'])]:
            for key in keys:
                settings.connect('changed::'+key, self.refresh)
        if self.theme:
            self.theme.connect('changed::name', self.refresh)
        state = Path.home()/'.local/state/hyalune/qt-installer-v1'
        self.owner = state/'active.json'
        self.monitor = Gio.File.new_for_path(str(state)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect('changed', self.refresh)
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self.registration = bus.register_object(OBJECT, info, self.method, None, None)
        self.subscription = bus.signal_subscribe(SHELL, EXTENSIONS,
            'ExtensionStateChanged', SHELL_OBJECT, USER_THEMES,
            Gio.DBusSignalFlags.NONE, self.refresh)
        self.watch = Gio.bus_watch_name_on_connection(bus, SHELL,
            Gio.BusNameWatcherFlags.NONE, self.refresh, self.shell_gone)
        self.refresh()

    def method(self, connection, sender, path, interface, method, parameters, invocation):
        if method == 'IsActive':
            invocation.return_value(GLib.Variant('(b)', (self.active,)))
        elif method == 'GetState':
            invocation.return_value(GLib.Variant('(bs)', (self.active, self.reason)))
        elif method == 'Quit':
            invocation.return_value(None)
            GLib.idle_add(self.loop.quit)

    def publish(self, active, reason):
        changed = self.active != active
        self.active, self.reason = active, reason
        if changed:
            self.bus.emit_signal(None, OBJECT, NAME, 'ActiveChanged', GLib.Variant('(b)', (active,)))

    def shell_gone(self, *unused):
        self.generation += 1
        self.publish(False, 'shell-unavailable')

    def inactive_reason(self):
        try:
            owner = json.loads(self.owner.read_text())
            if owner.get('component') != 'hyalune-qt':
                return 'not-managed'
        except (OSError, ValueError):
            return 'not-managed'
        if (self.owner.parent/'pending.json').exists():
            return 'transaction-pending'
        if not self.theme or self.theme.get_string('name') not in THEMES:
            return 'other-shell-theme'
        name = self.theme.get_string('name')
        roots = [Path.home()/'.themes', Path.home()/'.local/share/themes',
                 *(Path(directory)/'themes' for directory in GLib.get_system_data_dirs())]
        if not any((root/name/'gnome-shell/gnome-shell.css').is_file() for root in roots):
            return 'shell-theme-missing'
        if self.a11y.get_boolean('high-contrast'):
            return 'high-contrast'
        if self.shell.get_boolean('disable-user-extensions'):
            return 'extensions-disabled'
        if USER_THEMES not in self.shell.get_strv('enabled-extensions') or USER_THEMES in self.shell.get_strv('disabled-extensions'):
            return 'user-themes-disabled'
        return None

    def refresh(self, *unused):
        self.generation += 1
        generation = self.generation
        reason = self.inactive_reason()
        if reason:
            self.publish(False, reason)
            return
        self.bus.call(SHELL, SHELL_OBJECT, EXTENSIONS, 'GetExtensionInfo', GLib.Variant('(s)', (USER_THEMES,)),
            None, Gio.DBusCallFlags.NO_AUTO_START, 3000, None,
            lambda connection, result: self.extension_info(connection, result, generation))

    def extension_info(self, connection, result, generation):
        if generation != self.generation:
            return
        try:
            state = connection.call_finish(result).unpack()[0].get('state')
            active = state == 1 and self.inactive_reason() is None
            self.publish(active, 'hyalune' if active else 'user-themes-inactive')
        except GLib.Error:
            self.publish(False, 'shell-unavailable')


def main():
    loop = GLib.MainLoop()
    instances = []
    def acquired(connection, name):
        instances.append(ThemeService(connection, loop))
    owner = Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
        acquired, None, lambda *unused: loop.quit())
    try:
        loop.run()
    finally:
        Gio.bus_unown_name(owner)


if __name__ == '__main__':
    main()
