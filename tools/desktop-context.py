#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only desktop capability checks; no machine, disk or fixed UID identity."""
import os
from pathlib import Path
import platform
import pwd
import re


def validate(facts, restoring=False):
    if facts['uid'] == 0 or facts['euid'] != facts['uid']:
        raise ValueError('通常のデスクトップユーザーで実行してください（sudo不可）。')
    if not facts['home_valid']:
        raise ValueError('ユーザーHOMEの所有者・実体・書き込み権限を確認してください。')
    if not facts['session_bus']:
        raise ValueError('このユーザーのD-Busセッションへ接続できません。')
    if not restoring:
        if (facts['os_id'], facts['os_version']) != ('ubuntu', '26.04'):
            raise ValueError('このOSは動作未確認です。現在の導入対象はUbuntu 26.04です。')
        if not re.fullmatch(r'50\.\d+(?:\.\d+)?', facts['shell_version'] or ''):
            raise ValueError('導入には実行中のGNOME Shell 50.xが必要です。')
        if not facts['wayland_session']:
            raise ValueError('このユーザーのアクティブなGNOME Waylandセッションが必要です。')
    return facts


def inspect():
    from gi.repository import Gio, GLib
    uid = os.getuid(); home = Path(pwd.getpwuid(uid).pw_dir)
    info = platform.freedesktop_os_release()
    home_valid = (home.is_absolute() and home != Path('/') and home.is_dir() and
                  home.stat().st_uid == uid and os.access(home, os.W_OK | os.X_OK) and
                  not any(p.is_symlink() for p in (home, *home.parents)))
    facts = dict(uid=uid, euid=os.geteuid(), home=str(home), home_valid=home_valid,
                 os_id=info.get('ID'), os_version=info.get('VERSION_ID'), session_bus=False,
                 shell_version='', shell_pid=None, wayland_session=False)
    # Do not let an alternate HOME/backend make a normal invocation look private.
    for key, expected in {'HOME':home, 'XDG_CONFIG_HOME':home/'.config',
                          'XDG_DATA_HOME':home/'.local/share', 'XDG_STATE_HOME':home/'.local/state'}.items():
        if os.environ.get(key) and Path(os.environ[key]) != expected:
            raise ValueError('Nonstandard ' + key + '; normal installation uses the user HOME and default XDG directories.')
    if os.environ.get('GSETTINGS_BACKEND') not in (None, 'dconf'):
        raise ValueError('Normal installation requires dconf; private tests use --test-root.')
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None); facts['session_bus'] = True
    try:
        version = bus.call_sync('org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions',
            'org.freedesktop.DBus.Properties', 'Get', GLib.Variant('(ss)',
            ('org.gnome.Shell.Extensions', 'ShellVersion')), None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        facts['shell_version'] = version
        pid = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'GetConnectionUnixProcessID', GLib.Variant('(s)', ('org.gnome.Shell',)), None,
            Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        proc = Path('/proc')/str(pid)
        if proc.stat().st_uid != uid or (proc/'comm').read_text().strip() != 'gnome-shell':
            raise ValueError('GNOME Shell must belong to the invoking user.')
        facts['shell_pid'] = str(pid)
    except GLib.Error:
        pass
    try:
        system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        sessions = system.call_sync('org.freedesktop.login1', '/org/freedesktop/login1',
            'org.freedesktop.login1.Manager', 'ListSessions', None, None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        for _, owner, _, _, path in sessions:
            if owner != uid: continue
            props = system.call_sync('org.freedesktop.login1', path, 'org.freedesktop.DBus.Properties',
                'GetAll', GLib.Variant('(s)', ('org.freedesktop.login1.Session',)), None,
                Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
            if props.get('Type') == 'wayland' and props.get('State') == 'active' and props.get('Class') == 'user':
                facts['wayland_session'] = bool(facts['shell_pid']); break
    except GLib.Error:
        pass
    return facts


def guard(restoring=False):
    if os.getuid()==0 or os.geteuid()!=os.getuid():
        raise ValueError('通常のデスクトップユーザーで実行してください（sudo不可）。')
    try:
        facts = validate(inspect(), restoring=restoring)
    except ImportError as error:
        raise ValueError('Python3のPyGObject / Gio (python3-gi)が必要です。') from error
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('デスクトップ環境の読み取り確認に失敗しました: '+str(error)) from error
    return Path(facts['home'])
