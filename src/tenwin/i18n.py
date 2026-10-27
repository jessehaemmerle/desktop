"""gettext setup. English source strings, German translation in po/de.po."""

import gettext
import locale
import os

from tenwin import paths

DOMAIN = "tenwin"


def _languages():
    from tenwin.config import load_file

    choice = load_file().get("region.language", "auto")
    if choice in ("de", "en"):
        return [choice]
    return None  # let gettext use LANGUAGE / LC_ALL / LC_MESSAGES / LANG


try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

_translation = gettext.translation(
    DOMAIN, localedir=str(paths.LOCALE_DIR), languages=_languages(), fallback=True)

_ = _translation.gettext
ngettext = _translation.ngettext


def N_(message):
    """Mark a string for translation without translating it (xgettext keyword)."""
    return message


def pgettext(context, message):
    result = _translation.pgettext(context, message)
    return result


def current_language():
    """Two-letter code of the UI language actually in use."""
    info = _translation.info()
    lang = info.get("language")
    if lang:
        return lang.split("_")[0]
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.split(":")[0].split("_")[0][:2] or "en"
    return "en"
