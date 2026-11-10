# -*- coding: utf-8 -*-
"""The bot's languages: every text the code asks for has a Russian version with the same
placeholders, and a user who picks Russian gets Russian screens."""
import ast
import glob
import os
import re
import string

import pytest

import plugins.telegram_bot.bot as botmod
from plugins.telegram_bot import i18n
from plugins.telegram_bot.lang_ru import RU
from plugins.telegram_bot.panel_users import HINT
from plugins.telegram_bot.vpn_bot import ADMIN_ONLY

PKG = os.path.dirname(botmod.__file__)


@pytest.fixture(autouse=True)
def _back_to_english():
    yield
    i18n.use('en')


def _keys_in_code():
    keys = set()
    for path in glob.glob(os.path.join(PKG, '*.py')):
        for node in ast.walk(ast.parse(open(path, encoding='utf-8').read())):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == '_' and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                keys.add(node.args[0].value)
    # texts kept in constants and passed to _() by name
    keys |= {botmod.HELP, botmod.PRIVATE_ONLY, botmod.RULES_MOVED, HINT, ADMIN_ONLY}
    for label, _confirm, word in botmod.GUEST_ACTIONS.values():
        keys |= {label, word}
    keys |= {d for _c, d in botmod.COMMANDS}
    return keys


def _fields(text):
    return sorted(f for _lit, f, _spec, _conv in string.Formatter().parse(text) if f)


def test_every_text_has_a_russian_version():
    missing = sorted(_keys_in_code() - set(RU))
    assert not missing, missing


def test_no_russian_text_is_left_over():
    assert not sorted(set(RU) - _keys_in_code())


@pytest.mark.parametrize('key', sorted(RU))
def test_placeholders_and_markup_match(key):
    assert _fields(key) == _fields(RU[key])
    assert re.findall(r'</?\w+>', key) == re.findall(r'</?\w+>', RU[key])


def test_english_is_the_default_and_unknown_languages_fall_back():
    i18n.use('xx')
    assert i18n._('Cancel') == 'Cancel'
    i18n.use('ru')
    assert i18n._('Found: {count}', count=3) == 'Найдено: 3'


def test_a_user_switches_to_russian(tmp_path):
    from tests.test_tgbot import FakeApi, FakeTG, TOKEN, UID, msg, dec, enc
    from plugins.telegram_bot import Settings
    from plugins.telegram_bot.store import Store
    tg = FakeTG()
    bot = botmod.Bot(Settings({'alert_poll': 0}), tg, Store(str(tmp_path), enc, dec),
                     api_factory=lambda t: FakeApi(t, [], set()))
    bot.handle_update(msg(f'/login {TOKEN}'))
    assert 'Clusters' in tg.sent[-1][1]
    bot.handle_update(msg('/lang ru'))
    assert tg.sent[-1][1] == 'Язык: русский'
    bot.handle_update(msg('/menu'))
    text, kb = tg.sent[-1][1], tg.sent[-1][2]
    assert 'Кластеры' in text and any('Оповещения' in b['text'] for row in kb for b in row)
    assert bot.store.get(UID)['lang'] == 'ru'
    bot.handle_update(msg('/lang en'))
    bot.handle_update(msg('/menu'))
    assert '<b>Clusters</b>' in tg.sent[-1][1]


def test_the_plugin_default_language_applies_until_a_user_picks_one(tmp_path):
    from tests.test_tgbot import FakeApi, FakeTG, TOKEN, msg, dec, enc
    from plugins.telegram_bot import Settings
    from plugins.telegram_bot.store import Store
    tg = FakeTG()
    bot = botmod.Bot(Settings({'alert_poll': 0, 'language': 'ru'}), tg, Store(str(tmp_path), enc, dec),
                     api_factory=lambda t: FakeApi(t, [], set()))
    bot.handle_update(msg('/help'))
    assert 'Управление Proxmox' in tg.sent[-1][1]
    bot.handle_update(msg(f'/login {TOKEN}'))
    bot.poll_alerts()
    assert 'Кластер: Home' in tg.sent[-1][1] and tg.sent[-1][2][0][0]['text'] == '✔️ Подтвердить'
