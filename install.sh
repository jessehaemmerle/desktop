#!/bin/sh
# Tenwin – Installation auf Ubuntu 24.04 und neuer (und Ableitungen).
#
#   ./install.sh                 baut die .deb-Pakete und installiert sie
#   ./install.sh --with-greeter  zusätzlich LightDM-Anmeldebildschirm aktivieren
#   ./install.sh --no-greeter    nur die Sitzung, Anmeldemanager unverändert
#   ./install.sh --yes           keine Rückfragen
#
# Nach der Installation im Anmeldebildschirm die Sitzung "Tenwin" wählen.
set -eu

ROOT=$(cd "$(dirname "$0")" && pwd)
GREETER=ask
YES=0
for arg in "$@"; do
    case "$arg" in
        --with-greeter) GREETER=yes ;;
        --no-greeter) GREETER=no ;;
        --yes|-y) YES=1 ;;
        --help|-h) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWarnung:\033[0m %s\n' "$*" >&2; }

ask() {
    # ask "Frage" default(j/n)
    if [ "$YES" = 1 ]; then
        [ "$2" = j ]
        return
    fi
    if [ "$2" = j ]; then prompt="[J/n]"; else prompt="[j/N]"; fi
    printf '%s %s ' "$1" "$prompt"
    read -r answer || answer=""
    case "$answer" in
        [jJyY]*) return 0 ;;
        [nN]*) return 1 ;;
        "") [ "$2" = j ] ;;
        *) return 1 ;;
    esac
}

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO=sudo
    command -v sudo >/dev/null 2>&1 || { echo "sudo wird benötigt." >&2; exit 1; }
fi

# --- System prüfen -------------------------------------------------------
if [ -r /etc/os-release ]; then
    . /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *" ubuntu "*|*" debian "*) ;;
        *) warn "Tenwin ist für Ubuntu-basierte Systeme gedacht (gefunden: ${PRETTY_NAME:-unbekannt})." ;;
    esac
    if [ "${ID:-}" = ubuntu ]; then
        major=$(printf '%s' "${VERSION_ID:-0}" | cut -d. -f1)
        if [ "$major" -lt 24 ]; then
            warn "Ubuntu ${VERSION_ID} ist zu alt: labwc 0.7 gibt es erst ab Ubuntu 24.04."
            ask "Trotzdem fortfahren?" n || exit 1
        fi
    fi
fi

# --- Bauen -------------------------------------------------------------------
say "Installiere Build-Abhängigkeiten …"
$SUDO apt-get update
$SUDO apt-get install -y --no-install-recommends build-essential debhelper dpkg-dev fakeroot gettext \
    libcairo2-dev libgdk-pixbuf-2.0-dev libpam0g-dev libpango1.0-dev libwayland-bin libwayland-dev \
    libxkbcommon-dev pkgconf wayland-protocols

BUILD=$(mktemp -d "${TMPDIR:-/tmp}/tenwin-build.XXXXXX")
trap 'rm -rf "$BUILD"' EXIT
say "Baue Pakete in $BUILD …"
mkdir -p "$BUILD/tenwin"
# Saubere Kopie ohne alte Build-Ergebnisse.
(cd "$ROOT" && tar --exclude=./build --exclude=./.git --exclude='*.deb' -cf - .) | (cd "$BUILD/tenwin" && tar -xf -)
(cd "$BUILD/tenwin" && dpkg-buildpackage -us -uc -b >"$BUILD/build.log" 2>&1) || {
    echo "Der Build ist fehlgeschlagen. Letzte Zeilen aus $BUILD/build.log:" >&2
    tail -n 30 "$BUILD/build.log" >&2
    trap - EXIT
    exit 1
}

# --- Installieren --------------------------------------------------------------
DESKTOP_DEB=$(ls "$BUILD"/tenwin-desktop_*.deb)
GREETER_DEB=$(ls "$BUILD"/tenwin-greeter_*.deb)

if [ "$GREETER" = ask ]; then
    echo
    echo "Tenwin kann zusätzlich einen Anmeldebildschirm im Stil von Windows 10 einrichten."
    echo "Dafür wird der Anmeldemanager von GDM auf LightDM umgestellt (betrifft alle Benutzer)."
    if ask "Anmeldebildschirm im Win10-Stil einrichten?" j; then GREETER=yes; else GREETER=no; fi
fi

say "Installiere tenwin-desktop …"
$SUDO apt-get install -y "$DESKTOP_DEB"

if [ "$GREETER" = yes ]; then
    say "Installiere tenwin-greeter und LightDM …"
    $SUDO apt-get install -y "$GREETER_DEB"
    current=$(cat /etc/X11/default-display-manager 2>/dev/null || true)
    case "$current" in
        */lightdm) say "LightDM ist bereits der Anmeldemanager." ;;
        *)
            [ -n "$current" ] && echo "$current" | $SUDO tee /var/lib/tenwin-previous-display-manager >/dev/null
            say "Stelle den Anmeldemanager auf LightDM um …"
            echo "lightdm shared/default-x-display-manager select lightdm" | $SUDO debconf-set-selections
            $SUDO env DEBIAN_FRONTEND=noninteractive dpkg-reconfigure lightdm
            ;;
    esac
fi

echo
say "Fertig!"
echo "  • Melden Sie sich ab und wählen Sie im Anmeldebildschirm die Sitzung \"Tenwin\"."
if [ "$GREETER" = yes ]; then
    echo "  • Der neue Anmeldebildschirm erscheint nach einem Neustart."
fi
echo "  • Ausprobieren ohne Abmelden (in einem Fenster): $ROOT/tools/dev-session.sh"
echo "  • Entfernen: $ROOT/uninstall.sh"
