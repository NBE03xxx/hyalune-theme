# Hyalune Qt window controls

Optional Qt Wayland decorations for Ubuntu 26.04 / GNOME Shell 50. These sources extend the pinned Qt decoration implementations recorded in [UPSTREAM.json](UPSTREAM.json).

The three builds use Qt 5.15.18, native Qt 6.10.2 and KDE runtime Qt 6.11.3. The launchers enable the matching build only when the installed Qt ABI matches. Other versions launch with their original environment.

The read-only session service observes the User Themes selection, its actual extension state and High Contrast. Hyalune shows coloured controls. Another Shell theme, disabled User Themes, High Contrast or an unavailable policy service selects the original Qt drawing in already-open windows. GTK and GDM have their own settings.

`tools/build-qt.py` builds against matching public and private development headers. It accepts a normal `/usr` prefix or an independently extracted development prefix. The Flatpak build also needs the matching SDK headers and runtime prefix. The generated libraries and manifest live in `build/Hyalune-Qt`.

The optional installer is `./install.sh qt install`. It currently requires the supported native Nextcloud and Mozc launchers plus one supported KeePassXC Flatpak installation. `plan`, `status`, `remove` and `recover` use a separate ownership record and the common transaction engine. The normal application menu and existing Nextcloud autostart entries receive per-application wrappers. Native commands that directly execute the original binary retain their existing environment. Flatpak plugin access and policy-bus permission are passed only to the wrapper's process, without global overrides.

`qt5`, `qt6-6.10` and `qt6-6.11` retain the original copyright and licensing notices. These derived decoration sources are distributed under the LGPL v3 option in their headers. See [LGPL v3](licenses/LGPL-3.0.txt) and [GPL v3](licenses/GPL-3.0.txt). The new policy client, service, launcher and build/installation tools use MIT. The complete matching source is also installed beside the optional libraries.
