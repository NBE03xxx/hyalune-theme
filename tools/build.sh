#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! command -v sassc >/dev/null 2>&1; then
    printf '%s\n' 'sassc is required. No packages will be installed automatically.' >&2
    exit 1
fi

theme_dir="$project_dir/build/Glass50-Dark/gnome-shell"
mkdir -p "$theme_dir"
sassc -t expanded "$project_dir/src/scss/gnome-shell.scss" "$theme_dir/gnome-shell.css"
printf 'Built: %s\n' "$theme_dir/gnome-shell.css"

gtk_theme_dir="$project_dir/build/Glass50-Dark/gtk-3.0"
mkdir -p "$gtk_theme_dir"
sassc -t expanded "$project_dir/src/scss/gtk3.scss" "$gtk_theme_dir/gtk.css"
printf '@import url("gtk.css");\n' > "$gtk_theme_dir/gtk-dark.css"
printf 'Built: %s\n' "$gtk_theme_dir/gtk.css"

gtk4_dir="$project_dir/build/Glass50-Dark/gtk-4.0"
mkdir -p "$gtk4_dir"
for profile in gtk4 libadwaita; do
    sassc -t expanded "$project_dir/src/scss/$profile.scss" "$gtk4_dir/$profile.css"
    printf 'Built: %s\n' "$gtk4_dir/$profile.css"
done
sassc -t expanded "$project_dir/src/scss/gtk4-controls.scss" "$gtk4_dir/window-controls.css"
printf 'Built: %s\n' "$gtk4_dir/window-controls.css"

probe_dir="$project_dir/build/Glass50-Dark/phase4"
mkdir -p "$probe_dir"
sassc -t expanded "$project_dir/src/scss/phase4-probe.scss" "$probe_dir/probe.css"
printf 'Built: %s\n' "$probe_dir/probe.css"
