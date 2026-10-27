#!/bin/sh
# Run a command inside a headless labwc (pixman renderer) for screenshots and
# smoke tests, using a throw-away home directory.
#
#   tools/headless.sh [-a] [-t SECONDS] [-s WIDTHxHEIGHT] 'shell commands'
#
# -a starts the real session components (labwc autostart).
#
# The commands run inside the compositor; use grim to take screenshots.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TIMEOUT=20
SIZE=1366x768
AUTOSTART=0
while getopts "t:s:a" opt; do
    case $opt in
        t) TIMEOUT=$OPTARG ;;
        s) SIZE=$OPTARG ;;
        a) AUTOSTART=1 ;;
        *) exit 2 ;;
    esac
done
shift $((OPTIND - 1))

TEST_HOME=${TENWIN_TEST_HOME:-${TMPDIR:-/tmp}/tenwin-test-home}
mkdir -p "$TEST_HOME/.local/share/fonts" "$TEST_HOME/.local/share/themes" "$TEST_HOME/.config"
cp -u "$ROOT"/data/fonts/*.ttf "$TEST_HOME/.local/share/fonts/"
rm -rf "$TEST_HOME/.local/share/themes/Tenwin" "$TEST_HOME/.local/share/themes/Tenwin-Dark"
cp -r "$ROOT/data/themes/Tenwin" "$ROOT/data/themes/Tenwin-Dark" "$TEST_HOME/.local/share/themes/"
mkdir -p "$TEST_HOME/.local/share/icons"
ln -sfn "$ROOT/data/icons/hicolor" "$TEST_HOME/.local/share/icons/hicolor"

export HOME="$TEST_HOME"
export XDG_CONFIG_HOME="$TEST_HOME/.config"
export XDG_DATA_HOME="$TEST_HOME/.local/share"
export XDG_CACHE_HOME="$TEST_HOME/.cache"
export XDG_STATE_HOME="$TEST_HOME/.local/state"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-$TEST_HOME/runtime}"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
export PATH="$ROOT/bin:$ROOT/build/helpers:$PATH"
export XDG_CURRENT_DESKTOP=Tenwin:wlroots
export TENWIN_NESTED=1
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1
export WLR_HEADLESS_OUTPUTS=1
export GDK_BACKEND=wayland
export NO_AT_BRIDGE=1
fc-cache -f "$TEST_HOME/.local/share/fonts" >/dev/null 2>&1 || true

CONFIG_DIR=$("$ROOT/bin/tenwin-python" -m tenwin.session prepare | tail -n 1)
# Without -a the session components are not started automatically.
[ "$AUTOSTART" = 1 ] || printf '#!/bin/sh\n' > "$CONFIG_DIR/autostart"
INNER=$(mktemp)
cat > "$INNER" <<EOF
#!/bin/sh
wlr-randr --output HEADLESS-1 --custom-mode $SIZE >/dev/null 2>&1 || true
$*
EOF
chmod +x "$INNER"
if command -v dbus-run-session >/dev/null 2>&1; then
    timeout "$TIMEOUT" dbus-run-session -- labwc -C "$CONFIG_DIR" -s "$INNER" || true
else
    timeout "$TIMEOUT" labwc -C "$CONFIG_DIR" -s "$INNER" || true
fi
rm -f "$INNER"
