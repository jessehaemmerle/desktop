#!/bin/sh
# Start Tenwin from the source tree in a window inside your current desktop
# (labwc runs nested on X11 or Wayland). Uses your real home directory but a
# separate settings file, so your installed Tenwin settings stay untouched.
#
#   tools/dev-session.sh
#
# It gets its own D-Bus session and does not touch your systemd user
# environment (TENWIN_NESTED=1).
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
make -s -C "$ROOT" all

export TENWIN_CONFIG_DIR="${TENWIN_CONFIG_DIR:-$HOME/.config/tenwin-dev}"
export PATH="$ROOT/bin:$ROOT/build/helpers:$PATH"
export XDG_CURRENT_DESKTOP=Tenwin:wlroots
export DCONF_PROFILE=tenwin
mkdir -p "$TENWIN_CONFIG_DIR"

export TENWIN_NESTED=1
CONFIG_DIR=$("$ROOT/bin/tenwin-python" -m tenwin.session prepare | tail -n 1)
echo "Starting nested labwc. Close its window to quit."
exec dbus-run-session -- labwc -C "$CONFIG_DIR"
