#!/bin/sh
# Headless smoke test: starts the whole session in a headless labwc, opens the
# main UIs and writes screenshots to build/screenshots/. Fails if a component
# logged a Python traceback.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/build/screenshots"
mkdir -p "$OUT"
export TENWIN_TEST_HOME="${TMPDIR:-/tmp}/tenwin-smoke-home"
rm -rf "$TENWIN_TEST_HOME"
mkdir -p "$TENWIN_TEST_HOME/Desktop" "$TENWIN_TEST_HOME/Documents"
echo "Tenwin" > "$TENWIN_TEST_HOME/Desktop/Readme.txt"
mkdir -p "$TENWIN_TEST_HOME/.config/tenwin"
echo '{"session.first_run_done": true}' > "$TENWIN_TEST_HOME/.config/tenwin/settings.json"

"$ROOT/tools/headless.sh" -a -t 60 "
sleep 8
grim '$OUT/01-desktop.png'
tenwin-ctl start-menu; sleep 1.5; grim '$OUT/02-start.png'; tenwin-ctl start-menu
tenwin-ctl search; sleep 1; grim '$OUT/03-search.png'; tenwin-ctl search
tenwin-ctl action-center; sleep 1; grim '$OUT/04-action-center.png'; tenwin-ctl action-center
tenwin-explorer & sleep 4; grim '$OUT/05-explorer.png'
tenwin-settings & sleep 4; grim '$OUT/06-settings.png'
tenwin-ctl task-view; sleep 1; grim '$OUT/07-task-view.png'; tenwin-ctl task-view
tenwin-lock --image '$ROOT/data/wallpapers/tenwin-hero.svg' & LOCK=\$!; sleep 3; grim '$OUT/08-lock.png'; kill \$LOCK
"

status=0
for log in "$TENWIN_TEST_HOME"/.cache/tenwin/*.log; do
    if grep -q "Traceback" "$log"; then
        echo "Traceback in $log:" >&2
        grep -A12 "Traceback" "$log" >&2
        status=1
    fi
done
count=$(ls "$OUT"/*.png 2>/dev/null | wc -l)
echo "$count screenshots in $OUT"
[ "$count" -ge 8 ] || status=1
exit $status
