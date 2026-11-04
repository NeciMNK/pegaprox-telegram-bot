# -*- coding: utf-8 -*-
"""A thin client for the PegaProx REST API, called inside the PegaProx process.

Every call carries the linked user's own API token (Authorization: Bearer pgx_...) and
goes through PegaProx's own request handling (auth, RBAC, CSRF gate, audit log), so the
user can do in Telegram exactly what their role allows in the web interface, and no
more. The calls never leave the process: no URL, TLS or proxy is involved.
"""
from urllib.parse import quote


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _q(part):
    return quote(str(part), safe='')


class InProcess:
    """Hands a request to the Flask app PegaProx runs, as if it came over HTTP."""

    def __init__(self, app):
        self.app = app

    def request(self, method, path, json=None, params=None, headers=None):
        with self.app.test_client() as client:
            r = client.open(path, method=method, json=json, query_string=params, headers=headers,
                            base_url='https://localhost')
            return r.status_code, r.get_json(silent=True)


class PegaProx:
    def __init__(self, token, transport):
        self.token = token
        self.transport = transport

    # -- core ---------------------------------------------------------------
    def request(self, method, path, json=None, params=None):
        if not path.startswith('/'):
            path = '/' + path
        try:
            status, body = self.transport.request(
                method.upper(), path, json=json, params=params,
                headers={'Authorization': f'Bearer {self.token}', 'Accept': 'application/json',
                         # PegaProx's CSRF gate wants this on every write
                         'X-Requested-With': 'XMLHttpRequest'})
        except Exception as e:  # a crash inside PegaProx must not take the bot down
            raise ApiError(500, f'PegaProx failed: {e.__class__.__name__}')
        if not 200 <= status < 300:  # a redirect is a failure too
            msg = ''
            if isinstance(body, dict):
                msg = body.get('error') or body.get('message') or ''
            raise ApiError(status, msg or f'HTTP {status}')
        return body

    def get(self, path, **params):
        return self.request('GET', path, params=params or None)

    def post(self, path, json=None):
        return self.request('POST', path, json=json if json is not None else {})

    # -- who am I -----------------------------------------------------------
    def me(self):
        return self.get('/api/me/permissions')

    # -- clusters and nodes ---------------------------------------------------
    def clusters(self):
        data = self.get('/api/clusters')
        return data if isinstance(data, list) else (data or {}).get('clusters', [])

    def nodes(self, cid):
        data = self.get(f'/api/clusters/{_q(cid)}/nodes')
        return data if isinstance(data, list) else (data or {}).get('nodes', [])

    def node_action(self, cid, node, action):
        return self.post(f'/api/clusters/{_q(cid)}/nodes/{_q(node)}/action/{_q(action)}')

    def tasks(self, cid, limit=15):
        data = self.get(f'/api/clusters/{_q(cid)}/tasks', limit=limit)
        return data if isinstance(data, list) else (data or {}).get('tasks', [])

    def datastores(self, cid):
        return self.get(f'/api/clusters/{_q(cid)}/datastores') or {}

    # -- guests -------------------------------------------------------------
    def vms(self, cid):
        return (self.get(f'/api/clusters/{_q(cid)}/vms') or {}).get('vms', [])

    def _vm(self, cid, node, vtype, vmid):
        return f'/api/clusters/{_q(cid)}/vms/{_q(node)}/{_q(vtype)}/{int(vmid)}'

    def vm_action(self, cid, node, vtype, vmid, action):
        return self.post(f'{self._vm(cid, node, vtype, vmid)}/{_q(action)}')

    def snapshots(self, cid, node, vtype, vmid):
        data = self.get(f'{self._vm(cid, node, vtype, vmid)}/snapshots')
        return data if isinstance(data, list) else (data or {}).get('snapshots', [])

    def create_snapshot(self, cid, node, vtype, vmid, name, description=''):
        return self.post(f'{self._vm(cid, node, vtype, vmid)}/snapshots',
                         {'snapname': name, 'description': description})

    def rollback_snapshot(self, cid, node, vtype, vmid, name):
        return self.post(f'{self._vm(cid, node, vtype, vmid)}/snapshots/{_q(name)}/rollback')

    def delete_snapshot(self, cid, node, vtype, vmid, name):
        return self.request('DELETE', f'{self._vm(cid, node, vtype, vmid)}/snapshots/{_q(name)}')

    def backups(self, cid, node, vtype, vmid):
        data = self.get(f'{self._vm(cid, node, vtype, vmid)}/backups')
        return data if isinstance(data, list) else (data or {}).get('backups', [])

    def create_backup(self, cid, node, vtype, vmid, storage, mode='snapshot'):
        return self.post(f'{self._vm(cid, node, vtype, vmid)}/backups/create',
                         {'storage': storage, 'mode': mode, 'compress': 'zstd',
                          'notes': 'Telegram'})

    def migrate(self, cid, node, vtype, vmid, target, online=True):
        return self.post(f'{self._vm(cid, node, vtype, vmid)}/migrate',
                         {'target': target, 'online': bool(online)})

    # -- firewall -------------------------------------------------------------
    def dc_firewall_options(self, cid):
        return self.get(f'/api/clusters/{_q(cid)}/datacenter/firewall/options') or {}

    def set_dc_firewall_enabled(self, cid, enabled):
        return self.request('PUT', f'/api/clusters/{_q(cid)}/datacenter/firewall/options',
                            json={'enable': 1 if enabled else 0})

    def dc_firewall_rules(self, cid):
        return self.get(f'/api/clusters/{_q(cid)}/datacenter/firewall/rules') or []

    def set_dc_firewall_rule(self, cid, pos, enabled):
        return self.request('PUT', f'/api/clusters/{_q(cid)}/datacenter/firewall/rules/{int(pos)}',
                            json={'enable': 1 if enabled else 0})

    def vm_firewall_rules(self, cid, node, vtype, vmid):
        return self.get(f'/api/clusters/{_q(cid)}/vms/{_q(node)}/{_q(vtype)}/{int(vmid)}/firewall/rules') or []

    def set_vm_firewall_rule(self, cid, node, vtype, vmid, pos, enabled):
        return self.request(
            'PUT', f'/api/clusters/{_q(cid)}/vms/{_q(node)}/{_q(vtype)}/{int(vmid)}/firewall/rules/{int(pos)}',
            json={'enable': 1 if enabled else 0})

    # -- alerts -------------------------------------------------------------
    def active_alerts(self, cid):
        data = self.get(f'/api/clusters/{_q(cid)}/active-alerts') or {}
        if data.get('error'):  # PegaProx answers 200 with an error when its database read fails
            raise ApiError(500, data['error'])
        return data.get('active_alerts', [])

    def search(self, q):
        return (self.get('/api/global/search', q=q, type='all') or {}).get('results', [])

    def ack_alert(self, cid, fired_id):
        return self.post(f'/api/clusters/{_q(cid)}/active-alerts/{_q(fired_id)}/ack')

    # -- PegaProx's own users (needs the admin.users permission) ----------------
    def panel_users(self):
        data = self.get('/api/users')
        return data if isinstance(data, list) else []

    def panel_roles(self):
        data = self.get('/api/roles')
        return data if isinstance(data, list) else []

    def create_panel_user(self, username, password, role, display_name='', email=''):
        return self.post('/api/users', {'username': username, 'password': password, 'role': role,
                                        'display_name': display_name or username, 'email': email})

    def update_panel_user(self, username, fields):
        return self.request('PUT', f'/api/users/{_q(username)}', json=fields)

    def set_panel_password(self, username, password):
        return self.request('PUT', f'/api/users/{_q(username)}/password', json={'password': password})

    def reset_panel_2fa(self, username):
        return self.request('DELETE', f'/api/users/{_q(username)}/2fa')

    def delete_panel_user(self, username):
        return self.request('DELETE', f'/api/users/{_q(username)}')
