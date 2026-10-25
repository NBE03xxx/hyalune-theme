#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Transactional, VM-only installer for the four stable Glass50 CSS outputs."""

import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import uuid

THEME = ".local/share/themes/Glass50-Dark/"
FILES = (
    "gnome-shell/gnome-shell.css", "gtk-3.0/gtk.css",
    "gtk-3.0/gtk-dark.css", "gtk-4.0/window-controls.css",
)
CSS = ".config/gtk-4.0/gtk.css"
STATE = ".local/state/glass50/installer-v1"
ACTIVE = STATE + "/active.json"
BEGIN = b"/* Glass50 managed: window controls begin */"
END = b"/* Glass50 managed: window controls end */"
USER_THEMES = "user-theme@gnome-shell-extensions.gcampax.github.com"
KEYS = {
    "gtk-theme": ("org.gnome.desktop.interface", "gtk-theme", "'Glass50-Dark'"),
    "color-scheme": ("org.gnome.desktop.interface", "color-scheme", "'prefer-dark'"),
    "shell-theme": ("org.gnome.shell.extensions.user-theme", "name", "'Glass50-Dark'"),
}


def fail(message):
    raise ValueError(message)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(path):
    """Refuse links at every existing component, including dangling links."""
    if not path.is_absolute() or ".." in path.parts:
        fail(f"Unsafe path: {path}")
    for component in (path, *path.parents):
        if component.is_symlink():
            fail(f"Symlink refused: {component}")
    if path.exists() and not path.is_file():
        fail(f"Regular file required: {path}")


def snapshot(path):
    safe(path)
    if not path.exists():
        return None
    return {"data": base64.b64encode(path.read_bytes()).decode(),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def contents(value):
    return b"" if value is None else base64.b64decode(value["data"], validate=True)


def image(data, mode=0o644):
    return {"data": base64.b64encode(data).decode(), "mode": mode}


def write(path, value):
    safe(path)
    if value is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after creating parents; never follow a preexisting link.
        safe(path)
        fd, temporary = tempfile.mkstemp(prefix=".glass50-txn-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(contents(value))
                os.fchmod(stream.fileno(), value["mode"])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def guard():
    if socket.gethostname() != "KVM-PC" or not os.environ.get("SSH_CONNECTION"):
        fail("VM KVM-PCへの照合済みSSH内だけで実行してください。ホスト適用は未対応です。")
    if os.geteuid() == 0:
        fail("Run as the VM desktop user, without sudo.")
    root = subprocess.check_output(["findmnt", "-n", "-o", "SOURCE", "/"], text=True).strip()
    version = subprocess.check_output(["gnome-shell", "--version"], text=True).strip()
    if root != "/dev/vda2" or not re.fullmatch(r"GNOME Shell 50\.\d+", version):
        fail("Expected /dev/vda2 and GNOME Shell 50.x.")
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def load_package(path):
    manifest_path = path / "manifest.json"
    safe(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    expected = {"payload/" + name for name in FILES}
    if manifest.get("format") != 1 or manifest.get("component") != "base-theme" or set(manifest.get("files", {})) != expected:
        fail("Unknown package format/component/file list.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", manifest.get("version", "")):
        fail("Invalid package version.")
    if set(manifest.get("support_files", {})) != {"manage-theme.py", "INSTALL.md", "LICENSE", "LICENSES.md"}:
        fail("Unknown package support file list.")
    for name, expected_hash in manifest["support_files"].items():
        source = path / name
        safe(source)
        if digest(source.read_bytes()) != expected_hash:
            fail(f"Package hash mismatch: {name}")
    payload = {}
    for name in FILES:
        source = path / "payload" / name
        safe(source)
        data = source.read_bytes()
        if digest(data) != manifest["files"]["payload/" + name]:
            fail(f"Package hash mismatch: {name}")
        payload[THEME + name] = image(data)
    return manifest, payload


class Settings:
    def __init__(self, real_home):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        source = Gio.SettingsSchemaSource.get_default()
        schema_dir = real_home / ".local/share/gnome-shell/extensions" / USER_THEMES / "schemas"
        if schema_dir.is_dir():
            source = Gio.SettingsSchemaSource.new_from_directory(str(schema_dir), source, False)
        self.items = {}
        for alias, (schema_id, key, _) in KEYS.items():
            schema = source.lookup(schema_id, True)
            if schema is None:
                fail(f"Missing prerequisite schema: {schema_id}")
            self.items[alias] = (Gio.Settings.new_full(schema, None, None), key)

    def get(self, alias):
        settings, key = self.items[alias]
        value = settings.get_user_value(key)
        return value.print_(True) if value is not None else None

    def put(self, alias, value):
        settings, key = self.items[alias]
        if not settings.is_writable(key):
            fail(f"Setting is locked: {alias}")
        if value is None:
            settings.reset(key)
        elif not settings.set_value(key, self.GLib.Variant.parse(None, value, None, None)):
            fail(f"Setting write failed: {alias}")
        self.Gio.Settings.sync()
        if self.get(alias) != value:
            fail(f"Setting verification failed: {alias}")


def block(home):
    uri = (home / THEME / FILES[-1]).as_uri()
    return BEGIN + b'\n@import url("' + uri.encode() + b'");\n' + END


def locate(data):
    if data.count(BEGIN) != data.count(END) or data.count(BEGIN) > 1:
        fail("Malformed or duplicate GTK4 management block.")
    if not data.count(BEGIN):
        return None
    start, end = data.index(BEGIN), data.index(END) + len(END)
    if end < start:
        fail("Reversed GTK4 management block.")
    return data[start:end]


def validate_active(active):
    if (active.get("format") != 1 or set(active.get("originals", {})) != {THEME + f for f in FILES}
            or set(active.get("installed", {})) != set(active["originals"])
            or set(active.get("settings_before", {})) != set(KEYS)):
        fail("Invalid ownership manifest; restore from transaction record first.")


def make_plan(home, settings, action, package):
    old_state = snapshot(home / ACTIVE)
    active = json.loads(contents(old_state)) if old_state else None
    if active:
        validate_active(active)
    if action == "apply" and active:
        fail("Already managed: use update.")
    if action in ("update", "remove") and not active:
        fail("No managed installation.")
    operations, notes = [], []

    def file_op(name, before, after):
        if before != after:
            operations.append({"kind": "file", "name": name, "before": before, "after": after})

    if action != "remove":
        manifest, payload = load_package(package)
    for name in (THEME + f for f in FILES):
        current = snapshot(home / name)
        if active:
            if current != active["installed"][name]:
                fail(f"User modification; preserve and resolve before continuing: {name}")
        elif current is not None and contents(current) != contents(payload[name]):
            fail(f"Unmanaged different file; no overwrite: {name}")
        if action != "remove" and current is not None:
            payload[name]["mode"] = current["mode"]
        file_op(name, current, active["originals"][name] if action == "remove" else payload[name])

    css_before = snapshot(home / CSS)
    data, desired = contents(css_before), block(home)
    found = locate(data)
    if action != "remove":
        if found is not None and found != desired:
            fail("Unknown GTK4 management block; no overwrite.")
        if active and found != desired:
            fail("Managed GTK4 block was removed or modified.")
        new_data = data if found else desired + b"\n" + data
        css_after = image(new_data, css_before["mode"] if css_before else 0o644)
    else:
        if found != desired:
            fail("Managed GTK4 block was removed or modified.")
        original = active["css_original"]
        if css_before == active["css_installed"]:
            css_after = original
        else:
            # Preserve independent user edits; restore only our own exact block.
            old_block = locate(contents(original))
            new_data = data.replace(desired, old_block or b"", 1)
            if old_block is None and data.startswith(desired + b"\n"):
                new_data = data[len(desired) + 1:]
            css_after = image(new_data, css_before["mode"])
            notes.append("Independent GTK4 CSS edits preserved.")
    file_op(CSS, css_before, css_after)

    settings_before = {key: settings.get(key) for key in KEYS}
    for key, (_, _, desired_value) in KEYS.items():
        current = settings_before[key]
        if action == "remove":
            if current != desired_value:
                notes.append(f"User setting preserved: {key}")
                continue
            new_value = active["settings_before"][key]
        else:
            if active and current != desired_value:
                fail(f"User setting changed: {key}; remove preserves it, update stops.")
            new_value = desired_value
        if current != new_value:
            operations.append({"kind": "setting", "name": key, "before": current, "after": new_value})

    if action == "remove":
        after_state = None
    else:
        new_state = {
            "format": 1, "version": manifest["version"], "package_files": manifest["files"],
            "originals": active["originals"] if active else {name: snapshot(home / name) for name in payload},
            "installed": payload,
            "settings_before": active["settings_before"] if active else settings_before,
            "css_original": active["css_original"] if active else css_before,
            "css_installed": active["css_installed"] if active else css_after,
        }
        after_state = image(canonical(new_state), 0o600)
    file_op(ACTIVE, old_state, after_state)
    return operations, notes


def current(home, settings, operation):
    return snapshot(home / operation["name"]) if operation["kind"] == "file" else settings.get(operation["name"])


def mutate(home, settings, operation, value):
    if operation["kind"] == "file":
        write(home / operation["name"], value)
    else:
        settings.put(operation["name"], value)


def check_journal(journal):
    allowed_files = {THEME + f for f in FILES} | {CSS, ACTIVE}
    if journal.get("format") != 1 or not re.fullmatch(r"[0-9a-f]{32}", journal.get("id", "")):
        fail("Invalid recovery journal.")
    for op in journal["operations"]:
        if not ((op["kind"] == "file" and op["name"] in allowed_files)
                or (op["kind"] == "setting" and op["name"] in KEYS)):
            fail("Unexpected recovery target.")


def rollback(home, settings, journal):
    check_journal(journal)
    # Check every target before any recovery write, including crash-before-write.
    # One key can have several staged changes (disable our extension, then
    # restore the original list). Before the first stage, its current value
    # need not match the before/after pair of the final stage.
    states = {}
    for op in journal["operations"]:
        key = (op["kind"], op["name"])
        states.setdefault(key, []).extend([op["before"], op["after"]])
    for op in journal["operations"]:
        if current(home, settings, op) not in states[(op["kind"], op["name"])]:
            fail(f"Recovery conflict; backups retained: {op['name']}")
    for op in reversed(journal["operations"]):
        now = current(home, settings, op)
        if now == op["after"] and now != op["before"]:
            mutate(home, settings, op, op["before"])


def component_guard(home, action):
    if STATE != ".local/state/glass50/installer-v1" or action == "status":
        return
    for name in ("active.json", "pending.json"):
        path = home / ".local/state/glass50/installer-material-v1" / name
        safe(path)
        if path.exists():
            fail("Material preview is managed/pending; use manage-material.py first.")


def run(args):
    real_home = guard()
    home = real_home
    if args.test_root:
        home = Path(args.test_root)
        base = real_home / ".local/state/glass50/phase5-tests"
        if not home.is_absolute() or not home.is_relative_to(base) or home == base or ".." in home.parts:
            fail(f"Test root must be a child of {base}")
        for name in (home, *home.parents):
            if name.is_symlink():
                fail(f"Test root symlink: {name}")
        os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                          XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
                          GSETTINGS_BACKEND="keyfile")
    else:
        for name, expected in {"HOME": real_home, "XDG_CONFIG_HOME": real_home / ".config",
                               "XDG_DATA_HOME": real_home / ".local/share",
                               "XDG_STATE_HOME": real_home / ".local/state"}.items():
            if os.environ.get(name) and Path(os.environ[name]) != expected:
                fail(f"Nonstandard {name}; explicit test-root required.")
        if os.environ.get("GSETTINGS_BACKEND") not in (None, "dconf"):
            fail("Normal mode requires dconf.")
        if globals().get("require_user_themes", True) and args.action not in ("remove", "recover", "status") and USER_THEMES not in subprocess.check_output(
                ["gnome-extensions", "list", "--active"], text=True).splitlines():
            fail("Enable the already installed User Themes separately before applying.")
    if (args.fail_after or args.crash_after or args.crash_after_commit) and not args.test_root:
        fail("Fault injection is only available with test-root.")
    state_dir = home / STATE
    pending = state_dir / "pending.json"
    safe(pending)
    settings = Settings(real_home)
    if args.action == "status":
        state = snapshot(home / ACTIVE)
        decoded = json.loads(contents(state)) if state else None
        extra = globals().get("status_extra", lambda _home, _state: {})(home, decoded)
        print(canonical({"home": str(home), "managed": bool(state), "pending": pending.exists(),
                         "version": decoded["version"] if state else None, **extra}).decode(), end="")
        return
    action = args.operation if args.action == "plan" else args.action
    if args.action == "plan":
        component_guard(home, args.action)
        if pending.exists():
            fail("Interrupted transaction: recover first.")
        operations, notes = make_plan(home, settings, action, Path(args.package).absolute())
        print(canonical({"action": action, "home": str(home), "dry_run": True,
                         "targets": [{"kind": op["kind"], "name": op["name"]} for op in operations],
                         "notes": notes, **globals().get("plan_extra", lambda: {})()}).decode(), end="")
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / "lock"
    safe(lock)
    shared = home / ".local/state/glass50/appearance.lock"
    safe(shared)
    # Components with their own state directory (such as the settings app)
    # still share this lock on a previously untouched user HOME.
    shared.parent.mkdir(parents=True, exist_ok=True)
    safe(shared)
    with shared.open("a+b") as appearance, lock.open("a+b") as stream:
        os.fchmod(appearance.fileno(), 0o600)
        os.fchmod(stream.fileno(), 0o600)
        fcntl.flock(appearance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        component_guard(home, args.action)
        if args.action == "recover":
            if not pending.exists():
                fail("No pending transaction.")
            journal = json.loads(pending.read_text())
            check_journal(journal)
            history = state_dir / "transactions" / journal["id"]
            result = snapshot(history / "result.json")
            committed = result and json.loads(contents(result)).get("status") == "committed"
            if not committed:
                rollback(home, settings, journal)
                write(history / "result.json", image(canonical({"status": "recovered"}), 0o600))
            write(pending, None)
            print(canonical({"status": "commit-finalized" if committed else "recovered", "transaction": str(history)}).decode(), end="")
            return
        if pending.exists():
            fail("Interrupted transaction: recover first.")
        operations, notes = make_plan(home, settings, action, Path(args.package).absolute())
        simulated = {}
        for op in operations:
            key = (op["kind"], op["name"])
            before = simulated[key] if key in simulated else current(home, settings, op)
            if before != op["before"]:
                fail(f"Concurrent modification: {op['name']}")
            simulated[key] = op["after"]
        transaction_id = uuid.uuid4().hex
        history = state_dir / "transactions" / transaction_id
        history.mkdir(parents=True, mode=0o700, exist_ok=False)
        journal = {"format": 1, "id": transaction_id, "action": action,
                   "at": datetime.datetime.now().astimezone().isoformat(), "operations": operations}
        write(history / "journal.json", image(canonical(journal), 0o600))
        write(pending, image(canonical(journal), 0o600))
        try:
            for number, op in enumerate(operations, 1):
                if current(home, settings, op) != op["before"]:
                    fail(f"Concurrent modification: {op['name']}")
                mutate(home, settings, op, op["after"])
                if args.crash_after == number:
                    os._exit(86)
                if args.fail_after == number:
                    raise RuntimeError("Injected transaction failure")
            # A committed result is the durable commit point. recover rolls back
            # only if this record was not written before a process interruption.
            write(history / "result.json", image(canonical({"status": "committed"}), 0o600))
        except Exception:
            result = snapshot(history / "result.json")
            if result and json.loads(contents(result)).get("status") == "committed":
                # A failure while syncing the committed result must not undo it.
                # Leave the pointer for recover to finalize consistently.
                raise
            rollback(home, settings, journal)
            write(history / "result.json", image(canonical({"status": "rolled-back"}), 0o600))
            write(pending, None)
            raise
        if args.crash_after_commit:
            os._exit(86)
        write(pending, None)
        print(canonical({"status": "committed", "action": action, "transaction": str(history), "notes": notes, **globals().get("result_extra", lambda: {})()}).decode(), end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "update", "remove", "recover", "status"))
    parser.add_argument("--package", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--operation", choices=("apply", "update", "remove"), default="apply")
    parser.add_argument("--test-root")
    parser.add_argument("--fail-after", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--crash-after", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--crash-after-commit", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as error:
        print(f"Glass50: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
