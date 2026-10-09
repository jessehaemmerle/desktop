#!/bin/sh
# Prisma – Installation auf Ubuntu 24.04+ und darauf basierenden Distributionen
# (Linux Mint 22, Pop!_OS 24.04, Zorin OS 18, elementary OS 8, KDE neon, …)
#
#   ./install.sh            installiert Abhängigkeiten und Prisma nach /usr/local
#   ./install.sh --deps     nur Abhängigkeiten
#   ./install.sh --remove   Prisma entfernen
set -eu

cd "$(dirname "$0")"

REQUIRED="labwc python3 python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 \
gir1.2-gtk-4.0 gir1.2-adw-1 dbus-user-session"
RECOMMENDED="swaylock swayidle grim slurp wl-clipboard brightnessctl wireplumber network-manager \
fonts-inter papirus-icon-theme xdg-desktop-portal-wlr xdg-desktop-portal-gtk foot policykit-1-gnome \
wlr-randr wlopm libnotify-bin"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Dieses Skript ist für Ubuntu-basierte Systeme (apt) gedacht." >&2
    exit 1
fi

case "${1:-}" in
    --remove)
        $SUDO make uninstall PREFIX=/usr/local
        echo "Prisma wurde entfernt. Persönliche Einstellungen liegen weiterhin in ~/.config/prisma."
        exit 0
        ;;
esac

echo "→ Installiere Abhängigkeiten …"
$SUDO apt-get update
# shellcheck disable=SC2086
$SUDO apt-get install -y $REQUIRED
for package in $RECOMMENDED; do
    # Empfohlene Pakete einzeln, damit ein fehlendes Paket nicht alles abbricht.
    $SUDO apt-get install -y "$package" >/dev/null 2>&1 || echo "   (optional, übersprungen: $package)"
done

[ "${1:-}" = "--deps" ] && exit 0

echo "→ Installiere Prisma nach /usr/local …"
$SUDO make install PREFIX=/usr/local

cat <<'MSG'

✔ Prisma ist installiert.

  Abmelden und im Anmeldebildschirm über das Zahnrad die Sitzung „Prisma“ wählen.
  Zum Ausprobieren innerhalb einer laufenden Sitzung:  make run

  Erste Schritte:  Super+Leertaste öffnet den Kompass, Super+1/2/3 wechselt die Facette.
MSG
