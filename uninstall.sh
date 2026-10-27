#!/bin/sh
# Tenwin entfernen. Stellt den vorherigen Anmeldemanager wieder her, falls
# install.sh ihn umgestellt hat. Benutzereinstellungen (~/.config/tenwin)
# bleiben erhalten; mit --purge werden sie für den aktuellen Benutzer gelöscht.
set -eu

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO=sudo; fi

previous=$(cat /var/lib/tenwin-previous-display-manager 2>/dev/null || true)
if [ -n "$previous" ] && [ -x "$previous" ]; then
    name=$(basename "$previous")
    echo "Stelle den Anmeldemanager wieder auf $name um …"
    echo "$name shared/default-x-display-manager select $name" | $SUDO debconf-set-selections
    $SUDO env DEBIAN_FRONTEND=noninteractive dpkg-reconfigure "$name" || true
    $SUDO rm -f /var/lib/tenwin-previous-display-manager
fi

pkgs=""
for p in tenwin-greeter tenwin-desktop; do
    if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed"; then
        pkgs="$pkgs $p"
    fi
done
if [ -n "$pkgs" ]; then
    # shellcheck disable=SC2086
    $SUDO apt-get remove -y $pkgs
fi

if [ "$PURGE" = 1 ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/tenwin" "${XDG_STATE_HOME:-$HOME/.local/state}/tenwin" \
        "${XDG_CACHE_HOME:-$HOME/.cache}/tenwin" "${XDG_CONFIG_HOME:-$HOME/.config}/dconf/tenwin" \
        "${XDG_DATA_HOME:-$HOME/.local/share}/themes/Tenwin-Accent"
    echo "Benutzereinstellungen gelöscht."
fi
echo "Tenwin wurde entfernt."
