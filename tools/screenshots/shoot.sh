#!/bin/bash
# Cattura le tre schermate principali dell'app in una lingua.
#
#   shoot.sh <lingua> <x_tab_sicurezza> <y_tab_sicurezza> <x_tab_salute> <y_tab_salute>
#
# Le coordinate sono PARAMETRI e non costanti perché le etichette tradotte hanno
# larghezze diverse e spostano il layout: con quelle italiane, in spagnolo il click
# finisce sul pulsante «Asistente de primera configuración» e apre il Wizard invece
# della tab. Valori verificati:
#   it  394 93 260 482
#   en  366 93 273 482
#   es  366 93 278 482
#
# Prerequisiti: Xvfb :99 attivo, deps di tools/screenshots/README.md, lanciato dalla
# radice del repo. Il token nella config d'esempio è FITTIZIO: l'app non si connette.
#
# NB: niente `pkill -f "python3 main.py"` — quel pattern matcherebbe anche la shell
# che lancia lo script e la ucciderebbe. Si tiene il PID.
set -e
L="$1"; SX="$2"; SY="$3"; HX="$4"; HY="$5"
OUT="docs/assets/screenshots/linux-xvfb/$L"; mkdir -p "$OUT"

python3 - "$L" <<'PY'
import json, os, pathlib, sys
p = pathlib.Path(os.path.expanduser("~/.config/XTraderBridge/config.json"))
cfg = json.loads(p.read_text(encoding="utf-8")); cfg["app_language"] = sys.argv[1]
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
PY

rm -f "$HOME/.config/XTraderBridge/XTraderBridge.lock"
[ -f /tmp/app.pid ] && kill "$(cat /tmp/app.pid)" 2>/dev/null || true
sleep 1
DISPLAY=:99 python3 main.py > "/tmp/app_$L.log" 2>&1 &
echo $! > /tmp/app.pid
sleep 14

W=$(DISPLAY=:99 xdotool search --name "Signal Bridge" | tail -1)
eval $(DISPLAY=:99 xdotool getwindowgeometry --shell "$W")

grab () {
  DISPLAY=:99 import -window root /tmp/root.png
  python3 - "$OUT/$1" "$X" "$Y" "$WIDTH" "$HEIGHT" <<'PY'
from PIL import Image; import sys
d = sys.argv[1]; x, y, w, h = map(int, sys.argv[2:6])
Image.open("/tmp/root.png").crop((x, y, x + w, y + h)).save(d)
PY
}

grab "main-01-generale.png"
DISPLAY=:99 xdotool mousemove $((X+SX)) $((Y+SY)) click 1; sleep 2; grab "main-02-sicurezza.png"
DISPLAY=:99 xdotool mousemove $((X+HX)) $((Y+HY)) click 1; sleep 2; grab "main-03-salute.png"

kill "$(cat /tmp/app.pid)" 2>/dev/null || true; sleep 1
echo "OK $L (${WIDTH}x${HEIGHT})"
