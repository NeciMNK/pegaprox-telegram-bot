# -*- coding: utf-8 -*-
"""/vpn in the bot: the VPN the bot reaches Telegram through. PegaProx admins only.

The subscription URL itself is set only on the settings page: it is a secret, and a chat
is no place for it. Here an admin sees which server is in use, switches to another one
from the subscription, or downloads the subscription again.
"""
from . import views as v
from .i18n import _
from .pegaprox_client import ApiError

ADMIN_ONLY = 'Only a PegaProx admin can manage the bot\'s VPN.'


class VpnMixin:
    """Mixed into Bot. `self.vpn` is the plugin's VpnControl, or None outside the plugin."""

    vpn = None

    def _vpn_admin(self, uid):
        try:
            me = self.api(uid).me()
        except ApiError:
            return False
        return (me.get('effective_role') or me.get('role')) == 'admin'

    def cmd_vpn(self, msg, uid, chat, arg):
        return self.cb_vpn(uid, chat, None)

    def cb_vpn(self, uid, chat, mid):
        if not self._vpn_admin(uid):
            return self.screen(chat, mid, '⛔ ' + _(ADMIN_ONLY), None)
        if self.vpn is None:
            return self.screen(chat, mid, _('The VPN is not available here.'), None)
        st = self.vpn.status()
        if not st['configured']:
            return self.screen(chat, mid, _('No VPN subscription is set. Paste its URL on the plugin\'s '
                                            'settings page in PegaProx (Telegram Bot tab).'), None)
        lines = [_('<b>VPN for Telegram</b>')]
        if st['current']:
            lines.append(_('Server: <b>{name}</b> ({host}:{port}, {transport})', name=v.e(st['current']['name']),
                           host=v.e(st['current']['host']), port=st['current']['port'],
                           transport=v.e(st['current']['transport'])))
        else:
            lines.append(_('Server: none running'))
        lines.append(_('Telegram reachable: {ok}', ok='✅' if st['telegram_ok'] else '❌'))
        if st['last_refresh']:
            lines.append(_('Subscription downloaded: {when}', when=v.e(st['last_refresh'])))
        if st['last_error']:
            lines.append(_('Last error: {error}', error=v.e(st['last_error'])))
        kb = []
        current = (st['current'] or {}).get('name')
        for i, n in enumerate(st['servers']):
            if n['supported']:
                mark = '● ' if n['name'] == current else ''
                kb.append([self.btn(uid, (mark + n['name'])[:60], 'vpn_use', idx=i)])
        kb.append([self.btn(uid, _('🔄 Download the subscription again'), 'vpn_refresh')])
        return self.screen(chat, mid, '\n'.join(lines), kb)

    def cb_vpn_use(self, uid, chat, mid, idx):
        if not self._vpn_admin(uid):
            return self.screen(chat, mid, '⛔ ' + _(ADMIN_ONLY), None)
        servers = self.vpn.status()['servers']
        if not 0 <= idx < len(servers):
            return self.cb_vpn(uid, chat, mid)
        self.screen(chat, mid, _('Switching to {name}…', name=v.e(servers[idx]['name'])), None)
        self.vpn.use(servers[idx]['name'])
        return self.cb_vpn(uid, chat, mid)

    def cb_vpn_refresh(self, uid, chat, mid):
        if not self._vpn_admin(uid):
            return self.screen(chat, mid, '⛔ ' + _(ADMIN_ONLY), None)
        self.screen(chat, mid, _('Downloading the subscription…'), None)
        self.vpn.refresh()
        return self.cb_vpn(uid, chat, mid)
