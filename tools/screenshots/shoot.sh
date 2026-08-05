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
# Tre cose che questo script fa apposta (rilievi CodeRabbit sulla #277):
#  1. **non tocca la config in modo distruttivo**: ne fa una copia, scrive la versione
#     modificata su un file temporaneo nella STESSA cartella e la sostituisce in modo
#     atomico; al termine — anche in caso di errore — l'originale viene rimesso. La
#     config di chi lancia lo script è quella vera dell'app: cambiargli la lingua per
#     sempre, o lasciargliela a metà dopo un'interruzione, non è accettabile.
#  2. **usa una cartella temporanea privata** (`mktemp -d`, `umask 077`) invece di
#     percorsi prevedibili sotto /tmp, che chiunque sulla macchina può pre-creare come
#     symlink verso un altro file.
#  3. **possiede solo il proprio processo**: il PID è quello di questa invocazione, e un
#     `trap` lo chiude su EXIT/INT/TERM. Prima, se la ricerca della finestra falliva,
#     `main.py` restava vivo; e il PID veniva letto da un file condiviso, quindi due run
#     in parallelo si sarebbero uccisi a vicenda.
#
# NB: niente `pkill -f "python3 main.py"` — quel pattern matcherebbe anche la shell che
# lancia lo script e la ucciderebbe.
set -euo pipefail

L="${1:?lingua mancante}"; SX="${2:?}"; SY="${3:?}"; HX="${4:?}"; HY="${5:?}"
OUT="docs/assets/screenshots/linux-xvfb/$L"; mkdir -p "$OUT"

CFG="$HOME/.config/XTraderBridge/config.json"
LOCK="$HOME/.config/XTraderBridge/XTraderBridge.lock"

umask 077
RUNDIR="$(mktemp -d)"
APP_PID=""

pulisci () {
  local esito=$?
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true
  # La config torna com'era: la lingua la cambiamo per lo scatto, non per sempre. Il
  # ripristino è atomico esattamente come la scrittura — `cp` diretto su "$CFG" tronca il
  # file prima di riempirlo, quindi un'interruzione QUI lascerebbe la config a metà: lo
  # stesso guasto che stiamo cercando di evitare, nel codice che dovrebbe rimediarvi.
  # E niente `|| true` sul risultato: un ripristino fallito va detto, non ingoiato.
  if [ -f "$RUNDIR/config.orig.json" ]; then
    ripristino="$(mktemp "${CFG}.restore.XXXXXX")"
    if cp -p "$RUNDIR/config.orig.json" "$ripristino" && mv -f "$ripristino" "$CFG"; then
      :
    else
      rm -f "$ripristino"
      echo "ATTENZIONE: non sono riuscito a ripristinare $CFG" >&2
      echo "La copia intatta è in: $RUNDIR/config.orig.json (NON cancello la cartella)" >&2
      return "$esito"
    fi
  fi
  rm -rf "$RUNDIR"
  return $esito
}
trap pulisci EXIT INT TERM

if [ -e "$LOCK" ]; then
  echo "Lock presente: $LOCK" >&2
  echo "Se nessuna istanza dell'app è in esecuzione è un residuo: rimuovilo a mano." >&2
  echo "(Questo script non lo cancella: potrebbe essere di un'altra istanza viva.)" >&2
  exit 1
fi

cp -p "$CFG" "$RUNDIR/config.orig.json"
python3 - "$L" "$CFG" <<'PY'
import json, os, pathlib, sys, tempfile
lingua, percorso = sys.argv[1], sys.argv[2]
p = pathlib.Path(percorso)
cfg = json.loads(p.read_text(encoding="utf-8"))
cfg["app_language"] = lingua
# temporaneo nella STESSA cartella + replace: se il processo muore a metà, il file
# originale è ancora integro. Scrivere direttamente su `p` lo troncherebbe prima.
fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".config-", suffix=".json")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
except BaseException:
    os.unlink(tmp)
    raise
PY

DISPLAY=:99 python3 main.py > "$RUNDIR/app.log" 2>&1 &
APP_PID=$!
sleep 14

W="$(DISPLAY=:99 xdotool search --name "Signal Bridge" | tail -1)"
if [ -z "$W" ]; then
  echo "Finestra «Signal Bridge» non trovata. Ultime righe del log:" >&2
  tail -20 "$RUNDIR/app.log" >&2
  exit 1
fi

# Niente `eval` sull'output di xdotool: si legge riga per riga e si valida che siano
# numeri. `eval` rieseguirebbe come codice di shell qualunque cosa arrivi da fuori.
geometria () {
  DISPLAY=:99 xdotool getwindowgeometry --shell "$W" \
    | sed -n "s/^$1=\([0-9]\{1,\}\)\$/\1/p" | head -1
}
X="$(geometria X)"; Y="$(geometria Y)"
WIDTH="$(geometria WIDTH)"; HEIGHT="$(geometria HEIGHT)"
for v in "$X" "$Y" "$WIDTH" "$HEIGHT"; do
  [ -n "$v" ] || { echo "geometria della finestra non leggibile" >&2; exit 1; }
done

grab () {
  DISPLAY=:99 import -window root "$RUNDIR/root.png"
  python3 - "$OUT/$1" "$X" "$Y" "$WIDTH" "$HEIGHT" "$RUNDIR/root.png" <<'PY'
from PIL import Image; import sys
d = sys.argv[1]; x, y, w, h = map(int, sys.argv[2:6]); sorgente = sys.argv[6]
Image.open(sorgente).crop((x, y, x + w, y + h)).save(d)
PY
}

grab "main-01-generale.png"
DISPLAY=:99 xdotool mousemove $((X+SX)) $((Y+SY)) click 1; sleep 2; grab "main-02-sicurezza.png"
DISPLAY=:99 xdotool mousemove $((X+HX)) $((Y+HY)) click 1; sleep 2; grab "main-03-salute.png"

echo "OK $L (${WIDTH}x${HEIGHT})"
