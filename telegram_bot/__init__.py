# -*- coding: utf-8 -*-
"""Telegram bot for PegaProx, as a PegaProx plugin.

Each Telegram user links their own PegaProx account with an API token, and every action
goes through PegaProx's own API under that token, inside the PegaProx process. The user can
do in Telegram exactly what their role allows in the web UI, and the audit log shows it
under their name.

The plugin adds:
- a background task that long-polls Telegram while the plugin is enabled,
- admin-only settings routes (bot token, allowed Telegram ids, alert interval, proxy, VPN),
- an optional VPN: xray run from a subscription URL, refreshed on a timer (vpn.py),
- a settings page (manifest frontend_route 'ui').
"""
import json
import logging
import os
import re
import sys
import threading
import time

from flask import Response, request

PID = 'telegram_bot'
THREAD_NAME = 'pegaprox-telegram-bot'

# A reload loads this package again under the same name. Drop the old submodules first,
# or the new package would keep running the old code.
for _name in [n for n in sys.modules if n.startswith(__name__ + '.')]:
    del sys.modules[_name]

from .bot import Bot, COMMANDS  # noqa: E402
from .i18n import LANGUAGES  # noqa: E402
from .lang_ru import RU  # noqa: E402
from .pegaprox_client import InProcess, PegaProx  # noqa: E402
from .store import Store  # noqa: E402
from .telegram import Telegram  # noqa: E402
from . import vpn  # noqa: E402

log = logging.getLogger('plugin.telegram_bot')

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_TOKEN_RE = re.compile(r'^\d{5,15}:[A-Za-z0-9_-]{30,64}$')
PROXY_RE = re.compile(r'^(https?|socks5h?)://[^\s/?#]+/?$')
VPN_URL_RE = re.compile(r'^https?://[^\s]{4,2000}$')
DEFAULTS = {'bot_token': '', 'allowed_ids': [], 'alert_poll': 60, 'proxy': '', 'language': 'en',
            'vpn_url': '', 'vpn_server': '', 'vpn_refresh_hours': 6, 'xray_bin': ''}
SECRETS = ('bot_token', 'vpn_url')
VPN_FAILOVER_AFTER = 6   # Telegram calls in a row that failed before the next server is tried
VPN_FAILOVER_PAUSE = 120  # seconds between two failovers

_SELF = sys.modules.get(__name__)
_app = None
_thread = None
_settings_lock = threading.Lock()
_status = {'running': False, 'bot_username': '', 'last_error': '', 'started_at': None}
_store = None


# ------------------------------------------------------------------ storage
def data_dir():
    from pegaprox.constants import CONFIG_DIR
    return os.path.join(CONFIG_DIR, PID)


def _db():
    from pegaprox.core.db import get_db
    return get_db()


def _encrypt(value):
    return _db()._encrypt(value)


def _decrypt(value):
    return _db()._decrypt(value)


def store():
    global _store
    if _store is None or _store.data_dir != data_dir():
        _store = Store(data_dir(), _encrypt, _decrypt)
    return _store


def load_settings():
    """Settings with the bot token decrypted. Lives next to the PegaProx database, not in
    the plugin folder, so the core's plugin config editor never shows the token."""
    path = os.path.join(data_dir(), 'settings.json')
    out = dict(DEFAULTS)
    try:
        with open(path, encoding='utf-8') as f:
            out.update(json.load(f))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        log.warning('Telegram bot settings unreadable: %s', e.__class__.__name__)
    for key in SECRETS:
        try:
            out[key] = _decrypt(out[key]) if out[key] else ''
        except Exception:
            out[key] = ''
    return out


def save_settings(settings):
    os.makedirs(data_dir(), mode=0o700, exist_ok=True)
    stored = dict(settings)
    for key in SECRETS:
        stored[key] = _encrypt(settings[key]) if settings.get(key) else ''
    path = os.path.join(data_dir(), 'settings.json')
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(stored, f, indent=1)
    os.replace(tmp, path)


class Settings:
    """What Bot reads from its config."""

    def __init__(self, s):
        self.allowed_ids = set(s.get('allowed_ids') or [])
        self.alert_poll = int(s.get('alert_poll') or 0)
        self.language = s.get('language') if s.get('language') in LANGUAGES else 'en'


# ------------------------------------------------------------------ VPN
class VpnControl:
    """The plugin's xray: started from the subscription, refreshed on a timer, and moved to
    the next server when Telegram stays unreachable. Used by the bot loop, the settings
    routes and /vpn, from different threads."""

    def __init__(self):
        self.runner = None
        self.servers = []  # parsed nodes from the last download, keys included: never sent out
        self.url = ''
        self.last_refresh = 0.0
        self.last_failover = 0.0
        self.last_error = ''
        self.telegram_ok = False
        self.lock = threading.RLock()

    def _runner(self):
        if self.runner is None:
            self.runner = vpn.XrayRunner(os.path.join(data_dir(), 'vpn'))
        return self.runner

    @property
    def proxy(self):
        return self.runner.proxy if self.runner else ''

    def running(self):
        return bool(self.runner and self.runner.running())

    def status(self):
        s = load_settings()
        node = self.runner.node if self.running() else None
        return {
            'configured': bool(s['vpn_url']),
            'xray_bin': vpn.find_xray(s['xray_bin']),
            'current': vpn.describe(node) if node else None,
            'servers': [vpn.describe(n) for n in self.servers],
            'preferred': s['vpn_server'],
            'refresh_hours': s['vpn_refresh_hours'],
            'last_refresh': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.last_refresh))
            if self.last_refresh else '',
            'last_error': self.last_error,
            'telegram_ok': self.telegram_ok,
        }

    def refresh(self, rotate=False, prefer=None):
        """Download the subscription, start xray on the preferred server and check Telegram
        through it; when that fails, try the other servers. rotate: begin after the current one."""
        s = load_settings()
        with self.lock:
            if not s['vpn_url']:
                self._stop()
                self.servers, self.url = [], ''
                return False
            self.url = s['vpn_url']
            self.last_refresh = time.time()  # also on failure, so the timer does not hammer the host
            xray_bin = vpn.find_xray(s['xray_bin'])
            if not xray_bin:
                self.last_error = 'xray not found: install it or set its path'
                return False
            try:
                self.servers = vpn.fetch(s['vpn_url'])
            except vpn.SubscriptionError as e:
                self.last_error = str(e)
                if not self.servers:
                    return False
                # keep the servers from the last download: the subscription host may be down
            order = vpn.pick(self.servers, s['vpn_server'] if prefer is None else prefer)
            if not order:
                self.last_error = 'the subscription has no server this plugin can use (VLESS, VMess, Trojan, Shadowsocks)'
                return False
            names = [n['name'] for n in order]
            current = (self._runner().node or {}).get('name')
            if rotate and current in names:
                i = names.index(current)
                order = order[i + 1:] + order[:i + 1]
            errors = []
            for node in order:
                try:
                    self._runner().start(node, xray_bin)
                except vpn.SubscriptionError as e:
                    errors.append(f"{node['name']}: {e}")
                    continue
                if vpn.check_telegram(self.proxy):
                    self.telegram_ok = True
                    self.last_error = ''
                    log.info('VPN for Telegram: %s', node['name'])
                    return True
                errors.append(f"{node['name']}: Telegram not reachable")
            self.telegram_ok = False
            self.last_error = '; '.join(errors)[:500]
            log.warning('VPN: no server reaches Telegram: %s', self.last_error)
            try:  # keep the first choice running: Telegram may be down only for a moment
                self._runner().start(order[0], xray_bin)
            except vpn.SubscriptionError:
                pass
            return False

    def use(self, name):
        """Switch to a server by name and remember it as the preferred one."""
        with _settings_lock:
            s = load_settings()
            s['vpn_server'] = name
            save_settings(s)
        return self.refresh(prefer=name)

    def tick(self, tg):
        """Called by the bot loop: start xray, refresh on the timer, fail over when needed."""
        s = load_settings()
        if not s['vpn_url']:
            if self.running():
                self.stop()
            return
        now = time.time()
        hours = s['vpn_refresh_hours']
        due = hours and now - self.last_refresh >= hours * 3600
        if self.url != s['vpn_url'] or not self.running() or due:
            # a dead xray is retried at most every VPN_FAILOVER_PAUSE seconds
            if self.url != s['vpn_url'] or due or now - self.last_failover >= VPN_FAILOVER_PAUSE:
                self.last_failover = now
                self.refresh()
        elif tg is not None and tg.failures >= VPN_FAILOVER_AFTER and now - self.last_failover >= VPN_FAILOVER_PAUSE:
            log.warning('Telegram unreachable through %s, trying the next VPN server',
                        (self.runner.node or {}).get('name'))
            self.last_failover = now
            self.refresh(rotate=True)
            tg.failures = 0
        elif tg is not None:
            self.telegram_ok = tg.failures == 0

    def stop(self):
        with self.lock:
            self._stop()

    def _stop(self):
        if self.runner:
            self.runner.stop()
        self.telegram_ok = False


_vpn = VpnControl()


def effective_proxy(s):
    """The VPN's local proxy when a subscription is set, else the manual proxy."""
    if s.get('vpn_url'):
        return _vpn.proxy or None
    return s['proxy'] or None


# ------------------------------------------------------------------ routes
def _require_admin():
    # the token-floored effective role, as every core gate uses (same check as the
    # bundled notifications plugin)
    from pegaprox.utils.auth import build_authz_user
    from pegaprox.utils.rbac import acts_as_admin
    if not acts_as_admin(build_authz_user(request.session.get('user', ''), request.session)):
        return {'error': 'Admin access required'}, 403
    return None


def _audit(action, details):
    try:
        from pegaprox.utils.audit import log_audit
        log_audit(request.session.get('user', 'system'), action, details, ip_address=request.remote_addr)
    except Exception:
        pass


def route_settings():
    denied = _require_admin()
    if denied:
        return denied
    s = load_settings()
    return {
        'token_set': bool(s['bot_token']),
        'allowed_ids': sorted(s['allowed_ids']),
        'alert_poll': s['alert_poll'],
        'proxy': s['proxy'],
        'language': s['language'],
        'vpn': _vpn.status(),
        'languages': LANGUAGES,
        'status': dict(_status, running=bool(_thread and _thread.is_alive() and _status['running'])),
        'accounts': [{'tg_id': tid, 'tg_name': info.get('tg_name') or '', 'role': info.get('role') or '',
                      'notify': notify, 'lang': lang} for tid, info, notify, lang in store().accounts()],
    }


def _parse_ids(raw):
    if isinstance(raw, str):
        raw = [x for x in re.split(r'[\s,;]+', raw) if x]
    if not isinstance(raw, list):
        raise ValueError('allowed_ids must be a list of Telegram user ids')
    ids = []
    for x in raw:
        if isinstance(x, bool) or not re.fullmatch(r'\d{1,20}', str(x).strip()):
            raise ValueError(f'Not a Telegram user id: {str(x)[:30]}')
        ids.append(int(str(x).strip()))
    return sorted(set(ids))


def route_update():
    denied = _require_admin()
    if denied:
        return denied
    if request.method != 'POST':
        return {'error': 'POST only'}, 405
    body = request.get_json(silent=True) or {}
    with _settings_lock:
        s = load_settings()
        changed = []
        try:
            if 'allowed_ids' in body:
                s['allowed_ids'] = _parse_ids(body['allowed_ids'])
                changed.append('allowed_ids')
            if 'alert_poll' in body:
                poll = int(body['alert_poll'])
                if poll != 0 and not 15 <= poll <= 86400:
                    raise ValueError('alert_poll is 0 (off) or 15 to 86400 seconds')
                s['alert_poll'] = poll
                changed.append('alert_poll')
            if 'language' in body:
                if body['language'] not in LANGUAGES:
                    raise ValueError('language is one of: ' + ', '.join(LANGUAGES))
                s['language'] = body['language']
                changed.append('language')
            if 'vpn_refresh_hours' in body:
                hours = int(body['vpn_refresh_hours'])
                if not 0 <= hours <= 168:
                    raise ValueError('vpn_refresh_hours is 0 (off) to 168')
                s['vpn_refresh_hours'] = hours
                changed.append('vpn_refresh_hours')
            if 'vpn_server' in body and str(body['vpn_server'] or '') != s['vpn_server']:
                s['vpn_server'] = str(body['vpn_server'] or '')[:200]
                changed.append('vpn_server')
            if 'xray_bin' in body and str(body['xray_bin'] or '').strip() != s['xray_bin']:
                path = str(body['xray_bin'] or '').strip()
                if path and not (os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK)):
                    raise ValueError('xray path must be the absolute path of the xray program')
                s['xray_bin'] = path
                changed.append('xray_bin')
            if body.get('clear_vpn'):
                s['vpn_url'] = ''
                changed.append('vpn_url removed')
            elif body.get('vpn_url'):
                url = str(body['vpn_url']).strip()
                if not VPN_URL_RE.match(url):
                    raise ValueError('the subscription URL looks like https://...')
                try:  # check it now, so a typo shows on the page and not in the log
                    nodes = vpn.fetch(url)
                except vpn.SubscriptionError as e:
                    raise ValueError(f'subscription: {e}')
                if not vpn.pick(nodes):
                    raise ValueError('the subscription has no server this plugin can use')
                s['vpn_url'] = url
                changed.append(f'vpn_url ({len(nodes)} servers)')
            if 'proxy' in body:
                proxy = str(body['proxy'] or '').strip()
                if proxy and not PROXY_RE.match(proxy):
                    raise ValueError('proxy looks like http://host:port or socks5h://host:port')
                s['proxy'] = proxy
                changed.append('proxy')
        except (TypeError, ValueError) as e:
            return {'error': str(e)}, 400

        username = None
        if body.get('clear_token'):
            s['bot_token'] = ''
            changed.append('bot_token removed')
        elif body.get('bot_token'):
            token = str(body['bot_token']).strip()
            if not BOT_TOKEN_RE.match(token):
                return {'error': 'That does not look like a bot token from @BotFather'}, 400
            me, desc = Telegram(token, proxy=effective_proxy(s))._call('getMe', {})
            if not me:
                return {'error': f'Telegram did not accept the token: {desc or "no answer"}'}, 400
            s['bot_token'] = token
            username = me.get('username') or ''
            changed.append(f'bot_token (@{username})')
        save_settings(s)
    if any(c.startswith(('vpn_url', 'vpn_server', 'xray_bin')) for c in changed):
        # apply in the background so the page answers at once (xray and the check take seconds)
        threading.Thread(target=_vpn.refresh, name='pegaprox-telegram-vpn', daemon=True).start()
    if username is not None:
        _status['bot_username'] = username
    _audit('telegram_bot.settings', 'Changed: ' + (', '.join(changed) or 'nothing'))
    return {'success': True, 'changed': changed}


def route_vpn_refresh():
    denied = _require_admin()
    if denied:
        return denied
    if request.method != 'POST':
        return {'error': 'POST only'}, 405
    if not load_settings()['vpn_url']:
        return {'error': 'No VPN subscription is set'}, 400
    server = str((request.get_json(silent=True) or {}).get('server') or '')[:200]
    ok = _vpn.use(server) if server else _vpn.refresh()
    _audit('telegram_bot.vpn', f'VPN refreshed (server {server})' if server else 'VPN refreshed')
    return {'success': ok, 'vpn': _vpn.status()}


def route_unlink():
    denied = _require_admin()
    if denied:
        return denied
    if request.method != 'POST':
        return {'error': 'POST only'}, 405
    try:
        tg_id = int((request.get_json(silent=True) or {}).get('tg_id'))
    except (TypeError, ValueError):
        return {'error': 'tg_id required'}, 400
    if not store().unlink(tg_id):
        return {'error': 'No such linked account'}, 404
    _audit('telegram_bot.unlink', f'Unlinked Telegram user {tg_id}')
    return {'success': True}


def route_ui():
    denied = _require_admin()
    if denied:
        return Response('Admin access required', status=403, mimetype='text/plain')
    with open(os.path.join(PLUGIN_DIR, 'ui.html'), encoding='utf-8') as f:
        return Response(f.read(), mimetype='text/html')


def register(app):
    global _app
    from pegaprox.api.plugins import register_plugin_route
    _app = app
    register_plugin_route(PID, 'settings', route_settings)
    register_plugin_route(PID, 'settings/update', route_update)
    register_plugin_route(PID, 'accounts/unlink', route_unlink)
    register_plugin_route(PID, 'vpn/refresh', route_vpn_refresh)
    register_plugin_route(PID, 'ui', route_ui)


# ------------------------------------------------------------------ background task
def _alive():
    """This copy of the plugin is still the loaded one, and it is switched on here.
    PegaProx has no stop hook: disabling or reloading drops the module from sys.modules."""
    if sys.modules.get(__name__) is not _SELF:
        return False
    try:
        from pegaprox.api.plugins import plugin_runs_here
    except ImportError:  # a PegaProx without the HA check: being loaded is enough
        return True
    return plugin_runs_here(PID)


def start_background_tasks():
    global _thread
    if _thread and _thread.is_alive():  # enable on an already loaded plugin calls this again
        return
    _thread = threading.Thread(target=_run, name=THREAD_NAME, daemon=True)
    _thread.start()


def _run():
    # a previous copy (before a reload) may still be inside getUpdates: two pollers on one
    # token get 409 Conflict from Telegram, so wait for it to notice it is gone
    for t in threading.enumerate():
        if t.name == THREAD_NAME and t is not threading.current_thread():
            t.join(timeout=60)
    _status.update(running=True, started_at=time.time(), last_error='')
    log.info('Telegram bot task started')
    try:
        _loop()
    finally:
        _vpn.stop()  # the next copy of the plugin starts its own xray
        _status['running'] = False
        log.info('Telegram bot task stopped')


def _loop():
    bot = tg = None
    current = None
    offset = None
    last_poll = 0.0
    while _alive():
        s = load_settings()
        if not s['bot_token']:
            _status['last_error'] = 'No bot token set'
            time.sleep(5)
            continue
        _vpn.tick(tg)
        proxy = effective_proxy(s)
        if current != (s['bot_token'], proxy):
            current = (s['bot_token'], proxy)
            tg = Telegram(s['bot_token'], proxy=proxy)
            bot = Bot(Settings(s), tg, store(), api_factory=lambda token: PegaProx(token, InProcess(_app)))
            bot.vpn = _vpn
            offset = None
            me = tg.call('getMe')
            _status['bot_username'] = (me or {}).get('username', '')
            tg.set_commands(COMMANDS)
            # Telegram shows these to users whose app is in Russian
            tg.set_commands([(c, RU.get(d, d)) for c, d in COMMANDS], language_code='ru')
        bot.cfg = Settings(s)
        try:
            updates = tg.updates(offset, timeout=25)
            for upd in updates:
                offset = upd['update_id'] + 1
                if not _alive():
                    break
                try:
                    bot.handle_update(upd)
                except Exception:
                    log.exception('Telegram update failed')
            if bot.cfg.alert_poll and time.time() - last_poll >= bot.cfg.alert_poll:
                last_poll = time.time()
                bot.poll_alerts()
            _status['last_error'] = ''
        except Exception as e:
            _status['last_error'] = e.__class__.__name__
            log.exception('Telegram bot loop failed')
            time.sleep(5)
