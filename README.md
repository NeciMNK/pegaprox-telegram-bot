# Telegram Bot plugin for PegaProx

A community plugin for [PegaProx](https://github.com/PegaProx/project-pegaprox) that lets you
manage Proxmox from Telegram. Each Telegram user links their own PegaProx account with an API
token, and the bot acts with that token's permissions: no more and no less than in the web UI.
Every action lands in the PegaProx audit log under that user.

The bot runs inside PegaProx as a plugin background task. Its calls go straight into PegaProx's
own API handling in the same process (auth, RBAC, CSRF gate, audit log), so there is no URL,
TLS certificate or extra service to set up.

## Features

- Clusters: health, nodes online, guests running.
- Nodes: CPU, RAM, disk, uptime; reboot and shutdown (PegaProx allows these only for a node
  in maintenance mode).
- VMs and containers: paged list, `/find`, start, shutdown, reboot, stop, reset, suspend.
  Destructive actions ask for confirmation.
- Snapshots: list, create, rollback, delete.
- Backups: list, run a backup to a chosen storage (vzdump, snapshot mode, zstd).
- Migration to another node (live for a running VM).
- Firewall: datacenter (on/off, rules on/off) and the rules of a single VM/CT. A rule button
  checks that the rule is still the one it was drawn for, so a list that changed in the web UI
  never toggles the wrong rule.
- Storage and the latest cluster tasks.
- Alerts: list active ones, acknowledge, and the bot pushes new ones (`/notify off` turns it off).
- PegaProx users (`/users`): list, create, change role, enable and disable, set a new password,
  reset 2FA, delete. Needs the `admin.users` permission, and PegaProx's own limits apply as in
  the web UI. Works only in a private chat; password messages are deleted right away.
- English and Russian: `/lang en|ru` (or the 🌐 button) per user; the default is set on the
  settings page.
- `/api METHOD /api/path [JSON]`: any PegaProx API call when the buttons are not enough
  (private chat only).

## Install

Needs PegaProx 1.4.1 or newer, and a PegaProx host that reaches `api.telegram.org` (directly or
through a proxy, see below). No extra Python packages: the plugin uses `requests`, which PegaProx
already ships with.

1. Copy the `telegram_bot` folder into the PegaProx plugins directory
   (`/opt/PegaProx/plugins` in a standard install, or `PEGAPROX_PLUGINS_DIR`):
   ```bash
   git clone https://github.com/NeciMNK/pegaprox-telegram-bot.git
   sudo cp -r pegaprox-telegram-bot/telegram_bot /opt/PegaProx/plugins/
   sudo chown -R pegaprox:pegaprox /opt/PegaProx/plugins/telegram_bot   # the user PegaProx runs as
   ```
2. In PegaProx open **Settings → Server → Plugins**, press **Rescan**, and enable
   **Telegram Bot**. PegaProx marks it as a community plugin: it runs with PegaProx's full
   privileges, as every plugin does, so read the code before enabling it.
3. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
4. Open the plugin's **Telegram Bot** tab (admins only), paste the token and save. The plugin
   checks it with Telegram before it saves it.

### Settings

| Setting | Default | Meaning |
|---|---|---|
| Bot token | | from @BotFather; stored encrypted with PegaProx's own key, never shown again |
| Allowed Telegram user ids | empty | when set, the bot ignores everyone else |
| Default language | English | for users who did not pick one with `/lang` |
| Alert check interval | 60 | seconds between checks for new alerts, `0` turns alert messages off |
| Proxy | empty | `http://host:port` or `socks5h://host:port` if the host reaches Telegram only through a proxy (SOCKS needs the `PySocks` package) |

The settings and the linked accounts live in `<PegaProx config dir>/telegram_bot/` (mode 0700,
files 0600), not in the plugin folder, so the core's plugin config editor never shows them.
The page also lists the linked Telegram accounts, and an admin can unlink any of them.

With PegaProx high availability, the bot runs only on the active instance, like every plugin
background task. Copy the plugin folder to every instance.

## Linking an account

1. In PegaProx: **My Profile → API Tokens** → create a token. The token's role can be lower than
   your own, for example `viewer` if Telegram should only be able to look.
2. In a private chat with the bot: `/login pgx_...`. The bot checks the token and deletes the
   message right away.
3. `/menu` opens the clusters.

`/logout` unlinks the account; revoke the token in PegaProx afterwards. If the token is revoked
or the user loses a permission, the bot loses it at once, since PegaProx checks every call.

## Security

- Each user acts with their own token, so the PegaProx permission checks, tenant limits and
  audit log apply unchanged. The bot itself holds no privileges.
- Never post a token in a group. The bot accepts tokens only in a private chat and tries to
  delete a token it sees anywhere else, but it can delete group messages only if it is an admin
  there. If a token was ever exposed, revoke it in PegaProx right away.
- Buttons are bound to the user who opened them: someone else's buttons in a group do nothing.
- The settings page and its API are for PegaProx admins only (the token's effective role counts,
  so an admin's viewer-scoped token is not enough).

## Translations

The English text in the code is the key; `telegram_bot/lang_ru.py` maps it to Russian. To add a
language, add a `lang_<code>.py` with the same keys and list it in `telegram_bot/i18n.py`.
`tests/test_telegram_bot_lang.py` checks that every text has a translation with the same
placeholders and HTML tags.

## Development and tests

The tests run inside a PegaProx checkout, against the real PegaProx app:

```bash
git clone -b Testing https://github.com/PegaProx/project-pegaprox.git pegaprox
cp -r telegram_bot pegaprox/plugins/
cp tests/*.py pegaprox/tests/
cd pegaprox && pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/test_tgbot.py tests/test_tgbot_users.py tests/test_tgbot_against_pegaprox.py tests/test_telegram_bot_plugin.py tests/test_telegram_bot_lang.py
```

GitHub Actions does the same on every push (`.github/workflows/tests.yml`).

## License and credits

AGPL-3.0, like PegaProx. Written by NeciMNK with the help of an AI assistant (Claude Code).
It started as a standalone service proposed in PegaProx/project-pegaprox#1231 and became a
plugin at the maintainers' suggestion.
