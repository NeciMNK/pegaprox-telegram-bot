# -*- coding: utf-8 -*-
"""Bot texts in more than one language.

The English text is the key. `_('Cluster: {name}', name=x)` returns the text in the language
of the user the bot is answering right now (set with `use()` before each update), or English
when there is no translation.
"""
import threading

from .lang_ru import RU

LANGUAGES = {'en': 'English', 'ru': 'Русский'}
_CATALOGS = {'ru': RU}
_local = threading.local()


def use(lang):
    _local.lang = lang if lang in LANGUAGES else 'en'


def current():
    return getattr(_local, 'lang', 'en')


def _(text, **kw):
    text = _CATALOGS.get(current(), {}).get(text, text)
    return text.format(**kw) if kw else text
