#!/bin/sh
# Rauchtest: startet labwc ohne Bildschirm (headless) mit der Prisma-Shell, steuert sie über
# prisma-msg und speichert Bildschirmfotos. Benötigt: labwc, grim, dbus, GTK-Pakete von Prisma.
#
#   tests/smoke.sh [ausgabeordner]
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-/usr/bin/python3}"

if [ "${1:-}" = "--inner" ]; then
    OUT="$2"
    msg() { "$PYTHON" -m prisma.msg "$@"; }
    "$PYTHON" -m prisma.shell.main >"$OUT/shell.log" 2>&1 &
    SHELL_PID=$!
    sleep 4
    snap() { sleep 1.2; grim "$OUT/$1.png"; }

    command -v foot >/dev/null && { foot -T "Projektplan – Editor" >/dev/null 2>&1 & sleep 1; }
    command -v notify-send >/dev/null && notify-send -u critical -a Kalender "Termin in 10 Minuten" "Sprint-Review"
    snap 01-desktop
    msg kompass; snap 02-kompass
    msg kompass; sleep 0.4
    msg kompass "3,5*12+8"; snap 02-kompass-rechner
    msg kompass; sleep 0.4
    msg kompass "10 km in mi"; snap 02-kompass-einheiten
    msg kompass; sleep 0.4
    msg quicksettings; snap 03-schnelleinstellungen
    msg quicksettings; sleep 0.4
    msg daypanel; snap 04-tagesueberblick
    msg daypanel; sleep 0.4
    msg facet kreativ; snap 05-facette-kreativ
    msg facet 1; sleep 0.5
    msg theme-cycle; msg focus 25; snap 06-hell-fokus

    if kill -0 "$SHELL_PID" 2>/dev/null; then echo ok >"$OUT/result"; else echo "Shell abgestürzt" >"$OUT/result"; fi
    kill "$SHELL_PID" 2>/dev/null || true
    kill "$LABWC_PID" 2>/dev/null || true
    exit 0
fi

OUT="$(mkdir -p "${1:-$ROOT/smoke-output}" && cd "${1:-$ROOT/smoke-output}" && pwd)"
rm -f "$OUT/result"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/run" "$TMP/config" "$TMP/state" "$TMP/data"
chmod 700 "$TMP/run"

export XDG_RUNTIME_DIR="$TMP/run" XDG_CONFIG_HOME="$TMP/config" XDG_STATE_HOME="$TMP/state" XDG_DATA_HOME="$TMP/data"
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 WLR_HEADLESS_OUTPUTS=1
export PYTHONPATH="$ROOT" PYTHON
unset WAYLAND_DISPLAY DISPLAY

# Prisma-Konfiguration für labwc verwenden – ohne autostart, die Shell startet der Test selbst.
mkdir -p "$TMP/labwc"
cp "$ROOT/data/labwc/rc.xml" "$ROOT/data/labwc/menu.xml" "$ROOT/data/labwc/environment" "$TMP/labwc/"
mkdir -p "$TMP/config/prisma" "$TMP/data/themes"
echo '{"user_name": "Alex"}' >"$TMP/config/prisma/config.json"
cp -r "$ROOT/data/themes/Prisma" "$TMP/data/themes/"

timeout 90 dbus-run-session -- labwc -C "$TMP/labwc" -s "sh '$ROOT/tests/smoke.sh' --inner '$OUT'" >"$OUT/labwc.log" 2>&1 || true

if [ "$(cat "$OUT/result" 2>/dev/null)" = "ok" ]; then
    echo "Rauchtest bestanden – Bildschirmfotos in $OUT"
    grep -i "traceback" "$OUT/shell.log" && { echo "…aber mit Python-Fehlern im Log:"; cat "$OUT/shell.log"; exit 1; }
    exit 0
fi
echo "Rauchtest fehlgeschlagen" >&2
cat "$OUT/shell.log" >&2 2>/dev/null || true
exit 1
