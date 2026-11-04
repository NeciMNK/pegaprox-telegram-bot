# -*- coding: utf-8 -*-
"""The plugin around the bot: loading into PegaProx, the admin-only settings routes, and
the background task (it links a real PegaProx token in-process and stops when the plugin
is switched off)."""
import json
import os
import stat
import sys
import threading
import time

import pytest

from pegaprox.utils.auth import create_api_token

PID = 'telegram_bot'
BOT_TOKEN = '123456789:' + 'A' * 35


@pytest.fixture
def plugin(api, monkeypatch, tmp_path):
    import pegaprox.api.plugins as plugins
    import pegaprox.constants as constants
    monkeypatch.setattr(constants, 'CONFIG_DIR', str(tmp_path / 'config'))
    monkeypatch.setattr(plugins, '_loaded_plugins', dict(plugins._loaded_plugins))
    monkeypatch.setattr(plugins, '_plugin_routes', dict(plugins._plugin_routes))
    plugins.unload_plugin(PID)
    ok, err = plugins.load_plugin(api.app, PID)
    assert ok, err
    plugins._set_plugin_state(PID, True)
    mod = plugins._loaded_plugins[PID]
    yield mod
    plugins.unload_plugin(PID)


def _admin(api, seed):
    return api.as_user(seed.user('boss', role='admin'))


def _url(path):
    return f'/api/plugins/{PID}/api/{path}'


def test_settings_are_for_admins_only(api, seed, plugin):
    viewer = api.as_user(seed.user('val', role='viewer'))
    assert viewer.get(_url('settings')).status_code == 403
    assert viewer.post(_url('settings/update'), json={'alert_poll': 0}).status_code == 403
    assert viewer.get(_url('ui')).status_code == 403
    r = _admin(api, seed).get(_url('settings'))
    assert r.status_code == 200
    body = r.get_json()
    assert body['token_set'] is False and body['accounts'] == [] and body['alert_poll'] == 60


def test_an_admin_token_scoped_to_viewer_is_no_admin_here(api, seed, plugin):
    seed.user('boss', role='admin')
    token = create_api_token('boss', 'look only', role='viewer')['token']
    r = api.app.test_client().get(_url('settings'), headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 403


def test_the_bot_token_is_checked_saved_encrypted_and_never_shown(api, seed, plugin, monkeypatch):
    admin = _admin(api, seed)
    asked = []

    def fake_call(self, method, params):
        asked.append(method)
        return ({'username': 'my_pp_bot'}, '') if BOT_TOKEN in self.url else (None, 'Unauthorized')

    monkeypatch.setattr(plugin.Telegram, '_call', fake_call)
    r = admin.post(_url('settings/update'), json={'bot_token': '1:short'})
    assert r.status_code == 400
    r = admin.post(_url('settings/update'), json={'bot_token': '123456789:' + 'B' * 35})
    assert r.status_code == 400 and 'did not accept' in r.get_json()['error']
    r = admin.post(_url('settings/update'), json={
        'bot_token': BOT_TOKEN, 'allowed_ids': '42, 7', 'alert_poll': 120, 'proxy': 'http://127.0.0.1:10809'})
    assert r.status_code == 200, r.get_json()
    assert asked == ['getMe', 'getMe']

    path = os.path.join(plugin.data_dir(), 'settings.json')
    raw = open(path, encoding='utf-8').read()
    assert BOT_TOKEN not in raw
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert plugin.load_settings()['bot_token'] == BOT_TOKEN

    body = admin.get(_url('settings')).get_json()
    assert BOT_TOKEN not in json.dumps(body)
    assert body['token_set'] and body['allowed_ids'] == [7, 42] and body['alert_poll'] == 120
    assert body['status']['bot_username'] == 'my_pp_bot'

    assert admin.post(_url('settings/update'), json={'alert_poll': 5}).status_code == 400
    assert admin.post(_url('settings/update'), json={'allowed_ids': 'abc'}).status_code == 400
    assert admin.post(_url('settings/update'), json={'proxy': 'file:///etc/passwd'}).status_code == 400
    assert admin.post(_url('settings/update'), json={'clear_token': True}).status_code == 200
    assert plugin.load_settings()['bot_token'] == ''


def test_the_settings_page_is_served(api, seed, plugin):
    r = _admin(api, seed).get(_url('ui'))
    assert r.status_code == 200 and r.mimetype == 'text/html'
    assert b'settings/update' in r.data


class FakeTelegram:
    """Telegram for the background task: hands out queued updates, records the replies."""
    updates_q = []
    sent = []
    deleted = []

    def __init__(self, token, proxy=None):
        self.token = token

    def call(self, method, **params):
        return {'username': 'my_pp_bot'} if method == 'getMe' else True

    def updates(self, offset=None, timeout=50):
        time.sleep(0.05)
        out, FakeTelegram.updates_q[:] = list(FakeTelegram.updates_q), []
        return out

    def send(self, chat, text, keyboard=None, **kw):
        FakeTelegram.sent.append((chat, text))
        return {'message_id': len(FakeTelegram.sent)}

    def edit(self, chat, mid, text, keyboard=None):
        return self.send(chat, text, keyboard)

    def delete(self, chat, mid):
        FakeTelegram.deleted.append((chat, mid))
        return True

    def answer(self, *a, **k):
        return True

    def set_commands(self, commands):
        return True


def _wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_the_background_task_links_a_real_token_and_stops_when_disabled(api, seed, plugin, monkeypatch):
    import pegaprox.api.plugins as plugins
    seed.user('nikita', role='admin')
    pp_token = create_api_token('nikita', 'telegram', role='viewer')['token']
    plugin.save_settings(dict(plugin.DEFAULTS, bot_token=BOT_TOKEN, alert_poll=0))
    monkeypatch.setattr(plugin, 'Telegram', FakeTelegram)
    FakeTelegram.updates_q[:] = [{'update_id': 1, 'message': {
        'message_id': 5, 'from': {'id': 77, 'username': 'nik'}, 'chat': {'id': 77, 'type': 'private'},
        'text': f'/login {pp_token}'}}]
    FakeTelegram.sent[:] = []

    plugin.start_background_tasks()
    assert _wait(lambda: plugin.store().token(77) == pp_token), FakeTelegram.sent
    assert (77, 5) in FakeTelegram.deleted
    assert any('viewer' in text for _, text in FakeTelegram.sent)  # the token's role, read through PegaProx
    assert plugin._status['running'] and plugin._status['bot_username'] == 'my_pp_bot'

    thread = plugin._thread
    plugins.unload_plugin(PID)  # what Settings -> Plugins -> disable does
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_the_task_stops_when_the_plugin_is_switched_off_elsewhere(api, seed, plugin, monkeypatch):
    import pegaprox.api.plugins as plugins
    plugin.save_settings(dict(plugin.DEFAULTS, bot_token=BOT_TOKEN, alert_poll=0))
    monkeypatch.setattr(plugin, 'Telegram', FakeTelegram)
    FakeTelegram.updates_q[:] = []
    plugin.start_background_tasks()
    assert _wait(lambda: plugin._status['running'])
    plugin.start_background_tasks()  # a second start (enable on a loaded plugin) adds no poller
    assert sum(t.name == plugin.THREAD_NAME for t in threading.enumerate()) == 1
    plugins._set_plugin_state(PID, False)  # an HA standby following the leader
    plugin._thread.join(timeout=10)
    assert not plugin._thread.is_alive()


def test_an_admin_can_unlink_an_account(api, seed, plugin):
    plugin.store().link(55, 'pgx_ab12_' + 'x' * 43, {'role': 'user', 'tg_name': 'olga'})
    admin = _admin(api, seed)
    accounts = admin.get(_url('settings')).get_json()['accounts']
    assert accounts == [{'tg_id': 55, 'tg_name': 'olga', 'role': 'user', 'notify': True}]
    assert admin.post(_url('accounts/unlink'), json={'tg_id': 55}).status_code == 200
    assert plugin.store().token(55) is None
    assert admin.post(_url('accounts/unlink'), json={'tg_id': 55}).status_code == 404


def test_a_reload_runs_the_new_code(api, plugin):
    import pegaprox.api.plugins as plugins
    old_bot = sys.modules['plugins.telegram_bot.bot']
    plugins.unload_plugin(PID)
    ok, err = plugins.load_plugin(api.app, PID)
    assert ok, err
    assert sys.modules['plugins.telegram_bot.bot'] is not old_bot
    assert plugins._loaded_plugins[PID].Bot is sys.modules['plugins.telegram_bot.bot'].Bot
