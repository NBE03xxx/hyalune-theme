# SPDX-License-Identifier: MIT
"""JSON v1 adapter. All appearance writes use the existing shared transaction engine."""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import uuid

from . import profile

ROOT = Path(__file__).resolve().parents[2]
STATE = '.local/state/glass50/installer-material-v1'
ACTIVE = STATE + '/active.json'


class OperationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message); self.code = code


def module(name):
    spec = importlib.util.spec_from_file_location('hyalune_' + name.replace('-', '_'), ROOT / 'tools' / (name + '.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def environment():
    # A private GUI may have a separate HOME. The existing CLI's explicit test
    # root, not inherited XDG variables, controls where it may write.
    real = Path(pwd.getpwuid(os.getuid()).pw_dir)
    os.environ.update(HOME=str(real), XDG_CONFIG_HOME=str(real/'.config'),
                      XDG_DATA_HOME=str(real/'.local/share'), XDG_STATE_HOME=str(real/'.local/state'),
                      GSETTINGS_BACKEND='dconf')
    return real


def discovery_environment():
    result = os.environ.copy(); real = Path(pwd.getpwuid(os.getuid()).pw_dir)
    result.update(HOME=str(real), XDG_CONFIG_HOME=str(real/'.config'),
                  XDG_DATA_HOME=str(real/'.local/share'), XDG_STATE_HOME=str(real/'.local/state'),
                  GSETTINGS_BACKEND='dconf')
    return result


def prepare(args, package):
    real = module('desktop-context').guard(restoring=args.action in ('status', 'remove', 'recover', 'history', 'undo'))
    m = module('manage-material'); c = m.core
    action = {'set': 'update', 'sync': 'update', 'plan': 'plan'}.get(args.action, args.action)
    a = SimpleNamespace(action=action, operation='update', package=str(package), test_root=args.test_root,
                        blur='keep', settings='discard', adopt_preview=None,
                        fail_after=args.fail_after, crash_after=args.crash_after, crash_after_commit=False)
    m.ARGS = a
    module('manage-desktop').configure(m, real)
    home = Path(args.test_root) if args.test_root else real
    if args.test_root:
        base = real / '.local/state/glass50/phase5-tests'
        if not home.is_absolute() or home == base or not home.is_relative_to(base) or '..' in home.parts:
            raise OperationError('invalid-test-root', '専用のVM試験領域を指定してください。')
        c.safe(home/'.manager-path-check')
    c.safe(home/ACTIVE); owner = json.loads((home/ACTIVE).read_text()) if (home/ACTIVE).exists() else None
    a.operation = 'update' if owner else 'apply'
    if args.action == 'set': a.action = a.operation
    if args.action == 'plan' and args.operation == 'remove': a.operation = 'remove'
    if args.test_root:
        os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home/'.config'),
                          XDG_DATA_HOME=str(home/'.local/share'), XDG_STATE_HOME=str(home/'.local/state'),
                          GSETTINGS_BACKEND='keyfile')
    # Existing adapter uses a.test_root to avoid contacting/altering live Shell.
    return m, a, home, owner


def load_record(core, path):
    value = core.snapshot(path)
    return json.loads(core.contents(value)) if value else None


def known_profile(m, owner):
    if not owner: return None, 'not-installed'
    manager = owner.get('manager')
    if manager:
        value = profile.validate(manager['profile'])
        if manager.get('profile_sha256') != profile.digest(value):
            raise OperationError('invalid-profile-record', '所有記録のプロファイルを照合できません。')
        return value, 'managed-profile'
    # Only identify the fixed release when all four theme payloads match.
    expected = {m.theme_target(n, legacy=not any(n.startswith(m.SHELL_THEME) for n in owner.get('installed', {}))): hashlib.sha256((ROOT/'build/Glass50-Material-Preview'/n).read_bytes()).hexdigest()
                for n in m.THEME_FILES}
    if all(owner.get('package_files', {}).get(n) == h for n, h in expected.items()):
        value = profile.defaults()
        value['blur'] = {k: owner['settings_installed'].get(alias) == 'true'
                         for k, alias in [('quick_settings', 'effect-enabled'), ('windows', 'window-material-enabled')]}
        return value, 'fixed-release'
    return None, 'unidentified-fixed-values'


def settings(m):
    return m.Settings(Path(pwd.getpwuid(os.getuid()).pw_dir))


def inspect(args):
    m, a, home, owner = prepare(args, ROOT/'manager-base')
    # Schema lookup for existing installations can use their own schema copy.
    if not Path(a.package).is_dir():
        a.package = str(home)
        source = home/m.EXT/'schemas'
        # Settings also searches the installed real-home schema. A new test
        # root has no schema until the bundled base is prepared.
    base = ROOT/'manager-base'
    if not base.exists():
        # In a checkout there is no bundled base. A temporary base only supplies
        # schemas; it does not touch the user's configuration or ownership.
        with tempfile.TemporaryDirectory(prefix='hyalune-read-') as temp:
            make_base(Path(temp)/'package')
            a.package = str(Path(temp)/'package')
            return inspect_values(args, m, a, home, owner)
    return inspect_values(args, m, a, home, owner)


def inspect_values(args, m, a, home, owner):
    c = m.core; s = settings(m)
    value, identification = known_profile(m, owner)
    conflicts = []
    external_color_scheme = None
    if owner:
        for name, expected in owner.get('installed', {}).items():
            if name not in m.TARGETS: raise OperationError('invalid-ownership', '未対応の所有記録です。')
            try:
                if c.snapshot(home/name) != expected: conflicts.append({'target': name, 'code': 'file-edited'})
            except ValueError: conflicts.append({'target': name, 'code': 'unsafe-path'})
        for name, expected in owner.get('desktop', {}).get('installed', {}).items():
            # Only the closed-list native adapter is allowed to interpret paths.
            if name not in c.FILES: raise OperationError('invalid-ownership', '未対応のデスクトップ所有対象です。')
            if c.snapshot(home/name) != expected: conflicts.append({'target': name, 'code': 'entry-edited'})
        for name, expected in owner.get('settings_installed', {}).items():
            if name != 'enabled-extensions' and s.get(name) != expected:
                if name == 'color-scheme':
                    # Explicit profile Apply already selects this preference.
                    # Report the difference without blocking that same action.
                    external_color_scheme = {'current': s.effective(name), 'installed': expected}
                else:
                    conflicts.append({'target': name, 'code': 'setting-edited'})
        expected_block = m.BEGIN + b'\n@import url("' + (home/m.THEME/'gtk-4.0/material.css').as_uri().encode() + b'");\n' + m.END
        data = c.contents(c.snapshot(home/c.CSS))
        if data.count(m.BEGIN) != 1 or data.count(m.END) != 1 or expected_block not in data:
            conflicts.append({'target': c.CSS, 'code': 'managed-import-edited'})
    discovery = module('flatpak-discovery')
    flatpak_env = discovery_environment()
    apps = discovery.scan(home, env=flatpak_env)
    if apps['available']:
        running = set(subprocess.check_output(['flatpak', 'ps', '--columns=application'], env=flatpak_env, text=True, timeout=20).splitlines())
        for row in apps['apps']:
            if row['app'] in running:
                row.update(status='deferred', reason='起動中です。終了後に再検出してください。')
            elif row['status'] == 'already-managed':
                child = discovery.app_module(); child.configure_targets(row['app']); child.ARGS = SimpleNamespace(app=row['app'])
                try:
                    child.make_plan(home, None, 'remove', Path('.'))
                    record = load_record(child.core, home/child.core.ACTIVE)
                    row['last_profile_sha256'] = record.get('manager', {}).get('profile_sha256')
                except (OSError, ValueError, KeyError, TypeError) as error:
                    row.update(status='conflict', reason=str(error))
    for row in apps['apps']:
        policy = (value or {}).get('flatpak',{}).get(row['app'],{'mode':'hold'})
        record = load_record(c,home/'.local/state/glass50/installer-flatpak-v1'/row['app']/'active.json')
        manager = (record or {}).get('manager',{})
        if value and value['format']==1 and manager.get('mode')=='common':policy={'mode':'follow'}
        row['policy']=policy
        row['applied_policy']=manager.get('policy')
        row['rendering_note']=manager.get('rendering_note','')
        row['needs_update']=bool(value and policy['mode']!='hold' and
                                 (manager.get('material_sha256')!=profile.app_material_digest(value,policy) or manager.get('policy')!=policy))
    legacy_pending = (home/'.local/state/glass50/installer-v1/pending.json').exists()
    from gi.repository import Gio
    globally_disabled = Gio.Settings.new('org.gnome.shell').get_boolean('disable-user-extensions')
    return {'managed': bool(owner), 'version': owner.get('version') if owner else None,
            'pending': (home/STATE/'pending.json').exists(), 'legacy_pending': legacy_pending,
            'conflicts': conflicts, 'external_color_scheme': external_color_scheme,
            'profile': value, 'identification': identification,
            'blur': {'quick_settings': s.effective('effect-enabled'), 'windows': s.effective('window-material-enabled')},
            'extension_enabled': m.UUID in s.effective('enabled-extensions'),
            'extensions_globally_disabled': globally_disabled,
            'flatpak': apps, 'runtime': {'code_loaded': 'not-verified', 'note': '配置状態です。実読み込みと実画面は別途確認してください。'},
            'gdm': {'status': 'explicit-privileged-check-required', 'opacity_default': .32},
            'history': history(m, home), 'home': str(home)}


def history(m, home):
    rows = []
    root = home/STATE/'transactions'
    if root.is_symlink(): raise OperationError('unsafe-history', '履歴へのリンクは使用できません。')
    if root.exists():
        for folder in sorted(root.iterdir(), reverse=True):
            if folder.is_symlink() or not folder.is_dir(): continue
            journal = load_record(m.core, folder/'journal.json'); result = load_record(m.core, folder/'result.json')
            if journal and result:
                rows.append({'id': journal['id'], 'at': journal['at'], 'action': journal['action'], 'status': result['status']})
    return sorted(rows, key=lambda row: row['at'], reverse=True)[:30]


def undo_plan(m, home, settings):
    rows = history(m, home)
    latest = next((row for row in rows if row['status'] == 'committed'), None)
    if not latest or latest['action'] not in ('apply', 'update'):
        raise OperationError('no-previous-apply', '戻せる直前の適用がありません。')
    if len(latest['id']) != 32 or any(c not in '0123456789abcdef' for c in latest['id']):
        raise OperationError('invalid-history', '履歴IDを確認できません。')
    journal = load_record(m.core, home/STATE/'transactions'/latest['id']/'journal.json')
    discovery = module('flatpak-discovery')
    m.core.FILES = tuple(discovery.recovery_paths(journal['operations'], set(m.core.FILES)|{m.core.CSS,m.core.ACTIVE}, m.core.KEYS))
    m.core.check_journal(journal)
    owner_op = next((op for op in journal['operations'] if op['kind']=='file' and op['name']==m.core.ACTIVE), None)
    before = json.loads(m.core.contents(owner_op['before'])) if owner_op and owner_op['before'] else None
    after = json.loads(m.core.contents(owner_op['after'])) if owner_op and owner_op['after'] else None
    if not before or not after or 'manager' not in after:
        raise OperationError('no-previous-apply', '既存導入への更新だけを直前の適用へ戻せます。初回はテーマ解除を使ってください。')
    if any(op['kind']=='file' and op['name'].startswith(m.EXT) and op['before']!=op['after'] for op in journal['operations']):
        raise OperationError('code-restore-required', '拡張コード更新は保存した旧パッケージから戻してください。プロファイルだけの更新は直前へ戻せます。')
    app_ids = set()
    for op in journal['operations']:
        if op['name'].startswith('.var/app/'): app_ids.add(op['name'].split('/')[2])
    if app_ids:
        running = set(subprocess.check_output(['flatpak','ps','--columns=application'],env=discovery_environment(),text=True,timeout=20).splitlines())
        if app_ids & running: raise OperationError('app-running','対象のFlatpakを閉じてから戻してください。')
    return [dict(op, before=op['after'], after=op['before']) for op in reversed(journal['operations'])]


def make_base(destination):
    bundled = ROOT/'manager-base'
    if bundled.is_dir(): shutil.copytree(bundled, destination)
    else:
        subprocess.run([sys.executable, str(ROOT/'tools/package-material.py'), '--directory', str(destination)],
                       check=True, stdout=subprocess.DEVNULL, timeout=30)


def package_profile(value, destination):
    make_base(destination)
    generated = profile.generate(value, ROOT/'src/scss', destination/'profile-output')
    manifest = json.loads((destination/'manifest.json').read_text())
    m = module('manage-material')
    for name in m.THEME_FILES:
        target = m.theme_target(name, legacy=m.theme_target(name) not in manifest['files'])
        data = (generated/name).read_bytes(); (destination/'payload'/target).write_bytes(data)
        manifest['files'][target] = hashlib.sha256(data).hexdigest()
    manifest['appearance'] = profile.variant(value)
    # Typed profile is additionally recorded in the same owned active.json.
    (destination/'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2)+'\n')
    return generated


def read_request(args):
    if args.request:
        path = Path(args.request)
        if path.stat().st_size > 65536: raise OperationError('invalid-request', '設定データが大きすぎます。')
        value = json.loads(path.read_text())
    else:
        value = json.load(sys.stdin)
    if args.action == 'remove':
        if not isinstance(value, dict) or set(value) != {'plan_token'} or not isinstance(value['plan_token'], str):
            raise OperationError('plan-required', '先に解除内容を確認してください。')
        return value
    allowed = {'profile', 'apps', 'plan_token'}
    if not isinstance(value, dict) or set(value)-allowed or 'profile' not in value:
        raise OperationError('invalid-request', '設定データの形式を確認してください。')
    value['profile'] = profile.validate(value['profile'])
    apps = value.get('apps', [])
    discovery = module('flatpak-discovery')
    if not isinstance(apps, list) or len(apps) > 256 or any(not isinstance(n, str) or not discovery.valid_id(n) for n in apps):
        raise OperationError('invalid-app', 'アプリIDを確認してください。')
    value['apps'] = sorted(set(apps))
    if args.action == 'set' and not isinstance(value.get('plan_token'), str):
        raise OperationError('plan-required', '先に変更内容を確認してください。')
    return value


def sync_context(args):
    """Read only committed values; drafts and GDM have no role in system sync."""
    from gi.repository import Gio
    m, a, home, owner = prepare(args, ROOT/'manager-base')
    shell = Gio.Settings.new('org.gnome.shell')
    paused = None
    if not owner: paused = 'not-managed'
    elif (home/STATE/'pending.json').exists(): paused = 'recovery-required'
    elif shell.get_boolean('disable-user-extensions'): paused = 'extensions-disabled'
    elif m.UUID not in shell.get_strv('enabled-extensions') or m.UUID in shell.get_strv('disabled-extensions'): paused = 'extension-disabled'
    elif m.core.USER_THEMES not in shell.get_strv('enabled-extensions') or m.core.USER_THEMES in shell.get_strv('disabled-extensions'): paused = 'user-themes-disabled'
    if paused: return None, {'status':'paused','reason':paused}
    value, _ = known_profile(m, owner)
    if value is None: return None, {'status':'paused','reason':'unidentified-profile'}
    s = settings(m); raw = s.get('color-scheme')
    mode = 'dark' if s.effective('color-scheme') == 'prefer-dark' else 'light'
    desired = profile.upgrade(value)
    if desired['format'] != 3:
        desired = profile.select_variant(profile.select_variant(desired, 'light'), 'dark')
    desired = profile.select_variant(desired, mode)
    retry_apps = False
    for app, policy in desired['flatpak'].items():
        if policy['mode'] == 'hold': continue
        record = load_record(m.core,home/'.local/state/glass50/installer-flatpak-v1'/app/'active.json') or {}
        retry_apps |= record.get('manager',{}).get('material_sha256') != profile.app_material_digest(desired,policy)
    if value == desired and not retry_apps:
        return None, {'status':'unchanged','variant':mode}
    args.sync_owner = m.core.snapshot(home/ACTIVE)
    args.sync_scheme = raw
    return {'profile':desired,'apps':[]}, None


def execute(args):
    request = read_request(args) if (args.action in ('plan', 'set') and args.operation != 'remove') or args.action == 'remove' else None
    if args.action == 'sync':
        request, result = sync_context(args)
        environment()
        if result is not None: return result
    with tempfile.TemporaryDirectory(prefix='hyalune-profile-') as temp:
        package = Path(temp)/'package'
        if request and 'profile' in request: generated = package_profile(request['profile'], package)
        else: make_base(package); generated = None
        m, a, home, owner = prepare(args, package); c = m.core
        a.manager_profile_apply = bool(request and 'profile' in request)
        a.system_appearance_sync = args.action == 'sync'
        if not args.test_root and args.action in ('set','sync','undo'):
            pids = subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip()
            if not pids.isdecimal():
                raise OperationError('private-shell-active','独立Shellの検証を終了してから通常テーマへ適用してください。')
        original_plan = c.make_plan
        discovery = module('flatpak-discovery')
        plan_info = {}

        def combined(h, s, operation, source):
            if args.action == 'sync':
                from gi.repository import Gio
                shell = Gio.Settings.new('org.gnome.shell')
                if shell.get_boolean('disable-user-extensions') or any(n not in shell.get_strv('enabled-extensions') or n in shell.get_strv('disabled-extensions') for n in (m.UUID,c.USER_THEMES)):
                    raise OperationError('sync-paused','拡張が停止したため明暗連動を中止しました。')
                if c.snapshot(h/ACTIVE) != args.sync_owner or s.get('color-scheme') != args.sync_scheme:
                    raise OperationError('stale-sync','明暗または編集値が変わりました。最新値で再試行します。')
            if args.action == 'undo':
                return undo_plan(m, h, s), ['Restore the exact previous native and selected Flatpak snapshots; initial restoration data remains owned.']
            app_ops, report = [], {'apps': []}
            if operation == 'remove':
                app_ops, report = discovery.prepare_removal(h, env=discovery_environment())
                c.composite_flatpak_removals = tuple(row['app'] for row in report['apps'])
            native_ops, notes = original_plan(h, s, operation, source)
            if request and 'profile' in request:
                # The same journal owns both preferences independently. Keep all
                # previous restoration fields and user-independent settings.
                desired = request['profile']; state_op = next(op for op in native_ops if op['kind']=='file' and op['name']==c.ACTIVE)
                after = json.loads(c.contents(state_op['after']))
                for key, alias in [('quick_settings','effect-enabled'), ('windows','window-material-enabled')]:
                    final = 'true' if desired['blur'][key] else 'false'
                    native_ops = [op for op in native_ops if not(op['kind']=='setting' and op['name']==alias)]
                    before = s.get(alias)
                    if before != final: native_ops.insert(0, {'kind':'setting','name':alias,'before':before,'after':final})
                    after['settings_installed'][alias] = final
                members = list(s.effective('enabled-extensions'))
                wants = True  # System appearance integration also runs without blur.
                if wants and m.UUID not in members: members.append(m.UUID)
                if not wants: members = [n for n in members if n != m.UUID]
                final = s.array(members) if members != s.effective('enabled-extensions') else s.get('enabled-extensions')
                native_ops = [op for op in native_ops if not(op['kind']=='setting' and op['name']=='enabled-extensions')]
                if final != s.get('enabled-extensions'):
                    native_ops.append({'kind':'setting','name':'enabled-extensions','before':s.get('enabled-extensions'),'after':final})
                after['settings_installed']['enabled-extensions'] = final; after['enabled_installed_effective'] = members
                after['manager'] = {'format':1, 'profile':desired, 'profile_sha256':profile.digest(desired)}
                state_op['after'] = c.image(c.canonical(after), 0o600)
                from . import flatpak
                try:
                    app_ops, report['apps'] = flatpak.prepare(h, desired, request['apps'], package/'flatpak-profiles', module, discovery_environment())
                except ValueError as error:
                    raise OperationError('app-unavailable',str(error)) from error
                after['manager'] = {'format':1,'profile':desired,'profile_sha256':profile.digest(desired)}
                state_op['after'] = c.image(c.canonical(after),0o600)
                native_ops.remove(state_op); native_ops.append(state_op)
                # User Themes watches its setting, not file contents. Refresh
                # the same managed CSS path inside the journal, including its
                # temporary state in rollback/recovery and plan-token checks.
                if owner and any(op['kind']=='file' and op['name'] in (m.theme_target('gnome-shell/gnome-shell.css'),m.THEME+'gnome-shell/gnome-shell.css') for op in native_ops) and not any(op['kind']=='setting' and op['name']=='shell-theme' for op in native_ops):
                    theme = s.get('shell-theme')
                    native_ops.extend([{'kind':'setting','name':'shell-theme','before':theme,'after':"''"},
                                       {'kind':'setting','name':'shell-theme','before':"''",'after':theme}])
                if owner and any(op['kind']=='file' and op['name']==m.THEME+'gtk-3.0/gtk.css' for op in native_ops) and not any(op['kind']=='setting' and op['name']=='gtk-theme' for op in native_ops):
                    theme = s.get('gtk-theme')
                    native_ops.extend([{'kind':'setting','name':'gtk-theme','before':theme,'after':"'Adwaita'"},
                                       {'kind':'setting','name':'gtk-theme','before':"'Adwaita'",'after':theme}])
                if args.action == 'sync' and any(op['kind']=='file' and op['name'].startswith(m.EXT) for op in native_ops):
                    raise OperationError('explicit-update-required','拡張コードの更新は明示的な適用で行ってください。')
            # Active native record is last, after all selected app changes.
            tail = [op for op in native_ops if op['kind']=='file' and op['name']==c.ACTIVE]
            native_ops = [op for op in native_ops if op not in tail]
            operations = [*native_ops,*app_ops,*tail]
            if args.action == 'sync': operations = [op for op in operations if op['before'] != op['after']]
            c.FILES = tuple(dict.fromkeys([*c.FILES,*(op['name'] for op in app_ops)]))
            token = hashlib.sha256(c.canonical({'operations':operations,'apps':report['apps']})).hexdigest()
            plan_info.update(token=token, apps=report['apps'], operation=operation,
                             profile_sha256=profile.digest(request['profile']) if request and 'profile' in request else None)
            if args.action == 'sync' and not operations:
                raise OperationError('sync-no-changes','保留中のアプリ以外に変更はありません。')
            if args.action in ('set', 'remove') and token != request['plan_token']:
                raise OperationError('stale-plan', '確認後に状態が変わりました。もう一度変更内容を確認してください。')
            return operations, notes

        c.make_plan = combined
        c.plan_extra = lambda: {'manager':plan_info}
        c.result_extra = lambda: {'manager':{**plan_info,'apps':[{**row,'status':'applied' if row.get('status')=='planned' else row.get('status','removed')} for row in plan_info.get('apps',[])]}, 'reflection':{'shell':'relogin-or-theme-reload', 'gtk':'restart-apps', 'code_loaded':'not-verified'}}
        if args.action == 'recover' and (home/STATE/'pending.json').exists():
            journal = load_record(c,home/STATE/'pending.json')
            c.FILES = tuple(discovery.recovery_paths(journal['operations'], set(c.FILES)|{c.CSS,c.ACTIVE}, c.KEYS))
        stream = io.StringIO()
        environment()  # core.run sets the explicit test backend after its guard.
        try:
            with contextlib.redirect_stdout(stream): c.run(a)
        except OperationError as error:
            if error.code != 'sync-no-changes': raise
            return {'status':'deferred','manager':plan_info}
        return json.loads(stream.getvalue())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['status','plan','set','sync','remove','recover','undo'])
    p.add_argument('--request'); p.add_argument('--operation', choices=['set','remove'], default='set')
    p.add_argument('--test-root'); p.add_argument('--fail-after', type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument('--crash-after', type=int, default=0, help=argparse.SUPPRESS)
    args = p.parse_args(); operation_id = uuid.uuid4().hex
    response = {'api':'hyalune.settings', 'version':1, 'operation_id':operation_id, 'action':args.action}
    try:
        if os.getuid() == 0 or os.geteuid() != os.getuid(): raise OperationError('user-required','通常ユーザーで起動してください。')
        environment()
        response.update(ok=True, result=inspect(args) if args.action=='status' else execute(args))
        exit_code = 0
    except Exception as error:
        code = 'resource-busy' if isinstance(error, BlockingIOError) else 'operation-failed'
        response.update(ok=False, error={'code':getattr(error,'code',code), 'message':str(error),
                                        'recovery':'既存CLIと所有記録を保持しています。中断時はrecoverを先に実行してください。'})
        exit_code = 1
    print(json.dumps(response,ensure_ascii=False,sort_keys=True,indent=2))
    return exit_code
