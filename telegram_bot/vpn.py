# -*- coding: utf-8 -*-
"""VPN subscription support: the plugin reaches api.telegram.org through its own xray.

An admin pastes a subscription URL (the kind VPN panels hand out for v2rayN, Hiddify and
the like). The plugin downloads it, turns the chosen server into an xray config, and runs
xray as a child process with a local HTTP proxy on 127.0.0.1. When the provider changes
its servers or keys, the next refresh picks them up, and when Telegram stays unreachable
the plugin refreshes the subscription and tries the next server on its own.

Only standard library and `requests`. xray itself is a separate binary (XRAY_BIN).
"""
import base64
import binascii
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import parse_qsl, unquote, urlsplit

import requests

log = logging.getLogger('plugin.telegram_bot.vpn')

SUPPORTED = ('vless', 'vmess', 'trojan', 'ss')
XRAY_CANDIDATES = ('/usr/local/bin/xray', '/usr/bin/xray', '/opt/xray/xray')
USER_AGENT = 'v2rayN/7.0 (pegaprox-telegram-bot)'
MAX_SUB_BYTES = 1 << 20


class SubscriptionError(Exception):
    pass


# ------------------------------------------------------------------ parsing
def _b64(text):
    text = text.strip().replace('-', '+').replace('_', '/')
    return base64.b64decode(text + '=' * (-len(text) % 4), validate=False)


def parse_subscription(body):
    """The share links in a subscription body: plain lines or one base64 blob."""
    text = body.decode('utf-8', 'replace') if isinstance(body, bytes) else body
    text = text.strip()
    if '://' not in text:
        try:
            text = _b64(text).decode('utf-8', 'replace')
        except (binascii.Error, ValueError):
            raise SubscriptionError('subscription is neither share links nor base64')
    links = [ln.strip() for ln in text.splitlines() if '://' in ln]
    if not links:
        raise SubscriptionError('subscription has no servers')
    return links


def _name(u, fallback):
    return unquote(u.fragment).strip() or fallback


def parse_link(link):
    """A share link as a dict: scheme, name, host, port, and what the outbound needs.
    Unsupported schemes come back with supported=False so the page can still list them."""
    u = urlsplit(link)
    scheme = u.scheme.lower()
    if scheme == 'vmess':
        return _parse_vmess(link)
    if scheme == 'ss':
        return _parse_ss(link)
    try:
        port = u.port
    except ValueError:
        port = None
    node = {'scheme': scheme, 'host': u.hostname or '', 'port': port,
            'name': _name(u, f'{u.hostname}:{port}'), 'supported': scheme in SUPPORTED}
    if scheme in ('vless', 'trojan'):
        node['id'] = unquote(u.username or '')
        node['q'] = dict(parse_qsl(u.query))
    if node['supported'] and not (node['host'] and node['port'] and node.get('id')):
        node['supported'] = False
    return node


def _parse_vmess(link):
    try:
        v = json.loads(_b64(link[len('vmess://'):]).decode('utf-8', 'replace'))
        port = int(v.get('port') or 0)
    except (ValueError, binascii.Error):
        return {'scheme': 'vmess', 'name': 'vmess', 'host': '', 'port': None, 'supported': False}
    q = {'type': v.get('net') or 'tcp', 'security': v.get('tls') or 'none', 'sni': v.get('sni') or '',
         'host': v.get('host') or '', 'path': v.get('path') or '', 'fp': v.get('fp') or '',
         'serviceName': v.get('path') if v.get('net') == 'grpc' else '', 'alpn': v.get('alpn') or ''}
    host = v.get('add') or ''
    return {'scheme': 'vmess', 'host': host, 'port': port, 'id': v.get('id') or '',
            'aid': int(v.get('aid') or 0), 'scy': v.get('scy') or 'auto',
            'name': v.get('ps') or f'{host}:{port}', 'q': q,
            'supported': bool(host and port and v.get('id'))}


def _parse_ss(link):
    u = urlsplit(link)
    name = _name(u, 'shadowsocks')
    try:
        if u.username and not u.password:  # ss://base64(method:pass)@host:port
            method, password = _b64(unquote(u.username)).decode().split(':', 1)
            host, port = u.hostname, u.port
        elif u.password:
            method, password, host, port = unquote(u.username), unquote(u.password), u.hostname, u.port
        else:  # ss://base64(method:pass@host:port)
            raw = _b64(u.netloc).decode()
            cred, hp = raw.rsplit('@', 1)
            method, password = cred.split(':', 1)
            host, port = hp.rsplit(':', 1)
            port = int(port)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return {'scheme': 'ss', 'name': name, 'host': '', 'port': None, 'supported': False}
    return {'scheme': 'ss', 'name': name, 'host': host or '', 'port': port, 'method': method,
            'password': password, 'supported': bool(host and port)}


def describe(node):
    """What the settings page and /vpn show: no keys, ids or passwords."""
    q = node.get('q') or {}
    return {'name': node['name'], 'scheme': node['scheme'], 'host': node['host'], 'port': node['port'],
            'transport': q.get('type') or ('tcp' if node['scheme'] != 'ss' else ''),
            'security': q.get('security') or '', 'supported': node['supported']}


# ------------------------------------------------------------------ xray config
def _stream(q):
    net = (q.get('type') or 'tcp').lower()
    if net == 'http':
        net = 'xhttp' if q.get('mode') else 'tcp'
    sec = (q.get('security') or 'none').lower()
    s = {'network': net, 'security': sec if sec in ('tls', 'reality') else 'none'}
    if sec == 'reality':
        s['realitySettings'] = {'serverName': q.get('sni', ''), 'fingerprint': q.get('fp') or 'chrome',
                                'publicKey': q.get('pbk', ''), 'shortId': q.get('sid', ''),
                                'spiderX': unquote(q.get('spx', ''))}
    elif sec == 'tls':
        t = {'serverName': q.get('sni') or q.get('host', ''), 'fingerprint': q.get('fp') or 'chrome'}
        if q.get('alpn'):
            t['alpn'] = [a for a in unquote(q['alpn']).split(',') if a]
        if q.get('allowInsecure') in ('1', 'true'):
            t['allowInsecure'] = True
        s['tlsSettings'] = t
    if net == 'grpc':
        s['grpcSettings'] = {'serviceName': unquote(q.get('serviceName', '')),
                             'multiMode': q.get('mode') == 'multi'}
    elif net == 'ws':
        s['wsSettings'] = {'path': unquote(q.get('path') or '/'), 'host': q.get('host', '')}
    elif net == 'xhttp':
        x = {'path': unquote(q.get('path') or '/'), 'mode': q.get('mode') or 'auto'}
        if q.get('host'):
            x['host'] = q['host']
        s['xhttpSettings'] = x
    elif net == 'httpupgrade':
        s['httpupgradeSettings'] = {'path': unquote(q.get('path') or '/'), 'host': q.get('host', '')}
    elif net == 'tcp' and q.get('headerType') == 'http':
        s['tcpSettings'] = {'header': {'type': 'http', 'request': {
            'path': [unquote(q.get('path') or '/')], 'headers': {'Host': [q.get('host', '')]}}}}
    return s


def outbound(node):
    scheme = node['scheme']
    q = node.get('q') or {}
    if scheme == 'vless':
        user = {'id': node['id'], 'encryption': q.get('encryption') or 'none', 'flow': q.get('flow', '')}
        out = {'protocol': 'vless', 'settings': {'vnext': [
            {'address': node['host'], 'port': node['port'], 'users': [user]}]}}
    elif scheme == 'vmess':
        out = {'protocol': 'vmess', 'settings': {'vnext': [{'address': node['host'], 'port': node['port'], 'users': [
            {'id': node['id'], 'alterId': node.get('aid', 0), 'security': node.get('scy') or 'auto'}]}]}}
    elif scheme == 'trojan':
        out = {'protocol': 'trojan', 'settings': {'servers': [
            {'address': node['host'], 'port': node['port'], 'password': node['id']}]}}
        if not q.get('security'):
            q = dict(q, security='tls')
    elif scheme == 'ss':
        return {'tag': 'proxy', 'protocol': 'shadowsocks', 'settings': {'servers': [
            {'address': node['host'], 'port': node['port'], 'method': node['method'],
             'password': node['password']}]}}
    else:
        raise SubscriptionError(f'{scheme} is not supported')
    out['tag'] = 'proxy'
    out['streamSettings'] = _stream(q)
    return out


def xray_config(node, port):
    return {'log': {'loglevel': 'warning'},
            'inbounds': [{'tag': 'http', 'listen': '127.0.0.1', 'port': port, 'protocol': 'http'}],
            'outbounds': [outbound(node), {'tag': 'direct', 'protocol': 'freedom'}]}


# ------------------------------------------------------------------ download
def fetch(url, timeout=30, session=None):
    """Subscription servers, in the provider's order. The download goes direct: the
    subscription host is usually reachable even where Telegram is not."""
    if not url.lower().startswith(('https://', 'http://')):
        raise SubscriptionError('subscription URL must start with https://')
    http = session or requests
    try:
        r = http.get(url, timeout=timeout, headers={'User-Agent': USER_AGENT}, stream=True)
        body = r.raw.read(MAX_SUB_BYTES + 1, decode_content=True) if hasattr(r, 'raw') and r.raw else r.content
    except requests.RequestException as e:
        raise SubscriptionError(f'download failed: {e.__class__.__name__}')
    if r.status_code != 200:
        raise SubscriptionError(f'download failed: HTTP {r.status_code}')
    if len(body) > MAX_SUB_BYTES:
        raise SubscriptionError('subscription is too large')
    return [parse_link(ln) for ln in parse_subscription(body)]


def pick(nodes, preferred=''):
    """Supported servers, the preferred one (by name) first."""
    ok = [n for n in nodes if n['supported']]
    first = [n for n in ok if preferred and n['name'] == preferred]
    return first + [n for n in ok if n not in first]


def find_xray(configured=''):
    for path in ([configured] if configured else []) + [shutil.which('xray') or ''] + list(XRAY_CANDIDATES):
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ''


def free_port(preferred):
    for port in (preferred, 0):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', port))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    raise SubscriptionError('no free local port for xray')


# ------------------------------------------------------------------ the xray child process
class XrayRunner:
    """Owns one xray process. Thread-safe; the bot loop and the settings routes both use it."""

    def __init__(self, workdir, port=10810):
        self.workdir = workdir
        self.port = port
        self.proc = None
        self.node = None
        self.lock = threading.Lock()

    @property
    def proxy(self):
        return f'http://127.0.0.1:{self.port}' if self.running() else ''

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _kill_leftover(self, cfg):
        """An xray left running by a PegaProx that was killed: stop it, it holds the port."""
        pidfile = os.path.join(self.workdir, 'xray.pid')
        try:
            pid = int(open(pidfile).read().strip())
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                if cfg.encode() in f.read():
                    os.kill(pid, 15)
                    time.sleep(0.5)
        except (OSError, ValueError):
            pass

    def start(self, node, xray_bin):
        with self.lock:
            self._stop()
            os.makedirs(self.workdir, mode=0o700, exist_ok=True)
            self._kill_leftover(os.path.join(self.workdir, 'xray.json'))
            self.port = free_port(self.port)
            cfg = os.path.join(self.workdir, 'xray.json')
            fd = os.open(cfg + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(xray_config(node, self.port), f, indent=1)
            os.replace(cfg + '.tmp', cfg)
            logpath = os.path.join(self.workdir, 'xray.log')
            if os.path.exists(logpath) and os.path.getsize(logpath) > MAX_SUB_BYTES:
                os.replace(logpath, logpath + '.1')
            logf = open(logpath, 'ab')
            try:
                self.proc = subprocess.Popen([xray_bin, 'run', '-c', cfg], stdout=logf, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, cwd=self.workdir, close_fds=True)
            finally:
                logf.close()
            with open(os.path.join(self.workdir, 'xray.pid'), 'w') as f:
                f.write(str(self.proc.pid))
            self.node = node
            for _ in range(30):  # wait for the inbound to listen
                if self.proc.poll() is not None:
                    self.proc = None
                    raise SubscriptionError('xray exited at start, see xray.log')
                try:
                    socket.create_connection(('127.0.0.1', self.port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            log.info('xray started for %s (%s:%s)', node['name'], node['host'], node['port'])

    def stop(self):
        with self.lock:
            self._stop()

    def _stop(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None
            self.node = None


def check_telegram(proxy, timeout=10, session=None):
    """api.telegram.org answers through the proxy."""
    http = session or requests
    try:
        r = http.get('https://api.telegram.org/', timeout=timeout,
                     proxies={'http': proxy, 'https': proxy} if proxy else None)
        return r.status_code < 500
    except requests.RequestException:
        return False
