#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out="$root/build/Hyalune-Light"
command -v sassc >/dev/null
mkdir -p "$out/gnome-shell" "$out/gtk-3.0" "$out/gtk-4.0"
sassc -t expanded "$root/src/scss/light-shell.scss" "$out/gnome-shell/gnome-shell.css"
sassc -t expanded "$root/src/scss/light-gtk3.scss" "$out/gtk-3.0/gtk.css"
printf '@import url("gtk.css");\n' > "$out/gtk-3.0/gtk-dark.css"
sassc -t expanded "$root/src/scss/light-gtk4.scss" "$out/gtk-4.0/material.css"
sassc -t expanded "$root/src/scss/light-flatpak-gtk4.scss" "$out/gtk-4.0/flatpak.css"
sassc -t expanded "$root/src/scss/light-flatpak-gtk3.scss" "$out/gtk-3.0/flatpak.css"
printf 'Built: %s\n' "$out"
