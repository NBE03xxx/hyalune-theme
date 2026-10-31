#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# Development only. Compiled catalogs are shipped with the app, so installation
# and startup do not require gettext command-line tools.
msgfmt --check --check-format \
    -o "$project_dir/src/manager/locale/ja/LC_MESSAGES/hyalune.mo" \
    "$project_dir/src/manager/locale/ja/LC_MESSAGES/hyalune.po"
