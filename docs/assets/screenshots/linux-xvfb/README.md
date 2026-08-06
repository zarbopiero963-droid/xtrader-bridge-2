# Screenshot dell'app BetRelay — IT / EN / ES

Screenshot **reali** della GUI catturati con la pipeline descritta in
[`tools/screenshots/README.md`](../../../../tools/screenshots/README.md), usando la **config
d'esempio** delle guide: token **fittizio**, chat `-1001234567890`, percorso
`C:\XTrader\segnali.csv`. Nessun dato reale.

> ⚠️ **Da rigenerare (#232).** Il default del programma è passato a
> `C:\BetRelay\segnali.csv`, e la finestra si intitola ora **BetRelay** con header
> **«📡 BetRelay»**. Queste immagini sono **precedenti** al rebrand: mostrano ancora il
> percorso e il nome vecchi. Il testo delle guide è già aggiornato, quindi **finché non
> si rigenerano, testo e immagini non concordano** — un utente nuovo potrebbe copiare
> dalla schermata un percorso diverso da quello che il programma gli propone.
>
> La descrizione qui sopra **non** è stata aggiornata di proposito: deve dire cosa le
> immagini mostrano *davvero*, non cosa vorremmo mostrassero.

### Perché non sono ancora rigenerate — due ostacoli misurati, non ipotizzati

Tentata la rigenerazione con la pipeline documentata (Xvfb + `shoot.sh`). La pipeline **ora
funziona** — il difetto che la bloccava del tutto è corretto, vedi sotto — ma le immagini
prodotte **non sono utilizzabili in una guida**, per due ragioni distinte:

1. **La fascia rossa della licenza.** Su una macchina senza licenza attiva l'app mostra in
   cima `🔒 Licenza non valida: bridge bloccato` e il pulsante **AVVIA disabilitato**. Ogni
   scatto porterebbe quel banner: una schermata di **errore** dentro una guida che spiega
   l'uso normale. Le immagini attuali sono precedenti al sistema di licenze e infatti non ce
   l'hanno. Serve un ambiente **con licenza attiva** — non è una cosa che si aggira scrivendo
   codice: la firma Ed25519 è area dichiarata sana dall'audit, e fabbricare una licenza per
   fare una foto è esattamente ciò che non si fa.

2. **Le coordinate dei click sono stantie.** `shoot.sh` clicca le tab a coordinate fisse,
   calibrate quando la tabview aveva **quattro** schede (Generale · Riconoscimento · Sicurezza
   · Conferme XTrader). Oggi ce n'è una quinta, **Licenza**, e il banner sposta tutto in basso
   di ~33 px: i click cadono a vuoto e si ottengono **tre copie della stessa schermata**
   (verificato: tre file identici, 55 132 byte l'uno). Le coordinate vanno ri-misurate
   **nell'ambiente in cui si scatta**, perché con e senza licenza il layout differisce.

Finché entrambi non sono risolti, rigenerare produrrebbe immagini **peggiori** di queste:
sbagliate sul nome, e per giunta in stato d'errore.

Servono alle **tre sezioni per software** del sito — *BetRelay per XTrader* (IT), *for
BETTINGTOOLKIT.COM* (EN), *para BETTINGTOOLKIT.ES / .LAT* (ES) — secondo la regola in
[`docs/policy_lingue_sito.md`](../../../policy_lingue_sito.md): **il testo si traduce in tutte le
lingue del sito, gli screenshot esistono solo in IT/EN/ES e per ogni altra lingua si usano quelli
in inglese**.

| File | Schermata | Lingue |
|---|---|---|
| `<lang>/main-01-generale.png` | Finestra principale, tab ⚙️ Generale coi dati d'esempio | it · en · es |
| `<lang>/main-02-sicurezza.png` | Tab 🛡️ Sicurezza (modalità bridge, limiti, coda) | it · en · es |
| `<lang>/main-03-salute.png` | Tab 🚦 Salute (7 semafori) | it · en · es |
| `it/wizard-step1.png` | 🧙 Wizard, step 1/5 — Token del bot | it |
| `it/wizard-step2.png` | 🧙 Wizard, step 2/5 — Chat sorgente, con esito ✅ | it |

**Sono catture Linux, non Windows**: font e chrome di sistema differiscono (es. il pulsante
«📁 Sfoglia…» può risultare tagliato per via della larghezza fissa della finestra). Vanno
benissimo per guide e sito; per il pixel-perfect Windows restano preferibili le catture native,
da mettere nella cartella superiore `docs/assets/screenshots/`.

---

## ⚠️ Cosa mostrano davvero: la localizzazione EN/ES è incompleta

Le versioni inglese e spagnola **non sono interamente tradotte**. Gli screenshot sono fedeli: è
l'app a essere così oggi. Non vanno ritoccati né nascosti — vanno usati sapendolo, e le lacune
vanno chiuse nel codice.

| Cosa resta in italiano | Dove si vede | Impatto |
|---|---|---|
| **`Righe attive: N/M`** | header, **sempre a schermo** | alto: è fra le prime cose che un utente EN/ES legge |
| **Selettore «Modalità bridge»** — `🧪 Simulazione Bridge — NON scrive il CSV operativo`, `🔬 Collaudo XTrader…`, `⚠️ Reale…` | tab Sicurezza / Safety / Seguridad | **il più grave**: è il controllo che decide se il CSV operativo viene scritto |
| **Tutti e 7 i semafori** della tab Salute | tab Health / Salud | alto: è il pannello diagnostico, quello che si guarda quando qualcosa non va |
| **`Il bridge ascolterà queste N chat:`** | tab Chat monitorate | medio |

Origine nel codice — nessuna di queste stringhe passa da `i18n`:

- `xtrader_bridge/multi_signal.py` → `active_count_text()`
- `xtrader_bridge/bridge_mode.py` → `LABELS`
- `xtrader_bridge/health_check.py` → etichette e dettagli degli item
- `xtrader_bridge/app.py` → riga delle chat monitorate

Non rientrano fra le stringhe dichiarate «italiane per contratto» nella issue #3 (messaggi di
dominio, log di debug, dialog di istanza singola): sono **lacune vere**.

---

## Come rigenerarli

```bash
Xvfb :99 -screen 0 1280x1024x24 &
bash tools/screenshots/shoot.sh it 394 93 260 482
bash tools/screenshots/shoot.sh en 366 93 273 482
bash tools/screenshots/shoot.sh es 366 93 278 482
```

I quattro numeri sono le coordinate delle due tab da cliccare (prima Sicurezza, poi Salute).
**Cambiano da lingua a lingua**: le etichette tradotte hanno larghezze diverse e spostano il
layout. Con le coordinate italiane, in spagnolo il click finisce sul pulsante «Asistente de
primera configuración» e apre il Wizard invece della tab — è successo davvero generando questi
file, e per questo lo script prende le coordinate come parametri invece di fissarle.

Altre trappole già incontrate (tkinter, cryptography, tema chiaro, PYTHONPATH) stanno in
`tools/screenshots/README.md`.

## Il Wizard

`it/wizard-step1.png` e `it/wizard-step2.png` sono generati da
[`tools/screenshots/wizard_shot.py`](../../../../tools/screenshots/wizard_shot.py), che istanzia la
vista reale e la porta direttamente allo step voluto.

**Nessun token reale, mai.** Lo script esiste proprio per *non* averne bisogno: cliccando, il
Wizard blocca «Avanti ▶» finché la verifica dello step non è ✅, e quelle verifiche
chiamerebbero Telegram (`getMe`, `getUpdates`) con un token vero — che su una macchina di
documentazione non c'è e non deve esserci. Lo script salta quel percorso impostando lo step
direttamente sulla vista, esattamente come fa un test: i widget e i testi a schermo sono quelli
veri, i dati dentro sono quelli **fittizi** delle guide (token `123456789:AAExempio-…`, chat
`-1001234567890`). Le versioni EN/ES si generano con lo stesso script — e con lo stesso token
finto — passando `--lang en` / `--lang es`.
