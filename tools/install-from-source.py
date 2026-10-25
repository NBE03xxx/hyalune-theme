#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install from a git checkout, including detected GTK Flatpaks at initial apply."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
import subprocess


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def main():
    if sys.argv[1:2] == ['gdm']:
        return subprocess.call([sys.executable, str(Path(__file__).with_name('manage-gdm.py')), *sys.argv[2:]])
    if sys.argv[1:2] == ['flatpak']:
        return subprocess.call([sys.executable, str(Path(__file__).with_name('manage-flatpak.py')), *sys.argv[2:]])
    p = argparse.ArgumentParser(prog='install.sh', description=
        'git cloneしたソースから導入します。初回は検出したGTK系Flatpakにも適用します。', epilog=
        './install.sh plan; ./install.sh apply --blur on; ./install.sh flatpak scan')
    p.add_argument('action', nargs='?', choices=['layers', 'plan', 'apply', 'update', 'remove', 'recover', 'status', 'flatpak', 'gdm'])
    p.add_argument('--target', choices=['desktop', 'vm', 't16-trial'], default='desktop', help=argparse.SUPPRESS)
    p.add_argument('--operation', choices=['apply', 'update', 'remove'], default='apply')
    p.add_argument('--blur', choices=['keep', 'on', 'off'], default='keep')
    p.add_argument('--flatpak', choices=['existing', 'none'], default='existing', help='初回導入時の既存GTK系Flatpakへの適用（既定existing）')
    p.add_argument('--adopt-preview')
    p.add_argument('--settings', choices=['keep', 'discard'], default='discard',
                   help='remove時のGlass50効果設定: keep=保持、discard=導入前へ復元（既定）。保全記録は削除しません')
    p.add_argument('--test-root', help=argparse.SUPPRESS)
    p.add_argument('--fail-after', type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument('--crash-after', type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument('--crash-after-commit', action='store_true', help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.action is None: p.print_help(); return 0
    if a.settings != 'discard' and (a.operation if a.action == 'plan' else a.action) != 'remove':
        p.error('--settings keep is only available for remove or plan --operation remove')
    project = Path(__file__).resolve().parent.parent
    source_manager = project / 'tools/manage-material.py'
    if a.action == 'layers':
        info = json.loads(subprocess.check_output([sys.executable, str(source_manager), 'layers'], text=True))
        # User-package metadata stays compatible; the separate root preview is
        # advertised only by the source entry, never added to its payload.
        info['separate_gdm_preview'] = {'entry': './install.sh gdm --help', 'scope': 'system-login',
                                        'status': 'kvm-and-t16-trial', 'included_in_apply_remove': False}
        print(json.dumps(info, indent=2)); return 0
    template = module(source_manager, 'source_material')
    if a.target == 't16-trial': module(project / 'tools/manage-t16.py', 't16_template').configure(template)
    desktop = module(project / 'tools/manage-desktop.py', 'desktop_template')
    operation = a.operation if a.action == 'plan' else a.action
    real_home = desktop.context().guard(restoring=operation in ('remove','recover','status'))
    # Historical flags cannot bypass the common capability checks. The trial
    # alias additionally keeps its old identity guard for legacy callers.
    if a.target == 't16-trial': template.core.guard()

    environment = os.environ.copy()

    def run(package):
        subprocess.run([sys.executable, str(project / 'tools/package-material.py'),
                        '--directory', str(package)], check=True, stdout=subprocess.DEVNULL)
        m = module(package / 'manage-material.py', 'prepared_material')
        a.package = str(package); m.ARGS = a
        if a.target == 't16-trial': module(package / 'manage-t16.py', 't16_prepared').configure(m)
        else: module(package / 'manage-desktop.py', 'desktop_prepared').configure(m,real_home)
        if not a.test_root and (a.operation if a.action=='plan' else a.action) not in ('remove','recover','status') and not subprocess.check_output(['pgrep', '-u', str(os.getuid()), '-x', 'gnome-shell'], text=True).strip().isdecimal():
            m.core.fail('Normal Shell must be unique; finish private Shell probes first.')
        m.load_package(package)
        discovery = module(project / 'tools/flatpak-discovery.py', 'flatpak_discovery')
        # Recovery must not depend on today's installed app list or detection.
        home = Path(a.test_root) if a.test_root else real_home
        pending = home / m.core.STATE / 'pending.json'; m.core.safe(pending)
        if a.action == 'recover' and pending.exists():
            journal = json.loads(pending.read_text())
            native = set(m.core.FILES) | {m.core.CSS, m.core.ACTIVE}
            m.core.FILES = tuple(discovery.recovery_paths(journal['operations'], native, m.core.KEYS))
        action = a.operation if a.action == 'plan' else a.action
        if action == 'remove':
            base_plan = m.core.make_plan
            removal_report = {}
            def combined_remove(home, settings, operation, package):
                nonlocal removal_report
                app_ops, removal_report = discovery.prepare_removal(home, env=environment)
                m.core.composite_flatpak_removals = tuple(row['app'] for row in removal_report['apps'])
                try:
                    native_ops, notes = base_plan(home, settings, operation, package)
                finally:
                    m.core.composite_flatpak_removals = ()
                m.core.FILES = tuple(dict.fromkeys([*m.core.FILES, *(op['name'] for op in app_ops)]))
                notes += ['Managed Flatpak apps are scanned and restored with the desktop in one transaction.']
                return [*app_ops, *native_ops], notes
            m.core.make_plan = combined_remove
            m.core.plan_extra = lambda: {'flatpak_remove': removal_report}
            m.core.result_extra = lambda: {'flatpak_remove': {
                'apps': [{**row, 'status': 'removed'} for row in removal_report['apps']],
                'summary': {'removed': len(removal_report['apps'])}}}
        if action == 'apply' and a.flatpak == 'existing':
            source = package / 'flatpak-source'
            for name in ['gtk-3.0/gtk.css', 'gtk-4.0/flatpak.css']:
                src = project / 'build/Glass50-Material-Preview' / name; m.core.safe(src)
                dest = source / name; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dest)
            base_plan = m.make_plan; report = {}
            def combined(home, settings, operation, package):
                nonlocal report
                native_ops, notes = base_plan(home, settings, operation, package)
                app_ops, report = discovery.prepare(home, source, discovery.scan(home, env=environment))
                report['enabled'] = True
                report['record_kind'] = 'initial-installation-report'
                m.core.FILES = tuple(dict.fromkeys([*m.core.FILES, *(op['name'] for op in app_ops)]))
                # Keep the base ownership record last, after every per-app record.
                active = next((op for op in native_ops if op['kind'] == 'file' and op['name'] == m.core.ACTIVE), None)
                if active is None: m.core.fail('Missing initial base ownership operation')
                native_ops.remove(active)
                data = json.loads(m.core.contents(active['after'])); data['flatpak_auto'] = completed_report()
                active['after'] = m.core.image(m.core.canonical(data), 0o600)
                notes += ['Initial installation includes detected GTK Flatpaks. Deferred/conflicting/unknown apps are listed, not claimed as applied.']
                return [*native_ops, *app_ops, active], notes
            def completed_report():
                result = json.loads(json.dumps(report))
                for row in result.get('apps', []):
                    if row['status'] == 'planned': row['status'] = 'applied'
                result['summary'] = dict(result.get('summary', {}))
                result['summary']['applied'] = result['summary'].pop('planned', 0)
                return result
            m.core.make_plan = combined
            m.core.plan_extra = lambda: {'flatpak_auto': report}
            m.core.result_extra = lambda: {'flatpak_auto': completed_report()}
        m.core.run(a)
        return 0

    if a.action in ['apply', 'update', 'remove'] and not a.test_root:
        parent = real_home / '.local/state/glass50/source-packages'
        for node in (parent, *parent.parents):
            if node.is_symlink(): template.core.fail('Source snapshot parent is a symlink: ' + str(node))
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        package = parent / uuid.uuid4().hex
        print('Source installation snapshot: ' + str(package), file=sys.stderr)
        return run(package)
    with tempfile.TemporaryDirectory(prefix='glass50-source-') as directory:
        return run(Path(directory) / 'package')


if __name__ == '__main__':
    try: sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Glass50 source installer: ' + str(error), file=sys.stderr); sys.exit(1)
