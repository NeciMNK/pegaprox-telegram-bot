# -*- coding: utf-8 -*-
"""The VPN for Telegram: parsing a subscription, the xray config, the settings routes,
failover to the next server, and /vpn in the bot. No network: downloads, xray and the
Telegram check are replaced."""
import base64
import json
import os
import shutil
import subprocess

import pytest

from plugins.telegram_bot import vpn
from tests.test_telegram_bot_plugin import _admin, plugin  # noqa: F401  (the plugin fixture)

UUID = '11111111-2222-3333-4444-555555555555'
PBK = 'pUbLiCkEy_' + 'x' * 33
VLESS_GRPC = (f'vless://{UUID}@nl.example.net:8445?encryption=none&type=grpc&serviceName=grpc-service&mode=gun'
              f'&security=reality&sni=www.cloudflare.com&fp=chrome&pbk={PBK}#%F0%9F%87%B3%F0%9F%87%B1Pure%20NL')
VLESS_XHTTP = (f'vless://{UUID}@nl.example.net:8444?encryption=none&type=xhttp&path=%2Fxhttp&mode=auto'
               f'&security=reality&sni=www.cloudflare.com&fp=chrome&pbk={PBK}&sid=ab12#NL%20XHTTP')
HY2 = 'hysteria2://secret@nl.example.net:8443?obfs=salamander&obfs-password=pw&sni=nl.example.net#Hysteria'
TROJAN_WS = 'trojan://pass123@de.example.net:443?type=ws&path=%2Fws&host=de.example.net&security=tls&sni=de.example.net#DE'
VMESS = 'vmess://' + base64.b64encode(json.dumps({
    'v': '2', 'ps': 'VMess RU', 'add': 'ru.example.net', 'port': '443', 'id': UUID, 'aid': '0',
    'net': 'ws', 'path': '/v', 'host': 'ru.example.net', 'tls': 'tls', 'sni': 'ru.example.net'}).encode()).decode()
SS = 'ss://' + base64.urlsafe_b64encode(b'chacha20-ietf-poly1305:sspass').decode().rstrip('=') + '@ss.example.net:8388#SS'
LINKS = [VLESS_GRPC, HY2, VLESS_XHTTP, TROJAN_WS, VMESS, SS]
SUB = base64.b64encode('\n'.join(LINKS).encode())


def nodes():
    return [vpn.parse_link(x) for x in vpn.parse_subscription(SUB)]


# ------------------------------------------------------------------ parsing
def test_a_base64_subscription_and_a_plain_one_give_the_same_servers():
    assert vpn.parse_subscription(SUB) == LINKS
    assert vpn.parse_subscription('\n'.join(LINKS) + '\n') == LINKS
    with pytest.raises(vpn.SubscriptionError):
        vpn.parse_subscription(b'<html>not found</html>')


def test_the_servers_and_what_is_supported():
    got = [(n['name'], n['scheme'], n['host'], n['port'], n['supported']) for n in nodes()]
    assert got == [
        ('🇳🇱Pure NL', 'vless', 'nl.example.net', 8445, True),
        ('Hysteria', 'hysteria2', 'nl.example.net', 8443, False),
        ('NL XHTTP', 'vless', 'nl.example.net', 8444, True),
        ('DE', 'trojan', 'de.example.net', 443, True),
        ('VMess RU', 'vmess', 'ru.example.net', 443, True),
        ('SS', 'ss', 'ss.example.net', 8388, True),
    ]


def test_what_is_shown_carries_no_secret():
    shown = json.dumps([vpn.describe(n) for n in nodes()])
    for secret in (UUID, PBK, 'pass123', 'sspass', 'secret'):
        assert secret not in shown


def test_vless_grpc_reality_outbound():
    out = vpn.outbound(nodes()[0])
    assert out['protocol'] == 'vless' and out['tag'] == 'proxy'
    assert out['settings']['vnext'] == [{'address': 'nl.example.net', 'port': 8445,
                                         'users': [{'id': UUID, 'encryption': 'none', 'flow': ''}]}]
    st = out['streamSettings']
    assert st['network'] == 'grpc' and st['security'] == 'reality'
    assert st['realitySettings'] == {'serverName': 'www.cloudflare.com', 'fingerprint': 'chrome',
                                     'publicKey': PBK, 'shortId': '', 'spiderX': ''}
    assert st['grpcSettings'] == {'serviceName': 'grpc-service', 'multiMode': False}


def test_other_transports():
    by_name = {n['name']: n for n in nodes()}
    x = vpn.outbound(by_name['NL XHTTP'])['streamSettings']
    assert x['xhttpSettings'] == {'path': '/xhttp', 'mode': 'auto'} and x['realitySettings']['shortId'] == 'ab12'
    t = vpn.outbound(by_name['DE'])
    assert t['settings']['servers'][0]['password'] == 'pass123'
    assert t['streamSettings']['wsSettings'] == {'path': '/ws', 'host': 'de.example.net'}
    assert t['streamSettings']['tlsSettings']['serverName'] == 'de.example.net'
    m = vpn.outbound(by_name['VMess RU'])
    assert m['settings']['vnext'][0]['users'][0]['id'] == UUID and m['streamSettings']['security'] == 'tls'
    s = vpn.outbound(by_name['SS'])
    assert s['settings']['servers'][0] == {'address': 'ss.example.net', 'port': 8388,
                                           'method': 'chacha20-ietf-poly1305', 'password': 'sspass'}
    with pytest.raises(vpn.SubscriptionError):
        vpn.outbound(by_name['Hysteria'])


def test_pick_puts_the_preferred_server_first_and_skips_unsupported():
    order = [n['name'] for n in vpn.pick(nodes(), 'DE')]
    assert order[0] == 'DE' and 'Hysteria' not in order and len(order) == 5
    assert vpn.pick(nodes(), 'gone')[0]['name'] == '🇳🇱Pure NL'


def test_the_config_listens_only_on_localhost():
    cfg = vpn.xray_config(nodes()[0], 10810)
    assert cfg['inbounds'] == [{'tag': 'http', 'listen': '127.0.0.1', 'port': 10810, 'protocol': 'http'}]


def test_the_xray_folder_is_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = vpn.XrayRunner(os.path.join('config', 'telegram_bot', 'vpn'))
    assert runner.workdir == str(tmp_path / 'config' / 'telegram_bot' / 'vpn')


@pytest.mark.skipif(not vpn.find_xray(), reason='xray is not installed here')
def test_xray_accepts_every_config(tmp_path):
    for n in vpn.pick(nodes()):
        path = tmp_path / 'c.json'
        path.write_text(json.dumps(vpn.xray_config(n, 10810)))
        r = subprocess.run([vpn.find_xray(), 'run', '-test', '-c', str(path)], capture_output=True, text=True)
        assert r.returncode == 0, (n['name'], r.stdout[-500:])


class Resp:
    def __init__(self, status, body):
        self.status_code, self.content, self.raw = status, body, None


class Http:
    def __init__(self, resp):
        self.resp, self.seen = resp, []

    def get(self, url, **kw):
        self.seen.append((url, kw))
        return self.resp


def test_fetch():
    http = Http(Resp(200, SUB))
    assert len(vpn.fetch('https://sub.example.net/abc', session=http)) == 6
    assert 'v2rayN' in http.seen[0][1]['headers']['User-Agent']
    with pytest.raises(vpn.SubscriptionError, match='HTTP 404'):
        vpn.fetch('https://sub.example.net/abc', session=Http(Resp(404, b'')))
    with pytest.raises(vpn.SubscriptionError):
        vpn.fetch('file:///etc/passwd')


# ------------------------------------------------------------------ the plugin
class FakeRunner:
    """XrayRunner without xray: remembers which server it was started on."""
    started = []

    def __init__(self, workdir, port=10810):
        self.port, self.node, self._on = port, None, False

    @property
    def proxy(self):
        return f'http://127.0.0.1:{self.port}' if self._on else ''

    def running(self):
        return self._on

    def start(self, node, xray_bin):
        FakeRunner.started.append(node['name'])
        self.node, self._on = node, True

    def stop(self):
        self.node, self._on = None, False


@pytest.fixture
def vpn_plugin(plugin, monkeypatch):
    monkeypatch.setattr(plugin.vpn, 'fetch', lambda url, **kw: nodes())
    monkeypatch.setattr(plugin.vpn, 'XrayRunner', FakeRunner)
    monkeypatch.setattr(plugin.vpn, 'find_xray', lambda configured='': '/usr/local/bin/xray')
    reachable = {'🇳🇱Pure NL', 'NL XHTTP', 'DE', 'VMess RU', 'SS'}
    monkeypatch.setattr(plugin.vpn, 'check_telegram',
                        lambda proxy, **kw: plugin._vpn.runner.node['name'] in reachable)
    monkeypatch.setattr(plugin, '_vpn', plugin.VpnControl())
    FakeRunner.started[:] = []
    plugin.reachable = reachable
    yield plugin
    plugin._vpn.stop()


def _url(path):
    return f'/api/plugins/telegram_bot/api/{path}'


def test_the_subscription_url_is_saved_encrypted_and_never_shown(api, seed, vpn_plugin):
    admin = _admin(api, seed)
    url = 'https://sub.example.net/very-secret-path'
    r = admin.post(_url('settings/update'), json={'vpn_url': url, 'vpn_refresh_hours': 12})
    assert r.status_code == 200, r.get_json()
    raw = open(os.path.join(vpn_plugin.data_dir(), 'settings.json'), encoding='utf-8').read()
    assert 'very-secret-path' not in raw
    assert vpn_plugin.load_settings()['vpn_url'] == url
    vpn_plugin._vpn.refresh()
    body = admin.get(_url('settings')).get_json()
    assert 'very-secret-path' not in json.dumps(body) and UUID not in json.dumps(body)
    assert body['vpn']['configured'] and body['vpn']['refresh_hours'] == 12
    assert body['vpn']['current']['name'] == '🇳🇱Pure NL' and body['vpn']['telegram_ok']
    assert len(body['vpn']['servers']) == 6
    assert admin.post(_url('settings/update'), json={'vpn_url': 'ftp://x'}).status_code == 400
    assert admin.post(_url('settings/update'), json={'vpn_refresh_hours': 1000}).status_code == 400
    assert admin.post(_url('settings/update'), json={'xray_bin': 'xray; rm -rf /'}).status_code == 400
    assert admin.post(_url('settings/update'), json={'clear_vpn': True}).status_code == 200
    assert vpn_plugin.load_settings()['vpn_url'] == ''


def test_vpn_routes_are_for_admins_only(api, seed, vpn_plugin):
    viewer = api.as_user(seed.user('val', role='viewer'))
    assert viewer.post(_url('vpn/refresh'), json={}).status_code == 403
    assert viewer.post(_url('settings/update'), json={'vpn_url': 'https://x.example'}).status_code == 403


def test_the_proxy_follows_the_vpn(vpn_plugin):
    s = dict(vpn_plugin.DEFAULTS, proxy='http://10.0.0.1:3128')
    assert vpn_plugin.effective_proxy(s) == 'http://10.0.0.1:3128'
    vpn_plugin.save_settings(dict(s, vpn_url='https://sub.example.net/x'))
    vpn_plugin._vpn.refresh()
    assert vpn_plugin.effective_proxy(vpn_plugin.load_settings()) == 'http://127.0.0.1:10810'


def test_a_server_that_does_not_reach_telegram_is_skipped(vpn_plugin):
    vpn_plugin.reachable.discard('🇳🇱Pure NL')
    vpn_plugin.save_settings(dict(vpn_plugin.DEFAULTS, vpn_url='https://sub.example.net/x'))
    assert vpn_plugin._vpn.refresh()
    assert FakeRunner.started == ['🇳🇱Pure NL', 'NL XHTTP']


def test_the_preferred_server_and_use(vpn_plugin):
    vpn_plugin.save_settings(dict(vpn_plugin.DEFAULTS, vpn_url='https://sub.example.net/x', vpn_server='DE'))
    vpn_plugin._vpn.refresh()
    assert vpn_plugin._vpn.runner.node['name'] == 'DE'
    vpn_plugin._vpn.use('SS')
    assert vpn_plugin._vpn.runner.node['name'] == 'SS' and vpn_plugin.load_settings()['vpn_server'] == 'SS'


def test_failover_when_telegram_stops_answering(vpn_plugin):
    class TG:
        failures = 0
    vpn_plugin.save_settings(dict(vpn_plugin.DEFAULTS, vpn_url='https://sub.example.net/x'))
    tg = TG()
    vpn_plugin._vpn.tick(tg)  # first tick starts xray
    assert vpn_plugin._vpn.runner.node['name'] == '🇳🇱Pure NL'
    tg.failures = vpn_plugin.VPN_FAILOVER_AFTER
    vpn_plugin._vpn.tick(tg)  # too soon after the start: no failover yet
    assert vpn_plugin._vpn.runner.node['name'] == '🇳🇱Pure NL'
    vpn_plugin._vpn.last_failover -= vpn_plugin.VPN_FAILOVER_PAUSE + 1
    vpn_plugin._vpn.tick(tg)
    assert vpn_plugin._vpn.runner.node['name'] == 'NL XHTTP' and tg.failures == 0


def test_the_timer_downloads_the_subscription_again(vpn_plugin, monkeypatch):
    calls = []
    monkeypatch.setattr(vpn_plugin.vpn, 'fetch', lambda url, **kw: calls.append(url) or nodes())
    vpn_plugin.save_settings(dict(vpn_plugin.DEFAULTS, vpn_url='https://sub.example.net/x', vpn_refresh_hours=6))
    vpn_plugin._vpn.tick(None)
    vpn_plugin._vpn.tick(None)
    assert len(calls) == 1
    vpn_plugin._vpn.last_refresh -= 6 * 3600 + 1
    vpn_plugin._vpn.tick(None)
    assert len(calls) == 2


def test_removing_the_subscription_stops_xray(vpn_plugin):
    vpn_plugin.save_settings(dict(vpn_plugin.DEFAULTS, vpn_url='https://sub.example.net/x'))
    vpn_plugin._vpn.tick(None)
    assert vpn_plugin._vpn.running()
    vpn_plugin.save_settings(dict(vpn_plugin.DEFAULTS))
    vpn_plugin._vpn.tick(None)
    assert not vpn_plugin._vpn.running()


# ------------------------------------------------------------------ /vpn in the bot
class FakeVpn:
    def __init__(self):
        self.used, self.refreshed = [], 0

    def status(self):
        servers = [vpn.describe(n) for n in nodes()]
        return {'configured': True, 'current': servers[0], 'servers': servers, 'telegram_ok': True,
                'last_refresh': '2026-11-10 06:00:00', 'last_error': '', 'preferred': '', 'refresh_hours': 6,
                'xray_bin': '/usr/local/bin/xray'}

    def use(self, name):
        self.used.append(name)

    def refresh(self):
        self.refreshed += 1


def _bot(tmp_path, role):
    from tests.test_tgbot import FakeApi, FakeTG, TOKEN, msg, dec, enc
    from plugins.telegram_bot import Settings
    from plugins.telegram_bot.bot import Bot
    from plugins.telegram_bot.store import Store

    class Api(FakeApi):
        def me(self):
            return dict(super().me(), role=role, effective_role=role)
    tg = FakeTG()
    bot = Bot(Settings({'alert_poll': 0}), tg, Store(str(tmp_path), enc, dec), api_factory=lambda t: Api(t, [], set()))
    bot.vpn = FakeVpn()
    bot.handle_update(msg(f'/login {TOKEN}'))
    return bot, tg, msg


def test_vpn_command_is_for_admins_only(tmp_path):
    bot, tg, msg = _bot(tmp_path, 'user')
    bot.handle_update(msg('/vpn'))
    assert '⛔' in tg.sent[-1][1] and not tg.sent[-1][2]


def test_an_admin_sees_the_server_and_switches(tmp_path):
    from tests.test_tgbot import UID
    bot, tg, msg = _bot(tmp_path, 'admin')
    bot.handle_update(msg('/vpn'))
    text, kb = tg.sent[-1][1], tg.sent[-1][2]
    assert 'Pure NL' in text and UUID not in text and PBK not in text
    labels = [b['text'] for row in kb for b in row]
    assert '● 🇳🇱Pure NL' in labels and not any('Hysteria' in x for x in labels)
    de = next(b for row in kb for b in row if b['text'] == 'DE')
    bot.handle_update({'update_id': 9, 'callback_query': {
        'id': 'q1', 'from': {'id': UID}, 'data': de['callback_data'],
        'message': {'message_id': 3, 'chat': {'id': UID, 'type': 'private'}}}})
    assert bot.vpn.used == ['DE']
