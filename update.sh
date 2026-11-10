#!/bin/sh
# Install or update the Telegram Bot plugin on a PegaProx host.
#
#   sudo sh update.sh            # the latest release
#   sudo sh update.sh v1.2.0     # a given release
#   sudo sh update.sh main       # the main branch
#
# The settings and the linked accounts live in the PegaProx config directory, not in the
# plugin folder, so an update keeps them. The old folder is kept as .telegram_bot.bak
# (hidden: PegaProx skips folders starting with a dot, so it is not listed as a plugin).
# Afterwards press Reload next to the plugin in Settings -> Server -> Plugins (no restart).
set -eu

REPO=NeciMNK/pegaprox-telegram-bot
PLUGINS_DIR=${PEGAPROX_PLUGINS_DIR:-/opt/PegaProx/plugins}
REF=${1:-latest}

[ -d "$PLUGINS_DIR" ] || { echo "No plugins directory at $PLUGINS_DIR (set PEGAPROX_PLUGINS_DIR)" >&2; exit 1; }

if [ "$REF" = latest ]; then
    REF=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
          | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)
    [ -n "$REF" ] || { echo "Could not find the latest release, pass a version or main" >&2; exit 1; }
fi
case "$REF" in
    *[!A-Za-z0-9._-]*) echo "Bad version: $REF" >&2; exit 1 ;;
esac

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Downloading $REPO $REF"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$TMP/src.tar.gz"
tar -xzf "$TMP/src.tar.gz" -C "$TMP"
SRC=$(find "$TMP" -mindepth 2 -maxdepth 2 -type d -name telegram_bot | head -n1)
[ -f "$SRC/manifest.json" ] || { echo "No telegram_bot folder in the download" >&2; exit 1; }

OWNER=$(stat -c %U:%G "$PLUGINS_DIR")
DEST="$PLUGINS_DIR/telegram_bot"
BAK="$PLUGINS_DIR/.telegram_bot.bak"
rm -rf "$PLUGINS_DIR/telegram_bot.bak"  # left by update.sh 1.2.0, PegaProx listed it as a plugin
if [ -d "$DEST" ]; then
    rm -rf "$BAK"
    mv "$DEST" "$BAK"
fi
cp -r "$SRC" "$DEST"
chown -R "$OWNER" "$DEST"

VERSION=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$DEST/manifest.json")
echo "Installed Telegram Bot $VERSION into $DEST (the previous copy is in $BAK)."
echo "Now press Reload next to Telegram Bot in PegaProx: Settings -> Server -> Plugins."
