# Screenshot automatici dell'app (Linux + Xvfb)

Ricetta **verificata in sessione** per generare screenshot **reali** della GUI senza
Windows e senza toccare l'app: serve per le guide utente e per il sito, ed è
rigenerabile a ogni cambio di interfaccia (nelle tre lingue).

> Gli screenshot **pixel-perfect per Windows** restano quelli catturati su Windows
> reale (font e chrome di sistema sono diversi). Questa pipeline serve a non restare
> mai senza screenshot aggiornati e a fare da audit visivo della localizzazione.

## 1. Dipendenze

```bash
apt-get install -y python3.11-tk x11-apps imagemagick xdotool   # tk = versione di Python ATTIVA
pip install -r requirements.txt
pip install --upgrade cryptography cffi   # evita il crash pyo3/_cffi_backend con python-telegram-bot
```

## 2. Config d'esempio (mai dati reali)

L'app legge la config utente da `~/.config/XTraderBridge/config.json` (fuori Windows).
Seminala con i valori d'esempio usati in tutte le guide:

```json
{
  "app_language": "it",
  "bot_token": "123456789:AAExempio-Token-NON-Reale-0000",
  "chat_id": "-1001234567890",
  "csv_path": "C:\\XTrader\\segnali.csv",
  "clear_delay": 90,
  "provider": "TelegramBot",
  "dry_run": true
}
```

Il token è **fittizio**: l'app non si connette (il listener non viene mai avviato) e la
GUI lo mostra comunque mascherato a pallini. Cambiando `app_language` in `en`/`es` si
ottengono gli screenshot nelle altre lingue.

## 3. Finestra principale

```bash
Xvfb :99 -screen 0 1280x1024x24 &
DISPLAY=:99 python3 main.py &
sleep 12                                   # attesa costruzione finestra

# cambio scheda (coordinate della finestra a 720x760, angolo in alto a sinistra)
DISPLAY=:99 xdotool mousemove 394 93  click 1   # tab 🛡️ Sicurezza
DISPLAY=:99 xdotool mousemove 267 430 click 1   # tab 🚦 Salute

DISPLAY=:99 import -window root /tmp/root.png
python3 - <<'PY'
from PIL import Image
Image.open("/tmp/root.png").crop((0, 0, 730, 780)).save("shot.png")
PY
```

## 4. Finestre secondarie (Wizard)

Il Wizard blocca «Avanti ▶» finché la verifica dello step non è ✅ e quelle verifiche
chiamano Telegram: gli step oltre il primo **non** sono raggiungibili a click senza un
token vero. Si usa quindi l'harness che istanzia la vista reale:

```bash
DISPLAY=:99 PYTHONPATH=. python3 tools/screenshots/wizard_shot.py --step 2 --lang it &
sleep 5
W=$(DISPLAY=:99 xdotool search --name "Wizard" | head -1)
eval $(DISPLAY=:99 xdotool getwindowgeometry --shell $W)
DISPLAY=:99 import -window root /tmp/root.png
python3 - <<PY
from PIL import Image
Image.open("/tmp/root.png").crop(($X, $Y, $X+$WIDTH, $Y+$HEIGHT)).save("wizard-step2.png")
PY
```

## 5. Trappole già incontrate (e risolte)

| Sintomo | Causa | Rimedio |
|---|---|---|
| `ModuleNotFoundError: tkinter` | installato `python3-tk` per la versione **di sistema**, non per quella attiva | `apt-get install python3.11-tk` (o la versione in uso) |
| Crash `pyo3_runtime.PanicException` / `_cffi_backend` | `cryptography` di Debian in conflitto con `python-telegram-bot` | `pip install --upgrade cryptography cffi` |
| Finestra del Wizard in **tema chiaro** | l'harness non è l'app: il tema va impostato a mano | `ctk.set_appearance_mode("dark")` (già dentro `wizard_shot.py`) |
| `ModuleNotFoundError: xtrader_bridge` | script lanciato fuori dalla radice del repo | `PYTHONPATH=.` |
| PNG **vuoti** a 16/32 px (rendering HTML) | Chromium headless non scende sotto una dimensione minima di finestra | renderizzare grande e ridurre con Pillow/LANCZOS |
| Il pulsante «📁 Sfoglia…» esce dal bordo | font Linux più larghi, finestra a larghezza fissa 720px | catturare la finestra (non `root`) o accettarlo: è un artefatto Linux |

## 6. Cosa NON committare

Screenshot con **dati reali**: token, chat ID veri, nomi canale, link d'invito
`t.me/…`, foto profilo. Se un'immagine reale serve, i campi vanno **riscritti con i
valori d'esempio** prima di salvarla nel repo (vedi `website/static/img/guida/`).
