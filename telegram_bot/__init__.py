# -*- coding: utf-8 -*-
"""Telegram bot for PegaProx, as a PegaProx plugin.

Each Telegram user links their own PegaProx account with an API token, and every action
goes through PegaProx's own API under that token, inside the PegaProx process. The user can
do in Telegram exactly what their role allows in the web UI, and the audit log shows it
under their name.

The plugin adds:
- a background task that long-polls Telegram while the plugin is enabled,
- admin-only settings routes (bot token, allowed Telegram ids, alert interval, proxy),
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

log = logging.getLogger('plugin.telegram_bot')

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_TOKEN_RE = re.compile(r'^\d{5,15}:[A-Za-z0-9_-]{30,64}$')
PROXY_RE = re.compile(r'^(https?|socks5h?)://[^\s/?#]+/?$')
DEFAULTS = {'bot_token': '', 'allowed_ids': [], 'alert_poll': 60, 'proxy': '', 'language': 'en'}

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
    try:
        out['bot_token'] = _decrypt(out['bot_token']) if out['bot_token'] else ''
    except Exception:
        out['bot_token'] = ''
    return out


def save_settings(settings):
    os.makedirs(data_dir(), mode=0o700, exist_ok=True)
    stored = dict(settings)
    stored['bot_token'] = _encrypt(settings['bot_token']) if settings.get('bot_token') else ''
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
            me, desc = Telegram(token, proxy=s['proxy'] or None)._call('getMe', {})
            if not me:
                return {'error': f'Telegram did not accept the token: {desc or "no answer"}'}, 400
            s['bot_token'] = token
            username = me.get('username') or ''
            changed.append(f'bot_token (@{username})')
        save_settings(s)
    if username is not None:
        _status['bot_username'] = username
    _audit('telegram_bot.settings', 'Changed: ' + (', '.join(changed) or 'nothing'))
    return {'success': True, 'changed': changed}


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
        if current != (s['bot_token'], s['proxy']):
            current = (s['bot_token'], s['proxy'])
            tg = Telegram(s['bot_token'], proxy=s['proxy'] or None)
            bot = Bot(Settings(s), tg, store(), api_factory=lambda token: PegaProx(token, InProcess(_app)))
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
