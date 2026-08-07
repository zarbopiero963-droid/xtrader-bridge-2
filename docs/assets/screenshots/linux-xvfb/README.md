# Screenshot dell'app BetRelay — IT / EN / ES

Screenshot **reali** della GUI catturati con la pipeline descritta in
[`tools/screenshots/README.md`](../../../../tools/screenshots/README.md), usando la **config
d'esempio** delle guide: token **fittizio**, chat `-1001234567890`, percorso
`C:\BetRelay\segnali.csv`. Nessun dato reale.

Rigenerate il **7 agosto 2026** sul `main` post-#301: mostrano il nome nuovo — finestra
**BetRelay**, header **«📡 BetRelay»** — e il percorso di default `C:\BetRelay\segnali.csv`.
Testo delle guide e immagini tornano a concordare.

## Come sono state ottenute — i due ostacoli, e come sono stati tolti

Fino al 7 agosto queste immagini erano **bloccate** da due ostacoli misurati. Entrambi sono
risolti, e vale la pena sapere come, perché torneranno a presentarsi.

**① La fascia rossa della licenza.** Senza licenza attiva l'app mostra in cima
`🔒 Licenza non valida: bridge bloccato` col pulsante **AVVIA disabilitato**: ogni scatto
porterebbe una schermata d'**errore** dentro una guida che spiega l'uso normale.

Risolto con
[`app_con_licenza_di_prova.py`](../../../../tools/screenshots/app_con_licenza_di_prova.py), che
emette una licenza col seed di **test già presente** in `tests/conftest.py` e poi esegue lo
stesso `main.py`. **Nessuna chiave nuova viene generata e nessuna riga del licensing di
produzione è toccata**: la chiave pubblica *deployata* viene sostituita solo dentro quel
processo, come fa la fixture dei test. Autorizzazione esplicita del proprietario, 6 agosto 2026,
entro quei limiti — la firma Ed25519 resta area dichiarata sana dall'audit, e non è stata
modificata.

Il launcher **non distrugge una licenza reale**: se ne trova una la sposta in
`license_state.json.pre-screenshot` e la rimette a posto in uscita; se quel salvataggio esiste
già si **ferma**, perché dentro potrebbe esserci la licenza vera di una corsa interrotta.

**② Le coordinate dei click erano stantie**, e per due motivi insieme: calibrate quando la
tabview aveva **quattro** schede — oggi ce n'è una quinta, **Licenza** — e su un layout in cui
la fascia rossa spostava tutto di ~33 px. Ri-misurate: vedi «Come rigenerarli». Con la licenza
di prova la fascia non c'è, quindi esiste **una sola** condizione di layout invece di due.

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

**Elenco ri-verificato il 7 agosto 2026 guardando le immagini nuove**, non ereditato: da quando
era stato scritto, parecchie lacune sono state chiuse. Resta italiano:

| Cosa resta in italiano | Dove si vede | Impatto |
|---|---|---|
| **Valore del selettore «Modalità bridge»** — `🧪 Simulazione Bridge — NON scrive il CSV operativo` | tab Safety / Seguridad, riga in cima | **il più grave**: è il controllo che decide se il CSV operativo viene scritto. Nota: la *stessa* modalità, nel semaforo della tab Salute, è invece tradotta — quindi l'app dice la stessa cosa in due lingue diverse nella stessa schermata |
| **Scheda `Licenza`** | quinta tab, in EN e ES | medio: l'etichetta non è tradotta né in inglese né in spagnolo |
| **Dettaglio del semaforo CSV** — `il file verrà creato (cartella scrivibile)` | tab Health / Salud | medio: l'etichetta è tradotta, il dettaglio no |
| **Dettaglio del semaforo Dizionari** — `nessun conflitto su profili in uso` | tab Health / Salud | medio, stesso difetto |

**Già chiuse** (erano in questo elenco e non ci sono più): `Righe attive: N/M` → *Active rows* /
*Filas activas*; la riga delle chat monitorate → *The bridge will listen to these…* / *El bridge
escuchará estos…*; le **etichette** dei semafori della tab Salute, ora tradotte tutte e sette.

Origine nel codice delle lacune rimaste:

- `xtrader_bridge/bridge_mode.py` → `LABELS` (il valore del selettore)
- `xtrader_bridge/health_check.py` → i **dettagli** di alcuni item (le etichette passano già da `i18n`)
- **scheda Licenza**: il codice è a posto — `xtrader_bridge/app.py:1821` fa già
  `tabs.add(i18n.tr("🔑 Licenza"))`. Manca la **chiave** `"🔑 Licenza"` nei dizionari `en` e `es`
  di `xtrader_bridge/i18n.py`, che invece hanno `"🛡️ Sicurezza"` e `"🚦 Salute"`; senza voce,
  `tr()` restituisce l'originale italiano. È l'unica delle tre lacune che si chiude aggiungendo
  due righe di traduzione invece che toccando la logica.

Non rientrano fra le stringhe dichiarate «italiane per contratto» nella issue #3 (messaggi di
dominio, log di debug, dialog di istanza singola): sono **lacune vere**.

---

## Come rigenerarli

```bash
Xvfb :99 -screen 0 1280x1024x24 &
bash tools/screenshots/shoot.sh it 356 93 268 482
bash tools/screenshots/shoot.sh en 311 93 272 482
bash tools/screenshots/shoot.sh es 318 93 279 482
```

I quattro numeri sono le coordinate delle due tab da cliccare (prima Sicurezza, poi Salute).
**Cambiano da lingua a lingua**: le etichette tradotte hanno larghezze diverse e spostano il
layout. Con le coordinate italiane, in spagnolo il click finisce sul pulsante «Asistente de
primera configuración» e apre il Wizard invece della tab — è successo davvero generando questi
file, e per questo lo script prende le coordinate come parametri invece di fissarle.

**Le terne qui sopra sono state ri-misurate il 7 agosto 2026** su finestra 720×760. Le
precedenti (`it 394 93 260 482`) erano stantie per **due** motivi insieme: calibrate quando la
tabview di configurazione aveva quattro schede — oggi ce n'è una quinta, «Licenza» — e su un
layout in cui la fascia rossa «bridge bloccato» spostava tutto di ~33 px. Con la licenza di
prova quella fascia non c'è, quindi esiste **una sola** condizione di layout invece di due.

> ⚠️ **Guarda le immagini, non l'esito dello script.** Con coordinate sbagliate i click cadono a
> vuoto e si ottengono **tre copie della stessa schermata** — misurato: tre file identici da
> 55 132 byte l'uno — mentre `shoot.sh` stampa comunque `OK`. Dopo ogni rigenerazione va
> verificato che le tre immagini siano davvero diverse fra loro e che mostrino Generale,
> Sicurezza e Salute.

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
