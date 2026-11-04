# -*- coding: utf-8 -*-
"""Telegram bot for PegaProx.

Each Telegram user links their own PegaProx account by sending an API token
(PegaProx: My profile -> API tokens). Every action then goes through the PegaProx
REST API under that token, so the user can do in Telegram exactly what their
PegaProx role allows, and nothing more. Actions are written to the PegaProx audit
log under the user's name, as in the web interface.
"""
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from collections import OrderedDict

from . import views as v
from .i18n import LANGUAGES, _, use
from .pegaprox_client import ApiError
from .panel_users import PanelUsersMixin

log = logging.getLogger('plugin.telegram_bot')

PAGE = 8
GUEST_ACTIONS = {
    'start': ('▶️ Start', False, 'Start'),
    'shutdown': ('⏻ Shutdown', True, 'Shutdown'),
    'reboot': ('🔄 Reboot', True, 'Reboot'),
    'stop': ('⏹ Stop (hard)', True, 'Hard stop'),
    'reset': ('⚡ Reset', True, 'Reset'),
    'suspend': ('⏸ Suspend', False, 'Suspend'),
    'resume': ('⏯ Resume', False, 'Resume'),
}
TOKEN_RE = re.compile(r'^pgx_[0-9a-f]{4}_[A-Za-z0-9_\-]{20,}$')
TOKEN_ANYWHERE_RE = re.compile(r'pgx_[0-9a-f]{4}_[A-Za-z0-9_\-]{20,}')
RULES_MOVED = '⚠️ The rules changed since that list was drawn, nothing was toggled. Here is the current list.\n\n'
PASSWORD_KINDS = ('pp_newpass', 'pp_password')
PRIVATE_ONLY = 'User management works only in a private chat with the bot.'
SNAP_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_\-]{1,39}$')

HELP = (
    "<b>Proxmox management through PegaProx</b>\n\n"
    "The bot acts as your PegaProx user, with the same permissions.\n\n"
    "<b>How to connect</b>\n"
    "1. In PegaProx open \"My Profile → API Tokens\" and create a token.\n"
    "2. Send it here in a private chat: <code>/login pgx_...</code>\n"
    "   The bot deletes the message with the token right away.\n\n"
    "<b>Commands</b>\n"
    "/menu: main menu (clusters, nodes, VMs and containers)\n"
    "/find <i>text</i>: find a VM/CT by name or ID\n"
    "/users: PegaProx users and their roles\n"
    "/alerts: active alerts\n"
    "/notify on|off: push new alerts\n"
    "/lang en|ru: language of the bot\n"
    "/whoami: your role and permissions\n"
    "/api <i>METHOD /api/path [JSON]</i>: any PegaProx API call\n"
    "/logout: unlink the account\n"
)

COMMANDS = [
    ('menu', 'Main menu'), ('find', 'Find a VM/CT'), ('users', 'PegaProx users'), ('alerts', 'Active alerts'),
    ('notify', 'Notifications on/off'), ('lang', 'Language'), ('whoami', 'My permissions'), ('login', 'Link an account'),
    ('logout', 'Unlink the account'), ('api', 'API request'), ('help', 'Help'),
]


def _rule_fp(r):
    """What a firewall rule is, apart from whether it is on: a button toggles only that rule."""
    keep = {k: r.get(k) for k in sorted(r) if k not in ('enable', 'pos', 'digest')}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _same_rule(rules, pos, fp):
    for r in rules or []:
        if str(r.get('pos')) == str(pos):
            return _rule_fp(r) == fp
    return False


class Callbacks:
    """Inline buttons carry at most 64 bytes, so they point at a stored context."""

    def __init__(self, limit=20000):
        self._items = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def put(self, owner, action, **ctx):
        key = secrets.token_urlsafe(6)
        with self._lock:
            self._items[key] = (owner, action, ctx)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
        return key

    def get(self, key):
        with self._lock:
            return self._items.get(key)


class Bot(PanelUsersMixin):
    def __init__(self, cfg, tg, store, api_factory=None):
        self.cfg = cfg
        self.tg = tg
        self.store = store
        self.cb = Callbacks()
        self.pending = {}  # tg user id -> {'kind': ..., ctx}
        self._api_factory = api_factory  # token -> PegaProx client

    # ------------------------------------------------------------------ plumbing
    def api(self, uid):
        token = self.store.token(uid)
        if not token:
            raise ApiError(401, 'no linked account')
        return self._api_factory(token)

    def btn(self, uid, label, action, **ctx):
        return {'text': label, 'callback_data': self.cb.put(uid, action, **ctx)}

    def allowed(self, uid):
        return not self.cfg.allowed_ids or uid in self.cfg.allowed_ids

    def lang(self, uid):
        rec = self.store.get(uid) or {}
        return rec.get('lang') or getattr(self.cfg, 'language', 'en')

    def handle_update(self, upd):
        sender = (upd.get('callback_query') or upd.get('message') or {}).get('from') or {}
        use(self.lang(sender.get('id')))
        if 'callback_query' in upd:
            return self.on_callback(upd['callback_query'])
        msg = upd.get('message')
        if msg and msg.get('text'):
            return self.on_message(msg)

    # ------------------------------------------------------------------ messages
    def on_message(self, msg):
        uid = msg['from']['id']
        chat = msg['chat']['id']
        text = msg['text'].strip()
        private = msg['chat'].get('type') == 'private'
        has_token = bool(TOKEN_ANYWHERE_RE.search(text))
        login_form = TOKEN_RE.match(text) or re.match(r'^/login(@\w+)?\s', text)
        if has_token and (not private or not self.allowed(uid) or not login_form):
            # a token must not stay in a group or reach a bot that won't use it
            gone = self.tg.delete(chat, msg['message_id'])
            warn = (_('I deleted the message with the token') if gone
                    else _('I could not delete the message with the token'))
            if not self.allowed(uid):
                return self.tg.send(chat, _('Access to this bot is closed. Your Telegram id: <code>{uid}</code>',
                                            uid=uid) + '\n' + _('{warn}; revoke that token in PegaProx.', warn=warn))
            return self.tg.send(chat, _('{warn}. Send tokens only in a private chat with the bot, '
                                        'and revoke this one in PegaProx.', warn=warn))
        if not self.allowed(uid):
            return self.tg.send(chat, _('Access to this bot is closed. Your Telegram id: <code>{uid}</code>', uid=uid))
        try:
            return self._on_text(msg, uid, chat, text)
        except ApiError as err:
            return self.error(chat, err)

    def _on_text(self, msg, uid, chat, text):
        pend = self.pending.get(uid) or {}
        if pend.get('kind') in PASSWORD_KINDS and not self._is_command(text):
            # a password may start with '/': only a bare known command interrupts the prompt
            return self.on_input(msg, uid, chat, text, self.pending.pop(uid))
        if text.startswith('/'):
            cmd, _sep, arg = text.partition(' ')
            cmd = cmd[1:].split('@', 1)[0].lower()
            arg = arg.strip()
            self.pending.pop(uid, None)
            handler = getattr(self, f'cmd_{cmd}', None)
            if handler is None:
                return self.tg.send(chat, _('Unknown command. /help'))
            if cmd not in ('start', 'help', 'login', 'lang') and not self.store.get(uid):
                return self.tg.send(chat, _('Link your PegaProx account first: /login <i>token</i>. More: /help'))
            return handler(msg, uid, chat, arg)
        pend = self.pending.pop(uid, None)
        if pend:
            return self.on_input(msg, uid, chat, text, pend)
        if TOKEN_RE.match(text):  # a token pasted without /login
            return self.cmd_login(msg, uid, chat, text)
        return self.tg.send(chat, _('Open /menu or see /help'))

    def _is_command(self, text):
        m = re.match(r'^/([a-z]+)(@\w+)?$', text)
        return bool(m) and hasattr(self, 'cmd_' + m.group(1))

    def cmd_start(self, msg, uid, chat, arg):
        if self.store.get(uid):
            return self.cmd_menu(msg, uid, chat, arg)
        return self.tg.send(chat, _(HELP))

    def cmd_help(self, msg, uid, chat, arg):
        return self.tg.send(chat, _(HELP))

    def cmd_lang(self, msg, uid, chat, arg):
        code = arg.strip().lower()
        if code not in LANGUAGES:
            kb = [[self.btn(uid, name, 'lang', code=c) for c, name in LANGUAGES.items()]]
            return self.tg.send(chat, _('Choose the language:'), kb)
        return self._set_lang(uid, chat, None, code)

    def cb_lang(self, uid, chat, mid, code):
        return self._set_lang(uid, chat, mid, code)

    def _set_lang(self, uid, chat, mid, code):
        if self.store.get(uid):
            self.store.set_lang(uid, code)
            note = ''
        else:
            note = '\n' + _('Link your PegaProx account first: /login <i>token</i>. More: /help')
        use(code)
        return self.screen(chat, mid, _('Language: English') + note, None)

    def cmd_login(self, msg, uid, chat, arg):
        if arg:
            self.tg.delete(chat, msg['message_id'])
        if msg['chat'].get('type') != 'private':
            return self.tg.send(chat, _('Send the token only in a private chat with the bot. '
                                        'If you sent it here, revoke the token in PegaProx.'))
        token = arg.strip()
        if not TOKEN_RE.match(token):
            return self.tg.send(chat, _('Send a PegaProx API token: <code>/login pgx_...</code>\n'
                                        'You can create one under "My Profile → API Tokens".'))
        try:
            me = self._api_factory(token).me()
        except ApiError as err:
            if err.status in (401, 403):
                return self.tg.send(chat, _('❌ PegaProx did not accept the token: it is wrong, revoked or expired.'))
            return self.tg.send(chat, _('❌ Could not check the token: {error}', error=v.e(err.message)))
        self.store.link(uid, token, {'role': me.get('effective_role') or me.get('role'),
                                     'tg_name': msg['from'].get('username') or msg['from'].get('first_name')})
        log.info('Telegram user %s linked (role %s)', uid, me.get('role'))
        self.tg.send(chat, _('✅ Account linked. PegaProx role: <b>{role}</b>.\n'
                             'New alerts will be sent here (/notify off to stop).',
                             role=v.e(me.get('effective_role') or me.get('role'))))
        return self.cmd_menu(msg, uid, chat, '')

    def cmd_logout(self, msg, uid, chat, arg):
        self.store.unlink(uid)
        return self.tg.send(chat, _('Account unlinked. The token itself still works: '
                                    'revoke it in PegaProx ("My Profile → API Tokens").'))

    def cmd_whoami(self, msg, uid, chat, arg):
        try:
            me = self.api(uid).me()
        except ApiError as err:
            return self.error(chat, err)
        perms = me.get('permissions') or []
        return self.tg.send(chat, _('Role: <b>{role}</b>\nTenant: {tenant}\nPermissions ({count}): <code>{perms}</code>',
                                    role=v.e(me.get('effective_role') or me.get('role')),
                                    tenant=v.e(me.get('tenant_id')), count=len(perms),
                                    perms=v.e(', '.join(sorted(perms))[:3500])))

    def cmd_notify(self, msg, uid, chat, arg):
        on = arg.lower() not in ('off', '0', 'no')
        self.store.set_notify(uid, on)
        return self.tg.send(chat, _('Alert notifications are on.') if on else _('Notifications are off.'))

    def cmd_menu(self, msg, uid, chat, arg):
        return self.show_clusters(uid, chat)

    def cmd_alerts(self, msg, uid, chat, arg):
        return self.show_all_alerts(uid, chat)

    def cmd_find(self, msg, uid, chat, arg):
        if not arg:
            self.pending[uid] = {'kind': 'find'}
            return self.tg.send(chat, _('Type a VM/CT name or ID:'))
        return self.find(uid, chat, arg)

    def cmd_api(self, msg, uid, chat, arg):
        if msg['chat'].get('type') != 'private':
            # a raw call can carry a password or show account data: never in a group
            gone = self.tg.delete(chat, msg['message_id'])
            done = _('I deleted the message') if gone else _('I could not delete the message (the bot needs admin rights here)')
            return self.tg.send(chat, _('/api works only in a private chat with the bot. {done}; '
                                        'if it held a password, change it.', done=done))
        parts = arg.split(None, 2)
        if len(parts) < 2 or parts[0].upper() not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE') \
                or not parts[1].startswith('/api/'):
            return self.tg.send(chat, _('Usage: <code>/api GET /api/clusters</code>\n'
                                        'or <code>/api POST /api/path {"key": "value"}</code>'))
        body = None
        if len(parts) == 3:
            try:
                body = json.loads(parts[2])
            except ValueError:
                return self.tg.send(chat, _('The request body must be JSON.'))
        try:
            res = self.api(uid).request(parts[0], parts[1], json=body)
        except ApiError as err:
            return self.error(chat, err)
        out = v.e(json.dumps(res, ensure_ascii=False, indent=1))
        if len(out) > 3800:
            cut = out[:3800]
            amp = cut.rfind('&')
            if amp > cut.rfind(';'):  # don't leave half an HTML entity
                cut = cut[:amp]
            out = cut + '\n…'
        return self.tg.send(chat, f'<pre>{out}</pre>')

    def on_input(self, msg, uid, chat, text, pend):
        kind = pend['kind']
        if kind.startswith('pp_'):
            return self.pp_input(msg, uid, chat, text, pend)
        if kind == 'find':
            return self.find(uid, chat, text)
        if kind == 'snapname':
            if not SNAP_RE.match(text):
                self.pending[uid] = pend
                return self.tg.send(chat, _('Snapshot name: Latin letters, digits, _ and -, starting with a letter. Try again:'))
            g = pend['g']
            return self._do(uid, chat, None, lambda a: a.create_snapshot(g['cid'], g['node'], g['type'], g['vmid'], text,
                                                                          'Telegram'),
                            _('Creating snapshot <b>{name}</b>', name=v.e(text)), back=('snaps', {'g': g}))

    # ------------------------------------------------------------------ callbacks
    def on_callback(self, q):
        uid = q['from']['id']
        msg = q.get('message') or {}
        chat = (msg.get('chat') or {}).get('id', uid)
        mid = msg.get('message_id')
        item = self.cb.get(q.get('data') or '')
        if not item or item[0] != uid:
            self.tg.answer(q['id'], _('This button has expired, open /menu'), alert=True)
            return
        if not self.allowed(uid) or not self.store.get(uid):
            self.tg.answer(q['id'], _('No account linked: /login'), alert=True)
            return
        _owner, action, ctx = item
        if (action == 'users' or action.startswith('pp_')) and (msg.get('chat') or {}).get('type') != 'private':
            self.tg.answer(q['id'], _(PRIVATE_ONLY), alert=True)
            return
        self.tg.answer(q['id'])
        handler = getattr(self, f'cb_{action}')
        try:
            return handler(uid, chat, mid, **ctx)
        except ApiError as err:
            return self.error(chat, err, mid)

    def screen(self, chat, mid, text, kb):
        if mid:
            return self.tg.edit(chat, mid, text, kb)
        return self.tg.send(chat, text, kb)

    def error(self, chat, err, mid=None, kb=None):
        if err.status == 401:
            text = _('❌ PegaProx rejected the token (revoked or expired). Link again: /login')
        elif err.status == 403:
            text = _('⛔ Permission denied: {error}', error=v.e(err.message))
        else:
            text = _('❌ Error: {error}', error=v.e(err.message))
        return self.screen(chat, mid, text, kb) if mid else self.tg.send(chat, text, kb)

    def _do(self, uid, chat, mid, call, done_text, back=None):
        kb = None
        if back:
            kb = [[self.btn(uid, _('« Back'), back[0], **back[1])]]
        try:
            res = call(self.api(uid))
        except ApiError as err:
            return self.error(chat, err, mid, kb)
        detail = ''
        if isinstance(res, dict):
            task = res.get('task') or res.get('upid') or res.get('data')
            if isinstance(task, str) and task.startswith('UPID'):
                detail = '\n' + _('Task: <code>{task}</code>', task=v.e(task))
            elif res.get('message'):
                detail = f"\n{v.e(res['message'])}"
        return self.screen(chat, mid, f'✅ {done_text}{detail}', kb)

    # clusters ------------------------------------------------------------------
    def show_clusters(self, uid, chat, mid=None):
        try:
            clusters = self.api(uid).clusters()
        except ApiError as err:
            return self.error(chat, err, mid)
        if not clusters:
            return self.screen(chat, mid, _('No clusters available.'), None)
        kb = [[self.btn(uid, v.cluster_line(c), 'cluster', cid=c['id'], cname=v.cluster_name(c))] for c in clusters]
        kb.append([self.btn(uid, _('🔔 Alerts'), 'all_alerts'), self.btn(uid, _('🔍 Search'), 'ask_find')])
        kb.append([self.btn(uid, _('👥 Users'), 'users'), self.btn(uid, '🌐 ' + _('Language'), 'lang_menu')])
        return self.screen(chat, mid, _('<b>Clusters</b>'), kb)

    def cb_lang_menu(self, uid, chat, mid):
        kb = [[self.btn(uid, name, 'lang', code=c) for c, name in LANGUAGES.items()],
              [self.btn(uid, _('« Clusters'), 'clusters')]]
        return self.screen(chat, mid, _('Choose the language:'), kb)

    def cb_clusters(self, uid, chat, mid):
        return self.show_clusters(uid, chat, mid)

    def cb_cluster(self, uid, chat, mid, cid, cname):
        api = self.api(uid)
        lines = [f'<b>{v.e(cname)}</b>']
        try:
            nodes = api.nodes(cid)
            online = sum(1 for n in nodes if n.get('status') == 'online')
            lines.append(_('Nodes: {online} of {total} online', online=online, total=len(nodes)))
        except ApiError as err:
            lines.append(_('Nodes: {error}', error=v.e(err.message)))
        try:
            vms = api.vms(cid)
            running = sum(1 for x in vms if x.get('status') == 'running')
            lines.append(_('Guests: {running} of {total} running', running=running, total=len(vms)))
        except ApiError:
            pass
        c = dict(cid=cid, cname=cname)
        kb = [
            [self.btn(uid, _('🖥 Nodes'), 'nodes', **c), self.btn(uid, _('📦 VMs and CTs'), 'guests', page=0, **c)],
            [self.btn(uid, _('📋 Tasks'), 'tasks', **c), self.btn(uid, _('🔔 Alerts'), 'alerts', **c)],
            [self.btn(uid, _('🛡 Firewall'), 'fw', **c), self.btn(uid, _('💽 Storage'), 'storage', **c)],
            [self.btn(uid, _('🔄 Refresh'), 'cluster', **c), self.btn(uid, _('« Clusters'), 'clusters')],
        ]
        return self.screen(chat, mid, '\n'.join(lines), kb)

    # nodes ---------------------------------------------------------------------
    def cb_nodes(self, uid, chat, mid, cid, cname):
        try:
            nodes = self.api(uid).nodes(cid)
        except ApiError as err:
            return self.error(chat, err, mid)
        c = dict(cid=cid, cname=cname)
        lines = [_('<b>{cluster}: nodes</b>', cluster=v.e(cname))] + [v.node_line(n) for n in nodes]
        kb = [[self.btn(uid, n.get('node') or n.get('name'), 'node', node=n.get('node') or n.get('name'), **c)]
              for n in nodes]
        kb.append([self.btn(uid, _('« Back'), 'cluster', **c)])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    def cb_node(self, uid, chat, mid, cid, cname, node):
        try:
            nodes = self.api(uid).nodes(cid)
        except ApiError as err:
            return self.error(chat, err, mid)
        n = next((x for x in nodes if (x.get('node') or x.get('name')) == node), {'node': node, 'status': '?'})
        c = dict(cid=cid, cname=cname, node=node)
        kb = [[self.btn(uid, _('🔄 Reboot'), 'confirm_node', act='reboot', **c),
               self.btn(uid, _('⏻ Shutdown'), 'confirm_node', act='shutdown', **c)],
              [self.btn(uid, _('🔄 Refresh'), 'node', **c), self.btn(uid, _('« Nodes'), 'nodes', cid=cid, cname=cname)]]
        return self.screen(chat, mid, v.node_text(n) + '\n\n' + _('PegaProx allows reboot and shutdown '
                                                                  'only for a node in maintenance mode.'), kb)

    def cb_confirm_node(self, uid, chat, mid, cid, cname, node, act):
        c = dict(cid=cid, cname=cname, node=node)
        reboot = act == 'reboot'
        kb = [[self.btn(uid, _('✅ Yes, reboot') if reboot else _('✅ Yes, shut down'), 'node_do', act=act, **c),
               self.btn(uid, _('Cancel'), 'node', **c)]]
        text = _('Reboot node <b>{node}</b>?', node=v.e(node)) if reboot else _('Shut down node <b>{node}</b>?', node=v.e(node))
        return self.screen(chat, mid, text, kb)

    def cb_node_do(self, uid, chat, mid, cid, cname, node, act):
        return self._do(uid, chat, mid, lambda a: a.node_action(cid, node, act),
                        _('Node {node}: reboot started', node=v.e(node)) if act == 'reboot'
                        else _('Node {node}: shutdown started', node=v.e(node)),
                        back=('node', dict(cid=cid, cname=cname, node=node)))

    # guests --------------------------------------------------------------------
    def cb_guests(self, uid, chat, mid, cid, cname, page=0):
        try:
            vms = self.api(uid).vms(cid)
        except ApiError as err:
            return self.error(chat, err, mid)
        c = dict(cid=cid, cname=cname)
        pages = max(1, (len(vms) + PAGE - 1) // PAGE)
        page = min(max(0, page), pages - 1)
        chunk = vms[page * PAGE:(page + 1) * PAGE]
        kb = [[self.btn(uid, v.guest_button(x), 'guest', g=self._g(cid, cname, x))] for x in chunk]
        nav = []
        if page > 0:
            nav.append(self.btn(uid, '‹', 'guests', page=page - 1, **c))
        if page < pages - 1:
            nav.append(self.btn(uid, '›', 'guests', page=page + 1, **c))
        if nav:
            kb.append(nav)
        kb.append([self.btn(uid, _('🔍 Search'), 'ask_find'), self.btn(uid, _('« Back'), 'cluster', **c)])
        return self.screen(chat, mid, _('<b>{cluster}: VMs and containers</b> ({count}), page {page}/{pages}',
                                        cluster=v.e(cname), count=len(vms), page=page + 1, pages=pages), kb)

    @staticmethod
    def _g(cid, cname, x):
        return {'cid': cid, 'cname': cname, 'node': x.get('node'), 'type': x.get('type'),
                'vmid': int(x.get('vmid')), 'name': x.get('name') or ''}

    def _fresh(self, uid, g):
        """Re-read the guest: it may have moved or changed state since the button was drawn."""
        for x in self.api(uid).vms(g['cid']):
            if int(x.get('vmid')) == int(g['vmid']):
                return x
        return None

    def cb_guest(self, uid, chat, mid, g):
        try:
            x = self._fresh(uid, g)
        except ApiError as err:
            return self.error(chat, err, mid)
        if not x:
            return self.screen(chat, mid, _('Guest {vmid} not found.', vmid=g['vmid']),
                               [[self.btn(uid, _('« Back'), 'guests', cid=g['cid'], cname=g['cname'], page=0)]])
        g = self._g(g['cid'], g['cname'], x)
        st = x.get('status')
        acts = ['start'] if st == 'stopped' else (['resume', 'stop'] if st in ('paused', 'suspended')
                                                  else ['shutdown', 'reboot', 'stop', 'suspend'])
        if g['type'] == 'qemu' and st == 'running':
            acts.append('reset')
        if g['type'] == 'lxc':
            acts = [a for a in acts if a not in ('reset',)]
        row, kb = [], []
        for a in acts:
            row.append(self.btn(uid, _(GUEST_ACTIONS[a][0]), 'guest_act', g=g, act=a))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb += [[self.btn(uid, _('📸 Snapshots'), 'snaps', g=g), self.btn(uid, _('💾 Backups'), 'backups', g=g)],
               [self.btn(uid, _('🚚 Migrate'), 'migrate', g=g), self.btn(uid, _('🛡 Firewall'), 'vmfw', g=g)],
               [self.btn(uid, _('🔄 Refresh'), 'guest', g=g),
                self.btn(uid, _('« List'), 'guests', cid=g['cid'], cname=g['cname'], page=0)]]
        return self.screen(chat, mid, v.guest_text(x, g['cname']), kb)

    def cb_guest_act(self, uid, chat, mid, g, act, ok=False):
        label, needs_confirm, word = GUEST_ACTIONS[act]
        word = _(word)
        if needs_confirm and not ok:
            kb = [[self.btn(uid, _('✅ Yes: {action}', action=word.lower()), 'guest_act', g=g, act=act, ok=True),
                   self.btn(uid, _('Cancel'), 'guest', g=g)]]
            return self.screen(chat, mid, f"{word}: <b>{v.e(g['name'])}</b> ({g['vmid']})?", kb)
        return self._do(uid, chat, mid, lambda a: a.vm_action(g['cid'], g['node'], g['type'], g['vmid'], act),
                        f"{word}: {v.e(g['name'])} ({g['vmid']})", back=('guest', {'g': g}))

    # snapshots -------------------------------------------------------------------
    def cb_snaps(self, uid, chat, mid, g):
        try:
            snaps = [s for s in self.api(uid).snapshots(g['cid'], g['node'], g['type'], g['vmid'])
                     if s.get('name') != 'current']
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'guest', g=g)]])
        lines = [_('<b>Snapshots of {name} ({vmid})</b>', name=v.e(g['name']), vmid=g['vmid'])] + \
            ([v.snapshot_line(s) for s in snaps] or [_('No snapshots')])
        kb = [[self.btn(uid, f"↩️ {s['name']}", 'snap', g=g, snap=s['name'])] for s in snaps[-10:]]
        kb.append([self.btn(uid, _('➕ Create'), 'snap_new', g=g), self.btn(uid, _('« Back'), 'guest', g=g)])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    def cb_snap(self, uid, chat, mid, g, snap):
        kb = [[self.btn(uid, _('↩️ Roll back'), 'snap_do', g=g, snap=snap, op='rollback'),
               self.btn(uid, _('🗑 Delete'), 'snap_do', g=g, snap=snap, op='delete')],
              [self.btn(uid, _('« Snapshots'), 'snaps', g=g)]]
        return self.screen(chat, mid, _('Snapshot <b>{snap}</b> of {name} ({vmid})',
                                        snap=v.e(snap), name=v.e(g['name']), vmid=g['vmid']), kb)

    def cb_snap_do(self, uid, chat, mid, g, snap, op, ok=False):
        if not ok:
            kb = [[self.btn(uid, _('✅ Yes'), 'snap_do', g=g, snap=snap, op=op, ok=True),
                   self.btn(uid, _('Cancel'), 'snap', g=g, snap=snap)]]
            if op == 'rollback':
                text = _('Roll back to snapshot <b>{snap}</b>?', snap=v.e(snap)) + '\n' + \
                    _('The current state of the guest will be lost.')
            else:
                text = _('Delete snapshot <b>{snap}</b>?', snap=v.e(snap))
            return self.screen(chat, mid, text, kb)
        if op == 'rollback':
            call = lambda a: a.rollback_snapshot(g['cid'], g['node'], g['type'], g['vmid'], snap)
        else:
            call = lambda a: a.delete_snapshot(g['cid'], g['node'], g['type'], g['vmid'], snap)
        return self._do(uid, chat, mid, call,
                        _('Rollback to snapshot {snap}', snap=v.e(snap)) if op == 'rollback'
                        else _('Deleting snapshot {snap}', snap=v.e(snap)),
                        back=('snaps', {'g': g}))

    def cb_snap_new(self, uid, chat, mid, g):
        self.pending[uid] = {'kind': 'snapname', 'g': g}
        default = time.strftime('tg_%Y%m%d_%H%M')
        kb = [[self.btn(uid, _('Create "{name}"', name=default), 'snap_auto', g=g, name=default)],
              [self.btn(uid, _('Cancel'), 'snaps', g=g)]]
        return self.screen(chat, mid, _('Type a name for the new snapshot or press the button:'), kb)

    def cb_snap_auto(self, uid, chat, mid, g, name):
        self.pending.pop(uid, None)
        return self._do(uid, chat, mid, lambda a: a.create_snapshot(g['cid'], g['node'], g['type'], g['vmid'], name,
                                                                     'Telegram'),
                        _('Creating snapshot <b>{name}</b>', name=v.e(name)), back=('snaps', {'g': g}))

    # backups ---------------------------------------------------------------------
    def cb_backups(self, uid, chat, mid, g):
        try:
            items = self.api(uid).backups(g['cid'], g['node'], g['type'], g['vmid'])
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'guest', g=g)]])
        items = sorted(items, key=lambda b: b.get('ctime') or 0, reverse=True)
        lines = [_('<b>Backups of {name} ({vmid})</b>', name=v.e(g['name']), vmid=g['vmid'])] + \
            ([v.backup_line(b) for b in items[:10]] or [_('No backups')])
        kb = [[self.btn(uid, _('➕ Back up now'), 'backup_store', g=g), self.btn(uid, _('« Back'), 'guest', g=g)]]
        return self.screen(chat, mid, '\n'.join(lines), kb)

    def cb_backup_store(self, uid, chat, mid, g):
        try:
            ds = self.api(uid).datastores(g['cid'])
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'backups', g=g)]])
        names = []
        shared = ds.get('shared') or []
        if isinstance(shared, dict):
            shared = list(shared.values())
        local = (ds.get('local') or {}).get(g['node']) or []
        for s in list(shared) + list(local):
            if 'backup' in (s.get('content') or '') and s.get('storage') not in names:
                names.append(s.get('storage'))
        if not names:
            return self.screen(chat, mid, _('No backup storage available on this node.'),
                               [[self.btn(uid, _('« Back'), 'backups', g=g)]])
        kb = [[self.btn(uid, f'💽 {n}', 'backup_do', g=g, storage=n)] for n in names]
        kb.append([self.btn(uid, _('Cancel'), 'backups', g=g)])
        return self.screen(chat, mid, _('Where to store the backup (snapshot mode, zstd)?'), kb)

    def cb_backup_do(self, uid, chat, mid, g, storage):
        return self._do(uid, chat, mid, lambda a: a.create_backup(g['cid'], g['node'], g['type'], g['vmid'], storage),
                        _('Backup of {name} to {storage} started', name=v.e(g['name']), storage=v.e(storage)),
                        back=('backups', {'g': g}))

    # migration -------------------------------------------------------------------
    def cb_migrate(self, uid, chat, mid, g):
        try:
            nodes = self.api(uid).nodes(g['cid'])
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'guest', g=g)]])
        targets = [n.get('node') or n.get('name') for n in nodes
                   if n.get('status') == 'online' and (n.get('node') or n.get('name')) != g['node']]
        if not targets:
            return self.screen(chat, mid, _('No other online node to migrate to.'),
                               [[self.btn(uid, _('« Back'), 'guest', g=g)]])
        kb = [[self.btn(uid, f'➡️ {t}', 'migrate_do', g=g, target=t)] for t in targets]
        kb.append([self.btn(uid, _('Cancel'), 'guest', g=g)])
        return self.screen(chat, mid, _('Migrate <b>{name}</b> from {node} to:', name=v.e(g['name']), node=v.e(g['node'])), kb)

    def cb_migrate_do(self, uid, chat, mid, g, target, ok=False):
        if not ok:
            kb = [[self.btn(uid, _('✅ Migrate'), 'migrate_do', g=g, target=target, ok=True),
                   self.btn(uid, _('Cancel'), 'guest', g=g)]]
            return self.screen(chat, mid, _('Migrate <b>{name}</b> ({vmid}) to <b>{target}</b>?',
                                            name=v.e(g['name']), vmid=g['vmid'], target=v.e(target)), kb)
        try:
            x = self._fresh(uid, g)
        except ApiError as err:
            return self.error(chat, err, mid)
        online = bool(x and x.get('status') == 'running')
        return self._do(uid, chat, mid, lambda a: a.migrate(g['cid'], g['node'], g['type'], g['vmid'], target, online),
                        _('Migration of {name} to {target} started', name=v.e(g['name']), target=v.e(target)),
                        back=('guests', dict(cid=g['cid'], cname=g['cname'], page=0)))

    # firewall --------------------------------------------------------------------
    def cb_fw(self, uid, chat, mid, cid, cname, note=''):
        api = self.api(uid)
        c = dict(cid=cid, cname=cname)
        try:
            opts = api.dc_firewall_options(cid)
            rules = api.dc_firewall_rules(cid)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'cluster', **c)]])
        on = str(opts.get('enable', 0)) in ('1', 'True', 'true')
        lines = [_('<b>Datacenter firewall of {cluster}</b>', cluster=v.e(cname)),
                 _('State: {state}', state=_('✅ enabled') if on else _('⛔ disabled')),
                 _('Policy in: {pin}, out: {pout}', pin=v.e(opts.get('policy_in', 'DROP')),
                   pout=v.e(opts.get('policy_out', 'ACCEPT'))),
                 ''] + ([v.fw_rule_line(r) for r in rules[:30]] or [_('No rules')])
        kb = [[self.btn(uid, _('⛔ Disable firewall') if on else _('✅ Enable firewall'), 'fw_toggle', on=not on, **c)]]
        row = []
        for r in rules[:20]:
            r_on = str(r.get('enable', 0)) in ('1', 'True', 'true')
            row.append(self.btn(uid, f"{'⛔' if r_on else '✅'} #{r.get('pos')}", 'fw_rule', pos=r.get('pos'), fp=_rule_fp(r), on=not r_on, **c))
            if len(row) == 4:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([self.btn(uid, _('🔄 Refresh'), 'fw', **c), self.btn(uid, _('« Back'), 'cluster', **c)])
        return self.screen(chat, mid, note + '\n'.join(lines) + '\n\n' + _('The #N buttons turn a rule on or off.'), kb)

    def cb_fw_toggle(self, uid, chat, mid, cid, cname, on, ok=False):
        c = dict(cid=cid, cname=cname)
        if not ok:
            kb = [[self.btn(uid, _('✅ Yes'), 'fw_toggle', on=on, ok=True, **c), self.btn(uid, _('Cancel'), 'fw', **c)]]
            if on:
                text = _('Enable the datacenter firewall?') + '\n' + _(
                    'Make sure there are rules that allow the web UI and SSH, or you may lock yourself out.')
            else:
                text = _('Disable the datacenter firewall?')
            return self.screen(chat, mid, text, kb)
        return self._do(uid, chat, mid, lambda a: a.set_dc_firewall_enabled(cid, on),
                        _('Firewall enabled') if on else _('Firewall disabled'), back=('fw', c))

    def cb_fw_rule(self, uid, chat, mid, cid, cname, pos, fp, on):
        try:
            api = self.api(uid)
            if not _same_rule(api.dc_firewall_rules(cid), pos, fp):
                return self.cb_fw(uid, chat, mid, cid, cname, note=_(RULES_MOVED))
            api.set_dc_firewall_rule(cid, pos, on)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'fw', cid=cid, cname=cname)]])
        return self.cb_fw(uid, chat, mid, cid, cname)

    def cb_vmfw(self, uid, chat, mid, g, note=''):
        try:
            rules = self.api(uid).vm_firewall_rules(g['cid'], g['node'], g['type'], g['vmid'])
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'guest', g=g)]])
        lines = [_('<b>Firewall {name} ({vmid})</b>', name=v.e(g['name']), vmid=g['vmid'])] + \
            ([v.fw_rule_line(r) for r in rules[:30]] or [_('No rules')])
        kb, row = [], []
        for r in rules[:20]:
            r_on = str(r.get('enable', 0)) in ('1', 'True', 'true')
            row.append(self.btn(uid, f"{'⛔' if r_on else '✅'} #{r.get('pos')}", 'vmfw_rule', g=g, pos=r.get('pos'), fp=_rule_fp(r), on=not r_on))
            if len(row) == 4:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([self.btn(uid, _('🔄 Refresh'), 'vmfw', g=g), self.btn(uid, _('« Back'), 'guest', g=g)])
        return self.screen(chat, mid, note + '\n'.join(lines), kb)

    def cb_vmfw_rule(self, uid, chat, mid, g, pos, fp, on):
        try:
            api = self.api(uid)
            if not _same_rule(api.vm_firewall_rules(g['cid'], g['node'], g['type'], g['vmid']), pos, fp):
                return self.cb_vmfw(uid, chat, mid, g, note=_(RULES_MOVED))
            api.set_vm_firewall_rule(g['cid'], g['node'], g['type'], g['vmid'], pos, on)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'vmfw', g=g)]])
        return self.cb_vmfw(uid, chat, mid, g)

    # storage, tasks --------------------------------------------------------------
    def cb_storage(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        try:
            ds = self.api(uid).datastores(cid)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'cluster', **c)]])
        shared = ds.get('shared') or []
        if isinstance(shared, dict):
            shared = list(shared.values())
        lines = [_('<b>Storage of {cluster}</b>', cluster=v.e(cname))]
        for s in shared:
            lines.append(f"🌐 <b>{v.e(s.get('storage'))}</b> ({v.e(s.get('type'))}) " + v.used_of(s))
        for node, items in (ds.get('local') or {}).items():
            for s in items:
                lines.append(f"🖥 {v.e(node)}/<b>{v.e(s.get('storage'))}</b> ({v.e(s.get('type'))}) " + v.used_of(s))
        return self.screen(chat, mid, '\n'.join(lines),
                           [[self.btn(uid, _('🔄 Refresh'), 'storage', **c), self.btn(uid, _('« Back'), 'cluster', **c)]])

    def cb_tasks(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        try:
            tasks = self.api(uid).tasks(cid, limit=15)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'cluster', **c)]])
        lines = [_('<b>Latest tasks of {cluster}</b>', cluster=v.e(cname))] + ([v.task_line(t) for t in tasks[:15]] or [_('No tasks')])
        return self.screen(chat, mid, '\n'.join(lines),
                           [[self.btn(uid, _('🔄 Refresh'), 'tasks', **c), self.btn(uid, _('« Back'), 'cluster', **c)]])

    # alerts ------------------------------------------------------------------------
    def cb_alerts(self, uid, chat, mid, cid, cname):
        c = dict(cid=cid, cname=cname)
        try:
            alerts = self.api(uid).active_alerts(cid)
        except ApiError as err:
            return self.error(chat, err, mid, [[self.btn(uid, _('« Back'), 'cluster', **c)]])
        text = _('<b>Alerts of {cluster}</b>', cluster=v.e(cname)) + '\n\n' + \
            ('\n\n'.join(v.alert_text(a) for a in alerts[:10]) or _('No active alerts ✅'))
        kb = [[self.btn(uid, _('✔️ Acknowledge #{id}', id=a['id']), 'ack', cid=cid, cname=cname, fid=a['id'])]
              for a in alerts[:10] if not a.get('acked_at')]
        kb.append([self.btn(uid, _('🔄 Refresh'), 'alerts', **c), self.btn(uid, _('« Back'), 'cluster', **c)])
        return self.screen(chat, mid, text, kb)

    def cb_ack(self, uid, chat, mid, cid, cname, fid, back='alerts'):
        try:
            self.api(uid).ack_alert(cid, fid)
        except ApiError as err:
            return self.error(chat, err, mid)
        if back == 'none':
            return self.screen(chat, mid, _('✔️ Alert #{id} acknowledged', id=v.e(fid)), None)
        return self.cb_alerts(uid, chat, mid, cid, cname)

    def cb_all_alerts(self, uid, chat, mid):
        return self.show_all_alerts(uid, chat, mid)

    def show_all_alerts(self, uid, chat, mid=None):
        api = self.api(uid)
        try:
            clusters = api.clusters()
        except ApiError as err:
            return self.error(chat, err, mid)
        blocks = []
        for c in clusters:
            try:
                for a in api.active_alerts(c['id']):
                    blocks.append(v.alert_text(a, v.cluster_name(c)))
            except ApiError:
                continue
        text = _('<b>Active alerts</b>') + '\n\n' + ('\n\n'.join(blocks[:15]) or _('No active alerts ✅'))
        return self.screen(chat, mid, text, [[self.btn(uid, _('« Clusters'), 'clusters')]])

    # search ------------------------------------------------------------------------
    def cb_ask_find(self, uid, chat, mid):
        self.pending[uid] = {'kind': 'find'}
        return self.screen(chat, mid, _('Type a VM/CT name or ID:'), None)

    def find(self, uid, chat, query):
        try:
            api = self.api(uid)
            found = self._search(api, query.strip())
        except ApiError as err:
            return self.error(chat, err)
        if not found:
            return self.tg.send(chat, _('Nothing found for "{query}".', query=v.e(query)))
        kb = [[self.btn(uid, f'{v.guest_button(x)} @ {v.cluster_name(c)}'[:60], 'guest',
                        g=self._g(c['id'], v.cluster_name(c), x))] for c, x in found[:20]]
        return self.tg.send(chat, _('Found: {count}', count=len(found)), kb)

    @staticmethod
    def _search(api, query):
        """One call to PegaProx's global search; cluster by cluster only if it refuses the query."""
        try:
            hits = api.search(query)  # as typed: AND/OR/NOT are operators only in upper case
        except ApiError as err:
            if err.status != 400:  # e.g. a one-character query
                raise
            hits = None
        if hits is not None:
            out = []
            for h in hits:
                if h.get('type') not in ('vm', 'ct'):
                    continue
                c = {'id': h.get('cluster_id'), 'name': h.get('cluster_name'), 'display_name': h.get('cluster_name')}
                x = dict(h, type='qemu' if h['type'] == 'vm' else 'lxc')
                out.append((c, x))
            return out
        q = query.lower()
        found = []
        for c in api.clusters():
            try:
                for x in api.vms(c['id']):
                    if q == str(x.get('vmid')) or q in (x.get('name') or '').lower():
                        found.append((c, x))
            except ApiError:
                continue
        return found

    # alert notifications -------------------------------------------------------------
    def poll_alerts(self):
        for uid in self.store.linked_ids():
            rec = self.store.get(uid) or {}
            if not rec.get('notify', True) or not self.allowed(uid):
                continue
            use(self.lang(uid))
            try:
                api = self.api(uid)
                clusters = api.clusters()
            except ApiError:
                continue
            for c in clusters:
                try:
                    alerts = api.active_alerts(c['id'])
                except ApiError:
                    continue
                by_key = {f"{c['id']}:{a.get('id')}:{a.get('triggered_at')}": a for a in alerts
                          if not a.get('acked_at') and not a.get('muted_until')}
                sent = []
                for key in self.store.unseen(uid, list(by_key)):
                    a = by_key[key]
                    kb = [[self.btn(uid, _('✔️ Acknowledge'), 'ack', cid=c['id'], cname=v.cluster_name(c),
                                    fid=a['id'], back='none')]]
                    if self.tg.send(uid, '🔔 ' + v.alert_text(a, v.cluster_name(c)), kb):
                        sent.append(key)
                # only what reached the user counts as seen; the rest is tried again next poll
                self.store.mark_seen(uid, sent)
