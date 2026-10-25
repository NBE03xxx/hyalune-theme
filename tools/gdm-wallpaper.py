#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read and normalize the initiating user's wallpaper, without root access.

The root manager feeds this code to an ordinary user's Python process. Only a
bounded PNG snapshot and non-path metadata are returned. Nothing is written.
"""
import base64
import hashlib
import json
import os
import resource
import stat
import sys
from urllib.parse import urlsplit

MAX_SOURCE = 32 * 1024 * 1024
MAX_PNG = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000


def capture():
    if os.geteuid() == 0:
        raise ValueError('Wallpaper decoding must run as the desktop user')
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import Gio, GdkPixbuf

    appearance = Gio.Settings.new('org.gnome.desktop.interface')
    settings = Gio.Settings.new('org.gnome.desktop.background')
    scheme = appearance.get_string('color-scheme')
    options = settings.get_string('picture-options')
    if options == 'none' or settings.get_int('picture-opacity') == 0:
        raise ValueError('The desktop is not displaying a wallpaper image')
    key = 'picture-uri-dark' if scheme == 'prefer-dark' else 'picture-uri'
    uri = settings.get_string(key)
    if key == 'picture-uri-dark' and not uri:
        key = 'picture-uri'; uri = settings.get_string(key)
    if not uri:
        raise ValueError('No desktop wallpaper image is configured')
    parsed = urlsplit(uri)
    if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost') or parsed.query or parsed.fragment:
        raise ValueError('Only local file:// wallpaper images are supported')
    path = Gio.File.new_for_uri(uri).get_path()
    if not path or not os.path.isabs(path):
        raise ValueError('Wallpaper URI is not an absolute local file')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Wallpaper must be a regular file')
            if info.st_size > MAX_SOURCE:
                raise ValueError('Wallpaper source exceeds 32MiB')
            raw = file.read(MAX_SOURCE + 1)
    except OSError:
        raise ValueError('Desktop user cannot read the wallpaper image') from None
    if not raw or len(raw) > MAX_SOURCE:
        raise ValueError('Wallpaper source is empty or exceeds 32MiB')
    if path.lower().endswith('.xml') or b'<background' in raw[:4096]:
        raise ValueError('Dynamic XML wallpaper is unsupported; choose a static image or --background bundled')

    loader = GdkPixbuf.PixbufLoader.new()
    too_large = []
    def sized(loader, width, height):
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            too_large.append(True)
            loader.set_size(1, 1)
    loader.connect('size-prepared', sized)
    try:
        loader.write(raw); loader.close()
        if too_large:
            raise ValueError('Wallpaper exceeds 40 million pixels')
        animation = loader.get_animation()
        if animation is not None and not animation.is_static_image():
            raise ValueError('Animated wallpaper is unsupported; choose a static image')
        image = loader.get_pixbuf()
        if image is None:
            raise ValueError('Wallpaper has no decodable image')
        image = image.apply_embedded_orientation()
        width, height = image.get_width(), image.get_height()
        if width * height > MAX_PIXELS:
            raise ValueError('Wallpaper exceeds 40 million pixels')
        # Drop source metadata before encoding the managed copy.
        image = image.copy()
        for option in list(image.get_options()):
            image.remove_option(option)
        success, png = image.save_to_bufferv('png', [], [])
        if not success or len(png) > MAX_PNG:
            raise ValueError('Normalized wallpaper exceeds 64MiB')
    except ValueError:
        raise
    except Exception:
        raise ValueError('Wallpaper is not a supported static image') from None
    png = bytes(png)
    return {'png': base64.b64encode(png).decode('ascii'),
            'description': {'origin': 'desktop', 'resource_name': 'hyalune-background.png',
                            'sha256': hashlib.sha256(png).hexdigest(),
                            'source_sha256': hashlib.sha256(raw).hexdigest(),
                            'width': width, 'height': height, 'source_key': key,
                            'color_scheme': scheme, 'picture_options': options,
                            'render_mode': 'cover', 'captured_uid': os.getuid()}}


if __name__ == '__main__':
    try:
        print(json.dumps(capture()))
    except Exception as error:
        print(json.dumps({'error': str(error)})); sys.exit(1)
