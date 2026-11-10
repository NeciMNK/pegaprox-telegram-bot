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
- VPN for Telegram: paste a VPN subscription URL and the plugin reaches Telegram through
  `xray` with a server from it, downloads the subscription again on a timer and moves to the
  next server when Telegram stops answering. `/vpn` (admins) shows and switches the server.

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
| VPN subscription URL | empty | see [VPN for Telegram](#vpn-for-telegram); stored encrypted, never shown again; when set, Proxy is not used |
| VPN server | Automatic | a server from the subscription, or the first one that reaches Telegram |
| Download the subscription again | 6 hours | `0`: only when Telegram stops answering or on the button |
| Path to xray | empty | found in `/usr/local/bin`, `/usr/bin` or `PATH` |

The settings and the linked accounts live in `<PegaProx config dir>/telegram_bot/` (mode 0700,
files 0600), not in the plugin folder, so the core's plugin config editor never shows them.
The page also lists the linked Telegram accounts, and an admin can unlink any of them.

With PegaProx high availability, the bot runs only on the active instance, like every plugin
background task. Copy the plugin folder to every instance.

## VPN for Telegram

Where the provider blocks Telegram, the plugin can reach it through a VPN subscription, the
link a VPN service gives for v2rayN, Hiddify and similar apps (`https://.../sub/...`).

1. Install [xray](https://github.com/XTLS/Xray-core) on the PegaProx host, for example:
   ```bash
   bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
   systemctl disable --now xray   # the plugin runs its own xray, the system service is not needed
   ```
2. On the plugin's page, under **VPN for Telegram**, paste the subscription URL and press
   **Save VPN**. The plugin checks the subscription before it saves it.

The plugin then runs xray as the PegaProx user (no root), with an HTTP proxy on
`127.0.0.1` only, and sends the bot's Telegram traffic through it. The subscription itself is
downloaded directly. Supported servers: VLESS (TCP, WebSocket, gRPC, XHTTP, HTTPUpgrade; TLS or
Reality), VMess, Trojan and Shadowsocks. Hysteria2 servers are listed but skipped.

- When the VPN provider changes servers or keys, the next download picks them up: every
  6 hours by default, at once with **Download again and reconnect**, or with `/vpn`.
- When Telegram stops answering for about half a minute, the plugin downloads the
  subscription again and tries the next server, at most once every two minutes.
- `/vpn` in the bot (PegaProx admins only) shows the server and whether Telegram is
  reachable, switches to another server, and downloads the subscription again. The URL
  itself can only be changed on the settings page, never in a chat.
- xray's config and log are in `<PegaProx config dir>/telegram_bot/vpn/` (mode 0700).

## Updating

PegaProx has no plugin store: an update replaces the plugin folder, and **Reload** next to
the plugin (Settings → Server → Plugins) starts the new code without restarting PegaProx.
The settings and linked accounts are kept, since they live in the PegaProx config directory.

```bash
curl -fsSL https://raw.githubusercontent.com/NeciMNK/pegaprox-telegram-bot/main/update.sh | sudo sh
```

`update.sh` installs the latest release (or `sudo sh update.sh v1.2.0`, or `main`) and keeps
the previous folder as `.telegram_bot.bak`. Releases are on the
[Releases page](https://github.com/NeciMNK/pegaprox-telegram-bot/releases), with
`telegram_bot.zip` for a manual copy.

To publish a release: raise `version` in `telegram_bot/manifest.json`, add it to the change
log below, merge, and push a tag `v<version>`. GitHub Actions checks that the tag matches the
manifest and publishes the release.

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
python -m pytest tests/test_tgbot.py tests/test_tgbot_users.py tests/test_tgbot_against_pegaprox.py tests/test_telegram_bot_plugin.py tests/test_telegram_bot_lang.py tests/test_telegram_bot_vpn.py
```

GitHub Actions does the same on every push (`.github/workflows/tests.yml`).

## Changes

### 1.2.1

- The VPN's xray did not start when PegaProx's config directory is a relative path (the
  standard install): xray looked for its config relative to its own folder.
- `update.sh` keeps the previous copy as `.telegram_bot.bak`, which PegaProx does not list
  as a plugin.

### 1.2.0

- VPN for Telegram: a VPN subscription URL on the settings page; the plugin runs xray with a
  server from it, downloads it again on a timer, and moves to the next server when Telegram
  stops answering.
- `/vpn` for PegaProx admins: the server in use, switching servers, downloading again.
- `update.sh` and GitHub releases for updating the plugin.

### 1.1.0

- Russian translation (`/lang`).

### 1.0.0

- First release as a PegaProx plugin.

## License and credits

AGPL-3.0, like PegaProx. Written by NeciMNK with the help of an AI assistant (Claude Code).
It started as a standalone service proposed in PegaProx/project-pegaprox#1231 and became a
plugin at the maintainers' suggestion.
