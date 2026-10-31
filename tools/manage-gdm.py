#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independent, opt-in GDM resources for supported Ubuntu/GNOME environments."""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

GROUP = 'gdm-theme.gresource'
LINK = '/usr/share/gnome-shell/gdm-theme.gresource'
STATE = Path('/var/lib/hyalune-gdm')
ASSETS = Path('/usr/local/share/hyalune/gdm')
PREFIX = '/org/gnome/shell/theme/'
VERSION = '0.3.2'


def call(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Absolute, bounded path required')
    for node in (path, *path.parents):
        if node.is_symlink():
            raise ValueError('Symlink is not permitted: ' + str(node))
    return path


def write(path, data, mode=0o600):
    safe(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='.hyalune-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), mode); f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        syncdir(path.parent)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def save(path, obj):
    write(path, (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode())


def read(path):
    safe(path)
    return json.loads(path.read_text()) if path.exists() else None


def validate_environment(os_id, os_version, shell_version, loader):
    """Bound new changes by the OS and actual resource loader, not hardware."""
    if os_id != 'ubuntu' or os_version != '26.04':
        raise ValueError('Ubuntu 26.04 is required')
    if re.fullmatch(r'50\.\d+(?:\.\d+)?', shell_version) is None:
        raise ValueError('GNOME Shell 50.x is required')
    if b"themeResourceName: 'gdm-theme.gresource'" not in loader or b"stylesheetName: 'gdm.css'" not in loader:
        raise ValueError('Unsupported Ubuntu GDM resource loader')


def guard(restoring=False):
    if os.geteuid() != 0:
        raise ValueError('GDM管理はrootが必要です: sudo ./install.sh gdm ...（通常applyはsudo不要）')
    if not restoring:
        info = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        version = call('gnome-shell', '--version').split()[-1]
        loader = subprocess.check_output(['gresource', 'extract', '/usr/lib/gnome-shell/libshell-18.so', '/org/gnome/shell/ui/sessionMode.js'])
        validate_environment(info.get('ID', '').strip('"'), info.get('VERSION_ID', '').strip('"'), version, loader)
    # Restoration can survive an OS upgrade; owned assets, alternatives and
    # source hashes are still rechecked by the transaction/recovery engine.
    for p in (STATE, ASSETS): safe(p)


def alternatives():
    raw = call('update-alternatives', '--query', GROUP)
    head, *blocks = raw.split('\n\n')
    h = dict(line.split(': ', 1) for line in head.splitlines() if ': ' in line)
    candidates = {}
    for b in blocks:
        row = dict(line.split(': ', 1) for line in b.splitlines() if ': ' in line)
        if 'Alternative' in row:
            if 'Slaves:' in b: raise ValueError('Alternative slaves are unsupported')
            candidates[row['Alternative']] = int(row['Priority'])
    if h.get('Link') != LINK or not candidates or h.get('Status') not in ('auto', 'manual'):
        raise ValueError('Unexpected alternatives group')
    return {'mode': h['Status'], 'value': h['Value'], 'candidates': candidates}


def source_image(path):
    p = Path(path)
    if not p.is_absolute() or p.is_symlink() or not p.is_file():
        raise ValueError('Source resource must be a regular absolute file')
    return {'path': str(p), 'sha256': digest(p.read_bytes())}


MAX_BACKGROUND = 64 * 1024 * 1024
BACKGROUND_NAMES = ('hyalune-background.svg', 'hyalune-background.png')


def initiating_user(name=None):
    """Resolve the authenticated sudo caller, never guess a logged-in account."""
    if os.geteuid() == 0:
        sudo_uid = os.environ.get('SUDO_UID')
        if sudo_uid is not None:
            if not sudo_uid.isdecimal() or int(sudo_uid) == 0:
                raise ValueError('A normal desktop sudo caller is required')
            user = pwd.getpwuid(int(sudo_uid))
            if name and name != user.pw_name:
                raise ValueError('--desktop-user does not match the sudo caller')
            if os.environ.get('SUDO_USER', user.pw_name) != user.pw_name:
                raise ValueError('Inconsistent sudo caller identity')
        elif name:
            user = pwd.getpwnam(name)
        else:
            raise ValueError('Run from the desktop user with sudo, or specify --desktop-user for a root console')
    else:
        user = pwd.getpwuid(os.getuid())
        if name and name != user.pw_name:
            raise ValueError('Cannot capture another desktop user')
    if user.pw_uid == 0 or not Path(user.pw_dir).is_dir():
        raise ValueError('A normal desktop user with a valid HOME is required')
    sessions = json.loads(call('loginctl', 'list-sessions', '--json=short'))
    active = False
    for row in sessions:
        if row.get('uid') != user.pw_uid or row.get('class') != 'user' or not row.get('seat'):
            continue
        props = dict(line.split('=', 1) for line in call('loginctl', 'show-session', row['session'],
                     '-p', 'Type', '-p', 'State').splitlines() if '=' in line)
        if props.get('Type') == 'wayland' and props.get('State') == 'active':
            active = True
    if not active:
        raise ValueError('The initiating user needs an active local Wayland desktop')
    return user


def capture_environment(user):
    runtime = Path('/run/user')/str(user.pw_uid)
    info = runtime.stat()
    if runtime.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != user.pw_uid:
        raise ValueError('Desktop runtime identity mismatch')
    if not (runtime/'bus').exists():
        raise ValueError('Desktop session bus is unavailable')
    return {'PATH': '/usr/bin:/bin', 'HOME': user.pw_dir, 'USER': user.pw_name,
            'LOGNAME': user.pw_name, 'LANG': 'C.UTF-8', 'GSETTINGS_BACKEND': 'dconf',
            'XDG_RUNTIME_DIR': str(runtime), 'DBUS_SESSION_BUS_ADDRESS': 'unix:path='+str(runtime/'bus')}


def capture_desktop_background(name=None):
    user = initiating_user(name)
    environment = capture_environment(user)
    helper = Path(__file__).with_name('gdm-wallpaper.py').read_text()
    command = ['/usr/bin/python3', '-']
    if os.geteuid() == 0:
        command = ['/usr/sbin/runuser', '--user', user.pw_name, '--', *command]
    try:
        result = subprocess.run(command, input=helper, text=True, capture_output=True,
                                env=environment, timeout=25)
    except subprocess.TimeoutExpired:
        raise ValueError('Wallpaper capture timed out; no GDM changes made') from None
    if len(result.stdout) > 90 * 1024 * 1024:
        raise ValueError('Wallpaper capture output exceeds its limit')
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ValueError('Wallpaper capture failed; no GDM changes made') from None
    if result.returncode or 'error' in payload:
        raise ValueError(payload.get('error', 'Wallpaper capture failed'))
    try:
        data = base64.b64decode(payload['png'], validate=True)
        description = payload['description']
        if (not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) > MAX_BACKGROUND or
                description['sha256'] != digest(data) or description['captured_uid'] != user.pw_uid or
                description['resource_name'] != 'hyalune-background.png' or description['origin'] != 'desktop'):
            raise ValueError('Wallpaper snapshot verification failed')
    except (KeyError, TypeError):
        raise ValueError('Invalid wallpaper snapshot') from None
    return {'data': data, 'description': description}


def bundled_background():
    artwork = Path(__file__).resolve().parent.parent/'build/Hyalune-GDM/background.svg'
    safe(artwork); data = artwork.read_bytes()
    if len(data) > 1024 * 1024:
        raise ValueError('GDM artwork exceeds 1MiB')
    return {'data': data, 'description': {'origin': 'bundled',
            'resource_name': 'hyalune-background.svg', 'sha256': digest(data)}}


def owned_background(owner):
    """Read the snapshot from the verified owned resource, not from a user HOME."""
    description = owner.get('background')
    if description is None:
        # preview.1-6 used only the bundled SVG; adopt its actual saved bytes.
        if not owner.get('background_sha256'):
            raise ValueError('Legacy record has no background snapshot; preserve it and remove before a new apply')
        description = {'origin': 'legacy-bundled', 'resource_name': 'hyalune-background.svg',
                       'sha256': owner['background_sha256']}
    name = description.get('resource_name')
    if name not in BACKGROUND_NAMES:
        raise ValueError('Invalid managed background resource')
    data = subprocess.check_output(['gresource', 'extract', owner['resource'], PREFIX+name])
    if len(data) > MAX_BACKGROUND or digest(data) != description['sha256']:
        raise ValueError('Managed background snapshot mismatch')
    return {'data': data, 'description': dict(description)}


def build(source, overlay, output, background=None):
    """Rebuild locally installed resources, retaining notices and all assets."""
    output = Path(output); safe(output)
    if output.exists(): raise ValueError('Build output already exists')
    src = source_image(source)
    overlay_hash = digest(overlay)
    entries = call('gresource', 'list', str(source)).splitlines()
    if PREFIX + 'gdm.css' not in entries: raise ValueError('Source has no gdm.css')
    with tempfile.TemporaryDirectory(prefix='hyalune-gdm-build-') as tmp:
        root = Path(tmp); xml = ET.Element('gresources'); res = ET.SubElement(xml, 'gresource', prefix=PREFIX.rstrip('/'))
        files = {}
        for entry in entries:
            if not entry.startswith(PREFIX): raise ValueError('Unexpected resource namespace')
            rel = entry[len(PREFIX):]
            if not rel or '..' in Path(rel).parts or Path(rel).is_absolute(): raise ValueError('Unsafe resource name')
            files[rel] = subprocess.check_output(['gresource', 'extract', str(source), entry])
        background_description = None
        if b'hyalune-background.svg' in overlay:
            snapshot = background if background is not None else bundled_background()
            background_description = dict(snapshot['description'])
            name = background_description.get('resource_name')
            data = snapshot['data']
            if name not in BACKGROUND_NAMES or len(data) > MAX_BACKGROUND or digest(data) != background_description.get('sha256'):
                raise ValueError('Invalid background snapshot')
            if name.endswith('.png') and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Managed background PNG signature mismatch')
            files[name] = data
            overlay = overlay.replace(b'hyalune-background.svg', name.encode('ascii'))
        # High Contrast follows the installed upstream variant without our overlay.
        if 'gnome-shell-high-contrast.css' not in files: raise ValueError('Missing upstream High Contrast CSS')
        files['gdm-high-contrast.css'] = files['gnome-shell-high-contrast.css']
        for name in list(files):
            if name in ('gdm.css', 'gdm-dark.css', 'gdm-light.css'):
                files[name] += b'\n/* Hyalune GDM independent overlay */\n' + overlay
        for name, data in sorted(files.items()):
            p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
            ET.SubElement(res, 'file').text = name
        manifest = root/'resource.xml'; ET.ElementTree(xml).write(manifest, encoding='utf-8')
        candidate = root/'candidate.gresource'
        subprocess.run(['glib-compile-resources', str(manifest), '--sourcedir', str(root), '--target', str(candidate)], check=True)
        data = candidate.read_bytes(); write(output, data, 0o644)
    return {'source': src, 'resource_sha256': digest(data), 'overlay_sha256': overlay_hash,
            'rendered_overlay_sha256': digest(overlay),
            'background_sha256': background_description['sha256'] if background_description else None,
            'background': background_description}


def replace_background(owner, snapshot, output):
    """Change just the owned image and its URL; preserve installed UI CSS/assets."""
    old = owned_background(owner)
    description = dict(snapshot['description']); name = description.get('resource_name')
    data = snapshot['data']
    if (name not in BACKGROUND_NAMES or len(data) > MAX_BACKGROUND or
            digest(data) != description.get('sha256') or
            (name.endswith('.png') and not data.startswith(b'\x89PNG\r\n\x1a\n'))):
        raise ValueError('Invalid replacement background snapshot')
    output = Path(output); safe(output)
    if output.exists(): raise ValueError('Build output already exists')
    files = {}
    for entry in call('gresource', 'list', owner['resource']).splitlines():
        if not entry.startswith(PREFIX): raise ValueError('Unexpected resource namespace')
        rel = entry[len(PREFIX):]
        if not rel or '..' in Path(rel).parts or Path(rel).is_absolute(): raise ValueError('Unsafe resource name')
        files[rel] = subprocess.check_output(['gresource','extract',owner['resource'],entry])
    old_name = old['description']['resource_name']
    old_url = (PREFIX+old_name).encode(); new_url = (PREFIX+name).encode()
    if old_url not in files.get('gdm.css',b''):
        raise ValueError('Installed GDM stylesheet does not reference its managed background')
    files.pop(old_name)
    files[name] = data
    for css in ('gdm.css','gdm-dark.css','gdm-light.css'):
        if css in files: files[css] = files[css].replace(old_url,new_url)
    with tempfile.TemporaryDirectory(prefix='hyalune-gdm-background-') as tmp:
        root = Path(tmp); xml = ET.Element('gresources'); res = ET.SubElement(xml,'gresource',prefix=PREFIX.rstrip('/'))
        for rel,content in sorted(files.items()):
            path=root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            ET.SubElement(res,'file').text=rel
        manifest=root/'resource.xml';ET.ElementTree(xml).write(manifest,encoding='utf-8')
        candidate=root/'candidate.gresource'
        subprocess.run(['glib-compile-resources',str(manifest),'--sourcedir',str(root),'--target',str(candidate)],check=True)
        resource_data=candidate.read_bytes();write(output,resource_data,0o644)
    marker=b'/* Hyalune GDM independent overlay */\n'
    rendered=files['gdm.css'].rsplit(marker,1)[-1]
    return {'source':owner['source'],'overlay_sha256':owner['overlay_sha256'],
            'rendered_overlay_sha256':digest(rendered),'resource_sha256':digest(resource_data),
            'background_sha256':description['sha256'],'background':description}


def check_source(owner):
    if source_image(owner['source']['path']) != owner['source']:
        raise ValueError('Source resource changed (possibly a package update); preserve backups and review first')


def asset_path(value):
    p = Path(value); safe(p)
    if p.parent != ASSETS or len(p.stem) != 64 or p.suffix != '.gresource' or any(c not in '0123456789abcdef' for c in p.stem):
        raise ValueError('Invalid managed resource path')
    return p


def check_asset(owner):
    p = asset_path(owner['resource'])
    if not p.is_file() or digest(p.read_bytes()) != owner['resource_sha256']:
        raise ValueError('Managed resource was changed or is missing')


def check_owner(owner, current):
    if current != owner['installed_alternatives']:
        raise ValueError('GDM alternatives conflict; no changes made')
    check_source(owner); check_asset(owner)


def alt(*args):
    subprocess.run(['update-alternatives', *args], check=True, stdout=subprocess.DEVNULL)


def install_alt(owner):
    alt('--install', LINK, GROUP, owner['resource'], '-100')


def select_alt(owner):
    alt('--set', GROUP, owner['resource'])


def restore_alt(original, resources):
    for resource in resources:
        if resource in alternatives()['candidates']:
            alt('--remove', GROUP, resource)
    command = ['--auto', GROUP] if original['mode'] == 'auto' else ['--set', GROUP, original['value']]
    alt(*command)
    if alternatives() != original: raise ValueError('Alternative restoration mismatch')


def permitted_state(now, journal):
    """Only our candidates/selection may change during an interrupted step."""
    before = journal['before_alt']; target = journal.get('after_owner')
    resources = {o['resource'] for o in (journal.get('before_owner'), target) if o}
    original = journal['original']
    if {k:v for k,v in now['candidates'].items() if k not in resources} != original['candidates']:
        return False
    if any(v != -100 for k,v in now['candidates'].items() if k in resources): return False
    # External changes to existing candidate priorities/registrations stop recovery.
    allowed_values = {before['value'], original['value'], *resources}
    if now['mode'] == 'auto':
        best = max(now['candidates'].values())
        return now['value'] in [p for p,v in now['candidates'].items() if v == best]
    return now['value'] in allowed_values


def recover():
    j = read(STATE/'pending.json')
    if not j: return {'recovered': False}
    for key in ('before_owner', 'after_owner'):
        if j.get(key):
            path = asset_path(j[key]['resource'])
            if path.exists() or j[key]['resource'] in alternatives()['candidates']:
                check_asset(j[key])
    if not permitted_state(alternatives(), j): raise ValueError('Recovery alternatives conflict; backup retained')
    current_owner = read(STATE/'active.json')
    if current_owner not in (j['before_owner'], j['after_owner']): raise ValueError('Recovery owner conflict')
    if current_owner == j['after_owner'] and j['committed']:
        expected = j['after_alt']
        if alternatives() != expected: raise ValueError('Committed alternative conflict')
        result = 'committed'
    else:
        resources = [o['resource'] for o in (j.get('before_owner'), j.get('after_owner')) if o]
        restore_alt(j['original'], resources)
        if j['before_owner']:
            install_alt(j['before_owner']); select_alt(j['before_owner'])
            save(STATE/'active.json', j['before_owner'])
        elif (STATE/'active.json').exists():
            (STATE/'active.json').unlink(); syncdir(STATE)
        if alternatives() != j['before_alt']: raise ValueError('Rollback mismatch')
        result = 'rolled-back'
    save(STATE/'transactions'/j['id']/'result.json', {'recovery': result})
    (STATE/'pending.json').unlink(); syncdir(STATE)
    return {'recovered': True, 'result': result}


@contextlib.contextmanager
def locked():
    safe(STATE); STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    safe(STATE/'lock')
    with (STATE/'lock').open('a') as own, open('/var/lib/dpkg/lock-frontend', 'a') as dpkg:
        fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.lockf(dpkg, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def operate(action, overlay, dry=False, crash=0, background=None, replace_image=False, manager=None):
    if read(STATE/'pending.json'): raise ValueError('Interrupted GDM operation: run gdm recover first')
    owner = read(STATE/'active.json'); current = alternatives()
    if owner: check_owner(owner, current)
    if action == 'apply' and owner: raise ValueError('Already managed; use update')
    if action in ('update', 'remove', 'set-background') and not owner: raise ValueError('GDM is not managed')
    original = owner['original'] if owner else current
    if any(str(ASSETS) in k for k in original['candidates']): raise ValueError('Unowned Hyalune alternative detected')
    result = {'operation': action, 'layer': 4, 'scope': 'system-login', 'original': original, 'service_restart': False}
    new = None; resource_data = None
    if action != 'remove':
        with tempfile.TemporaryDirectory(prefix='hyalune-gdm-plan-') as tmp:
            candidate = Path(tmp)/'candidate.gresource'
            if action == 'set-background':
                if background is None: raise ValueError('A replacement background is required')
                info = replace_background(owner, background, candidate)
            else:
                snapshot = background if replace_image else (owned_background(owner) if owner else background)
                info = build(owner['source']['path'] if owner else current['value'], overlay, candidate, snapshot)
            resource_data = candidate.read_bytes()
        new = {**info, 'version': VERSION, 'original': original, 'resource': str(ASSETS/(info['resource_sha256']+'.gresource'))}
        if manager is not None: new['manager'] = manager
        elif action == 'set-background' and owner and 'manager' in owner: new['manager'] = owner['manager']
        candidates = dict(original['candidates']); candidates[new['resource']] = -100
        new['installed_alternatives'] = {'mode':'manual', 'value':new['resource'], 'candidates':candidates}
        result.update({'resource':new['resource'], 'source':new['source'], 'overlay_sha256':new['overlay_sha256'], 'background':new['background']})
    if dry: return result
    ident = uuid.uuid4().hex; tx = STATE/'transactions'/ident
    tx.mkdir(parents=True, mode=0o700)
    # Keep a standalone, root-owned recovery tool and source images in each transaction.
    write(tx/'manage-gdm.py', Path(__file__).read_bytes())
    if overlay is not None and action != 'set-background': write(tx/'overlay.css', overlay)
    save(tx/'before.json', {'owner': owner, 'alternatives': current})
    if not owner:
        write(tx/'original.gresource', Path(current['value']).read_bytes())
    else: write(tx/'resource-before.gresource', asset_path(owner['resource']).read_bytes())
    j = {'id':ident, 'operation':action, 'before_owner':owner, 'after_owner':new,
         'before_alt':current, 'after_alt':new['installed_alternatives'] if new else original,
         'original':original, 'committed':False}
    save(STATE/'pending.json',j)
    step=0
    def boundary():
        nonlocal step
        step+=1
        if crash==step: os._exit(90)
    try:
        if new:
            safe(ASSETS); ASSETS.mkdir(parents=True, exist_ok=True, mode=0o755); os.chmod(ASSETS,0o755)
            target=asset_path(new['resource'])
            if target.exists() and digest(target.read_bytes()) != new['resource_sha256']:
                raise ValueError('Retained resource conflict')
            if not target.exists(): write(target,resource_data,0o644)
            boundary(); install_alt(new); boundary(); select_alt(new); boundary()
            if owner and owner['resource'] != new['resource']:
                alt('--remove',GROUP,owner['resource'])
        else:
            restore_alt(original,[owner['resource']]); boundary()
        if alternatives()!=j['after_alt']: raise ValueError('Post-apply alternative mismatch')
        if new: save(STATE/'active.json',new)
        else: (STATE/'active.json').unlink(); syncdir(STATE)
        boundary()
        j['committed']=True;save(STATE/'pending.json',j);boundary()
        save(tx/'result.json',{'operation':action,'committed':True})
        (STATE/'pending.json').unlink();syncdir(STATE)
    except Exception:
        recover(); raise
    return {**result,'committed':True,'backup':str(tx),'restart_required':True}


def show_result(result, action, operation, as_json=False):
    if as_json:
        print(json.dumps(result, indent=2))
        return
    labels = {'apply': '初回導入', 'update': '更新', 'remove': '解除',
              'set-background': '背景の入れ替え'}
    if action == 'status':
        print('GDM: ' + ('導入済み' if result['managed'] else '未導入'))
        if result['version']: print('配置版: ' + result['version'])
        background = result.get('background') or {}
        if background:
            print('背景: ' + ('取り込み済みのデスクトップ画像' if background.get('origin') == 'desktop' else 'Hyaluneの背景'))
        print('中断: ' + ('あり。recoverを実行してください。' if result['pending'] else 'なし'))
        print('競合: ' + (result['conflict'] or 'なし'))
        print('これは配置状態です。表示は新しいログイン画面で確認してください。')
    elif action == 'plan' or result.get('preview'):
        print('予定: GDMの' + labels[operation])
        if operation == 'update': print('保存済みの背景を維持します。')
        elif operation in ('apply', 'set-background'):
            origin = (result.get('background') or {}).get('origin')
            print('背景: ' + ('現在のデスクトップ画像を取り込みます。' if origin == 'desktop' else 'Hyaluneの背景を使います。'))
        print('設定は変更していません。')
    elif action == 'recover':
        print('中断からの復旧が完了しました。' if result['recovered'] else '復旧が必要な中断はありません。')
    else:
        print('GDMの' + labels[operation] + 'が完了しました。')
        if result.get('backup'): print('保全先: ' + result['backup'])
        print('自動ログアウトは行いません。表示は次のログイン画面で確認してください。')


def main():
    primary = '{plan,set,status,background,remove,recover}'
    p = argparse.ArgumentParser(prog='install.sh gdm', description=
        'GDMを管理します。初回・更新とも plan → set → status。Ubuntu 26.04 / GNOME Shell 50.x向け。機種名による制限はありません。',
        epilog='background: 現在のデスクトップ壁紙へ入れ替え。background --plan: その予定確認。')
    p.add_argument('action', choices=['build','plan','set','apply','update','remove','recover','status','background','set-background'], metavar=primary)
    p.add_argument('--plan', action='store_true', help='backgroundの予定だけを確認')
    p.add_argument('--bundled', action='store_true', help='初回またはbackgroundでHyaluneの背景を選択')
    p.add_argument('--json', action='store_true', help='自動処理用の詳細JSONを出力')
    p.add_argument('--desktop-user', help='root端末のみ: 対象のデスクトップ利用者')
    # Older invocations remain accepted; they are no longer the public workflow.
    p.add_argument('--operation', choices=['apply','update','remove','set-background'], help=argparse.SUPPRESS)
    p.add_argument('--vm-preview', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--background', choices=['desktop','bundled'], help=argparse.SUPPRESS)
    p.add_argument('--output', type=Path, help=argparse.SUPPRESS)
    p.add_argument('--source', type=Path, help=argparse.SUPPRESS)
    p.add_argument('--crash-after', type=int, default=0, help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.plan and a.action != 'background': p.error('--plan is only for background')
    if a.operation and a.action != 'plan': p.error('--operation is only for plan')
    if a.bundled:
        if a.background and a.background != 'bundled': p.error('Conflicting background choices')
        a.background = 'bundled'
    css = Path(__file__).resolve().parent.parent/'build/Hyalune-GDM/overlay.css'
    if a.action == 'build':
        if a.desktop_user and a.background is None: a.background = 'desktop'
        if not a.output: p.error('build requires --output')
        source = str(a.source) if a.source else alternatives()['value']
        if not a.source and Path(source).parent == ASSETS:
            p.error('build requires --source with the original resource while GDM is managed')
        snapshot = capture_desktop_background(a.desktop_user) if a.background == 'desktop' else None
        print(json.dumps(build(source, css.read_bytes(), a.output, snapshot), indent=2))
        return
    # Root/path checks are unconditional; new changes also validate the OS/loader.
    guard(restoring=a.action in ('remove','recover','status') or
          (a.action == 'plan' and a.operation == 'remove'))
    owner = read(STATE/'active.json')
    operation = a.action
    if a.action in ('plan','set'):
        operation = a.operation or ('update' if owner else 'apply')
    elif a.action == 'background':
        operation = 'set-background'
    if (a.background is not None or a.desktop_user is not None) and operation not in ('apply','set-background'):
        p.error('Background selection is for initial set or background; updates keep the saved image')
    if a.desktop_user and a.background == 'bundled': p.error('--desktop-user cannot be used with --bundled')
    legacy = a.action in ('apply','update','set-background') or bool(a.operation or a.vm_preview or a.background and not a.bundled)
    as_json = a.json or legacy
    if a.action == 'status':
        conflict = None
        try:
            if owner: check_owner(owner, alternatives())
        except (OSError, ValueError) as error: conflict = str(error)
        result = {'layer':4, 'managed':owner is not None,
                  'version':owner.get('version') if owner else None,
                  'pending':read(STATE/'pending.json') is not None,
                  'alternatives':alternatives(), 'conflict':conflict,
                  'background':owner.get('background', {'origin':'legacy-bundled', 'sha256':owner.get('background_sha256')}) if owner else None,
                  'loaded':'not-probed; a new greeter is required after changes'}
        show_result(result, a.action, operation, as_json)
        return
    snapshot = None
    wants_background = (operation == 'apply' and owner is None) or (operation == 'set-background' and owner is not None)
    if wants_background and not read(STATE/'pending.json'):
        if owner: check_owner(owner, alternatives())
        snapshot = capture_desktop_background(a.desktop_user) if a.background != 'bundled' else bundled_background()
    dry = a.action == 'plan' or a.plan
    if dry:
        result = operate(operation, css.read_bytes() if operation != 'remove' else None, dry=True, background=snapshot)
        if a.plan: result['preview'] = True
    else:
        with locked():
            if a.action == 'recover': result = recover()
            else: result = operate(operation, css.read_bytes() if operation != 'remove' else None,
                                   crash=a.crash_after, background=snapshot)
    show_result(result, a.action, operation, as_json)


if __name__=='__main__':
    try: main()
    except (OSError,ValueError,subprocess.CalledProcessError) as error:
        print('Hyalune GDM: '+str(error),file=sys.stderr);sys.exit(1)
