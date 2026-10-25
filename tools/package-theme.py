#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a deterministic offline zip; never install or fetch dependencies."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.1.0-vm-preview.1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.version):
        parser.error("Invalid version")
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output already exists; choose a new name.")
    root = Path(__file__).resolve().parent.parent
    files = {}
    for name in ("gnome-shell/gnome-shell.css", "gtk-3.0/gtk.css", "gtk-3.0/gtk-dark.css", "gtk-4.0/window-controls.css"):
        source = root / "build/Glass50-Dark" / name
        if source.is_symlink():
            parser.error(f"Symlink payload refused: {source}")
        files["payload/" + name] = source.read_bytes()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    manifest = {"format": 1, "component": "base-theme", "version": args.version,
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "source_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()),
                "scope": "KVM-PC Ubuntu 26.04 / GNOME Shell 50.x / Wayland VM preview",
                "files": hashes}
    for name, source in {"manage-theme.py": "tools/manage-theme.py", "LICENSE": "LICENSE",
                         "INSTALL.md": "docs/LEGACY-INSTALL.md", "LICENSES.md": "docs/LICENSES.md"}.items():
        files[name] = (root / source).read_bytes()
    # Inventory protects against accidental corruption. It is not a signature;
    # obtain the zip and its separately recorded hash through trusted transport.
    manifest["support_files"] = {name: hashlib.sha256(data).hexdigest() for name, data in files.items() if not name.startswith("payload/")}
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo("Glass50-Dark/" + name, date_time=(2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
    print(json.dumps({"path": str(args.output), "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "version": args.version, "payload_sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
