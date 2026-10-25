#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$root/build/Hyalune-GDM"
sassc -t expanded "$root/src/scss/gdm.scss" "$root/build/Hyalune-GDM/overlay.css"
cp "$root/src/gdm/background.svg" "$root/build/Hyalune-GDM/background.svg"
