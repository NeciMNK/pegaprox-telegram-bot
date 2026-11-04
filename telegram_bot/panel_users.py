# -*- coding: utf-8 -*-
"""PegaProx's own users (the accounts of the panel and the bot) from Telegram.

The screens call /api/users and /api/roles under the linked user's token, so PegaProx
applies its own checks: the admin.users permission, tenant limits, no role above your own,
no deleting yourself or the last admin. The bot only shows what PegaProx answers.
Passwords typed in chat are taken in private chats only and deleted right away.
"""
import re

from . import views as v
from .i18n import _
from .pegaprox_client import ApiError

NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._@-]{2,63}$')
PPAGE = 10
HINT = ('Managing PegaProx users needs the admin.users permission (usually the admin role), '
        'and the token linked to the bot needs that role too.')


class PanelUsersMixin:
    """Mixed into tgbot.bot.Bot: uses its btn, screen, error, _do, pending and api."""

    def _pp_fail(self, uid, chat, mid, err, back=('pp_users', {})):
        kb = [[self.btn(uid, _('« Back'), back[0], **back[1])]]
        if err.status == 403:
            return self.screen(chat, mid, f'⛔ {_(HINT)}\n\n{v.e(err.message)}', kb)
        return self.error(chat, err, mid, kb)

    # ------------------------------------------------------------------ hub
    def cmd_users(self, msg, uid, chat, arg):
        if msg['chat'].get('type') != 'private':
            return self.tg.send(chat, _('User management works only in a private chat with the bot.'))
        return self.cb_users(uid, chat, None)

    def cb_users(self, uid, chat, mid):
        return self.cb_pp_users(uid, chat, mid)

    # ------------------------------------------------------------------ list, card
    def _pp_find(self, uid, username):
        for u in self.api(uid).panel_users():
            if u.get('username') == username:
                return u
        return None

    def cb_pp_users(self, uid, chat, mid, page=0):
        try:
            users = sorted(self.api(uid).panel_users(), key=lambda u: u.get('username') or '')
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=('clusters', {}))
        pages = max(1, (len(users) + PPAGE - 1) // PPAGE)
        page = min(max(0, page), pages - 1)
        kb = [[self.btn(uid, f"{'🟢' if u.get('enabled', True) else '⚪'} {u['username']} ({u.get('role')})"[:60],
                        'pp_user', username=u['username'])] for u in users[page * PPAGE:(page + 1) * PPAGE]]
        nav = []
        if page > 0:
            nav.append(self.btn(uid, '‹', 'pp_users', page=page - 1))
        if page < pages - 1:
            nav.append(self.btn(uid, '›', 'pp_users', page=page + 1))
        if nav:
            kb.append(nav)
        kb.append([self.btn(uid, _('➕ Create'), 'pp_new'), self.btn(uid, _('« Clusters'), 'clusters')])
        return self.screen(chat, mid, _('<b>PegaProx users</b> ({count}), page {page}/{pages}\n'
                                        '🟢 enabled, ⚪ disabled', count=len(users), page=page + 1, pages=pages), kb)

    def cb_pp_user(self, uid, chat, mid, username):
        try:
            u = self._pp_find(uid, username)
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err)
        if not u:
            return self.screen(chat, mid, _('User {name} not found.', name=v.e(username)),
                               [[self.btn(uid, _('« Users'), 'pp_users')]])
        on = u.get('enabled', True)
        local = (u.get('auth_source') or 'local') == 'local'
        lines = [f"🧑‍💻 <b>{v.e(username)}</b>" + (f" ({v.e(u['display_name'])})"
                                                   if u.get('display_name') and u['display_name'] != username else ''),
                 _('Role: <b>{role}</b>, tenant: {tenant}', role=v.e(u.get('role')), tenant=v.e(u.get('tenant_id'))),
                 _('State: {state}', state=_('🟢 enabled') if on else _('⚪ disabled')),
                 _('Login: {source}, 2FA: {tfa}', source=v.e(u.get('auth_source') or 'local'),
                   tfa=_('yes') if u.get('totp_enabled') else _('no')),
                 _('Last login: {time}', time=v.when(u.get('last_login')) if u.get('last_login') else _('never'))]
        if u.get('email'):
            lines.append(f"E-mail: {v.e(u['email'])}")
        if u.get('permissions'):
            lines.append(_('Extra permissions: <code>{perms}</code>', perms=v.e(', '.join(u['permissions']))[:1500]))
        kb = [[self.btn(uid, _('⚪ Disable') if on else _('🟢 Enable'), 'pp_enable', username=username, on=not on),
               self.btn(uid, _('🎭 Role'), 'pp_role', username=username)]]
        row = []
        if local:
            row.append(self.btn(uid, _('🔐 Password'), 'pp_pw', username=username))
        if u.get('totp_enabled'):
            row.append(self.btn(uid, _('🔓 Reset 2FA'), 'pp_2fa', username=username))
        if row:
            kb.append(row)
        kb.append([self.btn(uid, _('🗑 Delete'), 'pp_del', username=username)])
        kb.append([self.btn(uid, _('🔄 Refresh'), 'pp_user', username=username), self.btn(uid, _('« Users'), 'pp_users')])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    # ------------------------------------------------------------------ changes
    def cb_pp_enable(self, uid, chat, mid, username, on, ok=False):
        if not on and not ok:
            kb = [[self.btn(uid, _('✅ Yes, disable'), 'pp_enable', username=username, on=on, ok=True),
                   self.btn(uid, _('Cancel'), 'pp_user', username=username)]]
            return self.screen(chat, mid, _('Disable <b>{name}</b>? They will not be able to log in to PegaProx '
                                            'or use the bot.', name=v.e(username)), kb)
        try:
            self.api(uid).update_panel_user(username, {'enabled': bool(on)})
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=('pp_user', {'username': username}))
        return self.cb_pp_user(uid, chat, mid, username)

    def _roles_kb(self, uid, action, back, **ctx):
        roles = self.api(uid).panel_roles()
        kb, row = [], []
        for r in roles:
            row.append(self.btn(uid, f"{r.get('name') or r['id']}"[:40], action, role=r['id'], **ctx))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([self.btn(uid, _('Cancel'), back[0], **back[1])])
        return kb

    def cb_pp_role(self, uid, chat, mid, username):
        back = ('pp_user', {'username': username})
        try:
            kb = self._roles_kb(uid, 'pp_role_set', back, username=username)
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=back)
        return self.screen(chat, mid, _('New role for <b>{name}</b>:\n'
                                        'admin: everything, user: manage guests, viewer: read only.', name=v.e(username)), kb)

    def cb_pp_role_set(self, uid, chat, mid, username, role):
        try:
            self.api(uid).update_panel_user(username, {'role': role})
        except ApiError as err:
            return self._pp_fail(uid, chat, mid, err, back=('pp_user', {'username': username}))
        return self.cb_pp_user(uid, chat, mid, username)

    def cb_pp_pw(self, uid, chat, mid, username):
        self.pending[uid] = {'kind': 'pp_password', 'username': username}
        return self.screen(chat, mid, _('Send the new password for <b>{name}</b>.\n'
                                        'Private chat only: I delete the message with the password right away. '
                                        'All of the user\'s sessions will be closed.', name=v.e(username)),
                           [[self.btn(uid, _('Cancel'), 'pp_user', username=username)]])

    def cb_pp_2fa(self, uid, chat, mid, username, ok=False):
        if not ok:
            kb = [[self.btn(uid, _('✅ Yes, reset'), 'pp_2fa', username=username, ok=True),
                   self.btn(uid, _('Cancel'), 'pp_user', username=username)]]
            return self.screen(chat, mid, _('Reset two-factor authentication for <b>{name}</b>? '
                                            'They will log in with the password only until they set it up again.',
                                            name=v.e(username)), kb)
        return self._do(uid, chat, mid, lambda a: a.reset_panel_2fa(username),
                        _('2FA of {name} reset', name=v.e(username)), back=('pp_user', {'username': username}))

    def cb_pp_del(self, uid, chat, mid, username, ok=False):
        if not ok:
            kb = [[self.btn(uid, _('✅ Yes, delete'), 'pp_del', username=username, ok=True),
                   self.btn(uid, _('Cancel'), 'pp_user', username=username)]]
            return self.screen(chat, mid, _('Delete PegaProx user <b>{name}</b>? '
                                            'Their API tokens stop working too. This cannot be undone.',
                                            name=v.e(username)), kb)
        return self._do(uid, chat, mid, lambda a: a.delete_panel_user(username),
                        _('User {name} deleted', name=v.e(username)), back=('pp_users', {}))

    # ------------------------------------------------------------------ new user
    def cb_pp_new(self, uid, chat, mid):
        self.pending[uid] = {'kind': 'pp_username'}
        return self.screen(chat, mid, _('<b>New PegaProx user</b>\nSend the username '
                                        '(Latin letters, digits, dot, -, _; at least 3 characters):'),
                           [[self.btn(uid, _('Cancel'), 'pp_users')]])

    def cb_pp_new_role(self, uid, chat, mid, username, role):
        self.pending[uid] = {'kind': 'pp_newpass', 'username': username, 'role': role}
        return self.screen(chat, mid, _('Password for <b>{name}</b> (role {role}).\n'
                                        'By default PegaProx requires 8+ characters with an upper case letter, '
                                        'a lower case letter and a digit. '
                                        'I delete the message with the password right away.',
                                        name=v.e(username), role=v.e(role)),
                           [[self.btn(uid, _('Cancel'), 'pp_users')]])

    # ------------------------------------------------------------------ typed input
    def pp_input(self, msg, uid, chat, text, pend):
        kind = pend['kind']
        if kind == 'pp_username':
            name = text.strip().lower()
            if not NAME_RE.match(name):
                self.pending[uid] = pend
                return self.tg.send(chat, _('Username: Latin letters, digits, dot, - and _, 3 to 64 characters. Try again:'))
            try:
                kb = self._roles_kb(uid, 'pp_new_role', ('pp_users', {}), username=name)
            except ApiError as err:
                return self._pp_fail(uid, chat, None, err)
            return self.tg.send(chat, _('Which role should <b>{name}</b> have?', name=v.e(name)), kb)
        # a password: never leave it in the chat, and take it exactly as typed
        self.tg.delete(chat, msg['message_id'])
        text = msg['text']
        if msg['chat'].get('type') != 'private':
            return self.tg.send(chat, _('Send passwords only in a private chat with the bot. '
                                        'If you sent it here, change it.'))
        username = pend['username']
        if kind == 'pp_newpass':
            try:
                self.api(uid).create_panel_user(username, text, pend['role'])
            except ApiError as err:
                if err.status == 400 and 'password' in err.message.lower():
                    self.pending[uid] = pend
                    return self.tg.send(chat, '❌ ' + v.e(err.message) + '\n' + _('Send another password:'))
                return self._pp_fail(uid, chat, None, err)
            self.tg.send(chat, _('✅ PegaProx user <b>{name}</b> created.', name=v.e(username)))
            return self.cb_pp_user(uid, chat, None, username)
        if kind == 'pp_password':
            back = ('pp_user', {'username': username})
            try:
                self.api(uid).set_panel_password(username, text)
            except ApiError as err:
                if err.status == 400:
                    self.pending[uid] = pend
                    return self.tg.send(chat, '❌ ' + v.e(err.message) + '\n' + _('Send another password:'))
                return self._pp_fail(uid, chat, None, err, back=back)
            return self.tg.send(chat, _('✅ Password of {name} changed.', name=v.e(username)),
                                [[self.btn(uid, _('« Back'), back[0], **back[1])]])
