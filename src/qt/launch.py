#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Launch only the selected apps with an ABI-matched, theme-aware decoration."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

NAME = 'io.github.NBE03xxx.Hyalune.QtAppearance'
APP = 'org.keepassxc.KeePassXC'
NATIVE_COMMANDS = {'mozc':'/usr/lib/mozc/mozc_tool','nextcloud':'/usr/bin/nextcloud'}


def command(app, arguments, prefix, env, manifest):
    key = {'mozc':'native5','nextcloud':'native6','keepassxc':'flatpak6'}[app]
    variant = manifest['variants'][key]
    options = []
    scope = '--'+manifest.get('flatpak_scope','system')
    if app == 'keepassxc':
        base = ['/usr/bin/flatpak','run',scope,'--branch=stable','--arch=x86_64',
                '--command=keepassxc','--file-forwarding']
        try:
            runtime = subprocess.check_output(['/usr/bin/flatpak','info',scope,'--show-runtime',APP],text=True,timeout=5).strip()
            location = subprocess.check_output(['/usr/bin/flatpak','info',scope,'--show-location',runtime],text=True,timeout=5).strip()
            core = Path(location)/'files/lib/x86_64-linux-gnu/libQt6Core.so.6'
        except (OSError,subprocess.SubprocessError):
            core = Path('/nonexistent')
    else:
        base = [NATIVE_COMMANDS[app]]
        core = Path('/usr/lib/x86_64-linux-gnu')/f'libQt{variant["major"]}Core.so.{variant["major"]}'
    matching = core.resolve().name == f'libQt{variant["major"]}Core.so.{variant["abi"]}'
    plugin = prefix/variant['path']
    compatible = matching and plugin.is_file() and env.get('QT_WAYLAND_DECORATION','') in ('','hyalune')
    if compatible:
        directory = str(plugin.parent.parent)
        if app == 'keepassxc':
            options = ['--filesystem='+directory+':ro','--talk-name='+NAME,
                       '--env=QT_PLUGIN_PATH='+directory+':/app/lib/plugins:/usr/lib/plugins',
                       '--env=QT_WAYLAND_DECORATION=hyalune']
        else:
            env['QT_PLUGIN_PATH'] = directory + (':'+env['QT_PLUGIN_PATH'] if env.get('QT_PLUGIN_PATH') else '')
            env['QT_WAYLAND_DECORATION'] = 'hyalune'
    else:
        print('Hyalune Qt: current ABI or decoration differs; using the original launcher environment.',file=sys.stderr)
    return [*base,*options,*([APP] if app=='keepassxc' else []),*arguments]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('app',choices=['mozc','nextcloud','keepassxc'])
    p.add_argument('arguments',nargs=argparse.REMAINDER)
    args=p.parse_args()
    prefix=Path(__file__).resolve().parent.parent
    manifest=json.loads((prefix/'manifest.json').read_text())
    env=os.environ.copy()
    arguments=args.arguments[1:] if args.arguments[:1]==['--'] else args.arguments
    argv=command(args.app,arguments,prefix,env,manifest)
    os.execvpe(argv[0],argv,env)


if __name__=='__main__':
    main()
