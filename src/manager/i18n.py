# SPDX-License-Identifier: MIT
"""Settings UI localization. Never translate persisted profiles or API data."""
import gettext
import os
from pathlib import Path
import re


def select_language(environ=None):
    """Use the primary message language; unsupported languages fall back to English.

    LANGUAGE is the desktop's ordered message preference. A secondary Japanese
    preference must not override an unsupported primary language. The explicit
    C/POSIX locale disables LANGUAGE, as in gettext. C.UTF-8 allows preferences.
    """
    env = os.environ if environ is None else environ
    locale = env.get('LC_ALL') or env.get('LC_MESSAGES') or env.get('LANG') or ''
    if locale in ('C', 'POSIX'):
        return 'en'
    preferences = [part for part in env.get('LANGUAGE', '').split(':') if part]
    primary = preferences[0] if preferences else locale
    return 'ja' if re.split(r'[_\-.@]', primary.lower(), maxsplit=1)[0] == 'ja' else 'en'


LANGUAGE = select_language()
JAPANESE = gettext.translation('hyalune', Path(__file__).with_name('locale'), languages=['ja'], fallback=True)
_ = (JAPANESE if LANGUAGE == 'ja' else gettext.NullTranslations()).gettext

# Legacy helpers and saved notes keep their original wording and hashes. These
# complete templates allow the UI to localize their prefix, preserving details.
DIAGNOSTIC_TEMPLATES = (
    'SCSS generation failed: {details}',
    'GDM generation failed: {details}',
    'Cannot change app: {details}',
    'Inspection failed: {details}',
    'Desktop environment inspection failed: {details}',
    'Disable the conflicting blur extensions first: {details}',
)


def message(text):
    """Localize known helper diagnostics only at the display boundary.

    The catalog's legacy context maps old Japanese messages to English source
    messages. Unknown OS/library diagnostics and paths remain intact.
    """
    english = JAPANESE.pgettext('legacy', text)
    if english != text:
        return _(english)
    for template in DIAGNOSTIC_TEMPLATES:
        for source in (template, JAPANESE.gettext(template)):
            prefix, suffix = source.split('{details}')
            if text.startswith(prefix) and (not suffix or text.endswith(suffix)):
                details = text[len(prefix):len(text)-len(suffix) if suffix else None]
                return _(template).format(details=message(details))
    return _(text)
