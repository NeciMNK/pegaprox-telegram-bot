# -*- coding: utf-8 -*-
"""Linked accounts: Telegram user id -> PegaProx API token.

The tokens are encrypted with PegaProx's own key (the same one that protects cluster
passwords in its database), and the file is readable by the PegaProx user only.
"""
import json
import os
import threading


class Store:
    def __init__(self, data_dir, encrypt, decrypt):
        self.data_dir = data_dir
        os.makedirs(data_dir, mode=0o700, exist_ok=True)
        self._path = os.path.join(data_dir, 'accounts.json')
        self._lock = threading.Lock()
        self._encrypt, self._decrypt = encrypt, decrypt
        self._data = self._read()

    def _read(self):
        if not os.path.exists(self._path):
            return {}
        with open(self._path, encoding='utf-8') as f:
            return json.load(f)

    def _write(self):
        tmp = self._path + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)

    def link(self, tg_id, token, info=None):
        with self._lock:
            self._data[str(tg_id)] = {
                'token': self._encrypt(token),
                'info': info or {},
                'notify': True,
                'seen_alerts': [],
            }
            self._write()

    def unlink(self, tg_id):
        with self._lock:
            existed = self._data.pop(str(tg_id), None) is not None
            if existed:
                self._write()
            return existed

    def token(self, tg_id):
        rec = self._data.get(str(tg_id))
        if not rec:
            return None
        try:
            return self._decrypt(rec['token']) or None
        except Exception:  # a key change or a damaged entry: the user links again
            return None

    def get(self, tg_id):
        return self._data.get(str(tg_id))

    def set_notify(self, tg_id, on):
        with self._lock:
            rec = self._data.get(str(tg_id))
            if rec:
                rec['notify'] = bool(on)
                self._write()

    def set_lang(self, tg_id, lang):
        with self._lock:
            rec = self._data.get(str(tg_id))
            if rec:
                rec['lang'] = lang
                self._write()

    def unseen(self, tg_id, keys):
        """The alert ids not sent to this user yet."""
        with self._lock:
            rec = self._data.get(str(tg_id))
            if not rec:
                return []
            known = set(rec.get('seen_alerts') or [])
            return [k for k in keys if k not in known]

    def mark_seen(self, tg_id, keys, keep=500):
        """Remember alert ids already sent. Returns the ids that are new."""
        with self._lock:
            rec = self._data.get(str(tg_id))
            if not rec:
                return []
            seen = rec.get('seen_alerts') or []
            known = set(seen)
            new = [k for k in keys if k not in known]
            if new:
                rec['seen_alerts'] = (seen + new)[-keep:]
                self._write()
            return new

    def linked_ids(self):
        return [int(k) for k in list(self._data.keys())]

    def accounts(self):
        """[(telegram id, info)] for the settings page; never the tokens."""
        with self._lock:
            return [(int(k), dict(rec.get('info') or {}), bool(rec.get('notify', True)), rec.get('lang') or '')
                    for k, rec in self._data.items()]
