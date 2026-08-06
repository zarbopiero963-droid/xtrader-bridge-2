# Checklist di release — BetRelay

> PR-20 (PHASE 9). Passi da eseguire **prima** di distribuire una versione. Il merge
> e la pubblicazione restano **manuali del proprietario**. Spunta ogni voce solo dopo
> averla verificata davvero.

## A. Pre-requisiti (ambiente di sviluppo)

- [ ] Branch pulito, allineato a `main`, nessun file fuori scope.
- [ ] Nessun segreto nello staging: niente `config.json` reale, token, chat ID reali,
      `.env`, CSV generati, log, EXE/ZIP (vedi `.gitignore`).

## B. Test automatici (offline)

- [ ] `python -m py_compile main.py` → OK.
- [ ] `python -m pytest -m "not manual"` → tutti verdi (atteso: 536 passed, 2 skipped
      o più, mai fallimenti).
- [ ] **La suite è offline** — nessun test apre una connessione di rete vera (#211 R1).
      Due gate in `tests/safety/test_stub_fedeli_211.py`: gli stub dei test devono
      rispettare la firma del metodo vero, e chi esegue `App._run_bot` deve sostituire
      `ApplicationBuilder`. Senza, il risultato dipende da COME la rete fallisce — token
      rifiutato (permanente) → verde; rete assente (`NetworkError` transitorio) → il
      supervisor entra nel backoff e il test si appende. Controllo diretto, se serve
      rifarlo a mano: rieseguire la suite con `socket.socket.connect` sostituito da un
      tripwire che solleva — atteso **zero** connessioni tentate.
- [ ] Il job CI `contract` è verde (contratto CSV a 14 colonne invariato).
- [ ] Tutti i check della PR sono **completati e verdi** prima del merge.

## C. Versione e changelog

- [ ] `xtrader_bridge.__version__` aggiornato secondo semver (oggi `0.1.0`).
- [ ] Il titolo della GUI mostra la versione corretta.
- [ ] README allineato al comportamento reale e al workflow (`build.yaml`).

## D. Build EXE Windows (manuale / CI Windows)

> Non eseguibile in ambiente headless. Eseguire su Windows o tramite il workflow
> `build.yaml`, che parte **manualmente** (Actions → «Run workflow») o su **tag `v*`**
> (non più a ogni push su `main`, per non consumare la quota storage artifact).

- [ ] Il workflow `build.yaml` completa senza errori.
- [ ] L'artifact versionato `BetRelay-Windows-v<versione>-<data>.zip`
      è presente e scaricabile.
- [ ] L'EXE interno si chiama `BetRelay.exe` (nome stabile).
- [ ] L'EXE si avvia su Windows 10/11 senza terminale nero (`--windowed`).
- [ ] L'EXE **non** contiene token o config personali.
- [ ] L'EXE salva la config in `%APPDATA%\XTraderBridge\` e la ricarica al riavvio.
- [ ] L'EXE scrive il CSV nel percorso configurato.

## E. Sicurezza

- [ ] Tutte le GitHub Action nei workflow sono fissate a SHA (test di enforcement verde).
- [ ] Nessun token Telegram compare nei log (redazione attiva).
- [ ] Nessun token **GitHub** compare nei log del License Manager. Tre livelli: `redact_secrets`
      ne conosce le shape, il valore vivo è registrato alla **lettura** dal keyring, e i logger
      del package redigono messaggio **e** traceback. I due lati della barriera — scanner dei
      commit e redattore dei log — restano allineati da un test, non da un'abitudine.
- [ ] **`chat_id` esplicito configurato** prima dell'uso: senza, il filtro chat ammette
      tutte le chat (vedi `archive/final_audit.md` §4 punto 6). Requisito bloccante per l'uso reale.
- [ ] DRY_RUN (default = simulazione) **agganciato al runtime (PR-21)**: verifica che in
      DRY_RUN il CSV operativo NON venga scritto (log "🧪 DRY_RUN"). Per l'uso reale,
      disattivarlo consapevolmente.
- [ ] **Attive a runtime (PR-21):** anti-duplicato + limite/minuto (`signal_dedupe`,
      stato persistito) e limite/giorno (`safety_guard`, `max_per_day`). Verifica i log
      "♻️ Duplicato"/"🚦 Limite ...".
- [ ] **Protezioni NON ancora attive a runtime** (da agganciare prima dell'uso reale):
      coda multi-segnale (`signal_queue`), conferma XTrader (`confirmation_reader`),
      multi-chat (`source_manager`). Vedi `archive/final_audit.md` §4.
- [ ] **License Manager — «🔍 Verifica accesso» collaudata contro GitHub vero** (#215).
      Metti `Contents` a *Read-only* sul token *fine-grained* → il pulsante deve rispondere
      **403** («senza permesso di SCRITTURA»); rimetti *Read and write* → «✅ Accesso OK».
      Perché è qui e non fra i test automatici: la sonda è provata da 62 test con un HTTP
      **finto**, che non possono dimostrare come si comporta l'API reale. Un «✅ Accesso OK»
      al passo *Read-only* è un **guasto bloccante**: la verifica non proverebbe nulla.
      Passi esatti in `docs/licensing.md` → «Smoke manuale del proprietario».
- [ ] **Il token vede il repository delle revoche** — `zarbopiero963-droid/xtrader-revocation`
      in «Repository access» del token, con **Contents: Read and write**. Senza, la lista
      firmata non si pubblica: una licenza revocata **continua a funzionare** sui bridge già
      distribuiti, che è il guasto peggiore di tutta la catena. Da rifare su ogni PC nuovo:
      il token **non** è nel backup completo (sta solo nel keyring).

- [ ] **Le guide dell'assistente sono leggibili per sezione.** Il job `safety` include il gate
      `test_nessuna_guida_del_repo_ha_un_recinto_APERTO`: se una guida ha un blocco di codice
      aperto e mai chiuso, l'indice che l'assistente costruisce diventa ambiguo. Il test dice
      file e riga; la correzione è chiudere il recinto nel documento, non toccare il parser.

## F. Verifica funzionale manuale (Windows + GUI)

- [ ] App avviabile; START/STOP funzionano; chiusura finestra ferma il bridge.
- [ ] Salvataggio config dalla GUI funziona e persiste.
- [ ] Log leggibile; errori parser/CSV visibili; nessun token mostrato.

### F.1 Scheda «🧩 Parser Personalizzato» — layout e verdetto (PR #249)

Verificato sotto Xvfb su CustomTkinter reale, **non** su Windows: la geometria Tk e il DPI
scaling sono l'unica parte che l'automazione qui non copre. Da rifare a mano al primo avvio
su PC, anche a **125%** e **150%** di scala schermo.

- [ ] **Nessun buco fra le sezioni.** Apri il Parser su un parser **senza** righe multi e
      **senza** condizioni: «Output multi-riga» e «Condizioni di gate» devono essere alte
      quanto i loro controlli (interruttori, pulsanti «➕», hint), non lasciare uno spazio
      vuoto sotto. Prima della #249 ogni contenitore vuoto ne riservava **200px**.
      Atteso: la «Griglia regole — 14 colonne CSV» entra nella stessa schermata.
- [ ] **Il contenitore torna basso quando si svuota.** Aggiungi una riga mercato, poi
      rimuovila col «🗑 Rimuovi». La sezione deve **tornare** alta com'era, non restare alta
      quanto la riga appena tolta. Ripeti con una condizione di gate.
      *(È il caso che il solo `height=0` alla costruzione non copre: l'altezza richiesta
      resta quella dell'ultimo contenuto finché non la si rimette.)*
- [ ] **Le due tabelle di prova nascono ridotte.** Prima di premere «🧪 Prova messaggio» sotto
      le etichette «Anteprima righe generate» e «Diagnostica» non deve esserci un riquadro
      vuoto; compaiono alla prima prova.
- [ ] **Il verdetto nomina la condizione di gate.** Metti una condizione «contiene» con un
      testo che il messaggio di prova **non** ha, poi «🧪 Prova messaggio».
      Atteso: `⛔ Non pronto (CONDITIONS_NOT_MET) · il messaggio è stato letto correttamente,
      ma non soddisfa la condizione di gate «contiene: …»`.
      **Non** deve dire «nessun contenuto estratto dal messaggio»: era il motivo sbagliato,
      e mandava a controllare i delimitatori invece della condizione.
- [ ] **L'interruttore multi a vuoto si vede nel verdetto.** Accendi MultiMarket senza
      aggiungere righe e prova un messaggio valido. Atteso: `✅ Pronto · … · ⚠ MultiMarket è
      attivo ma nessuna riga mercato è abilitata: nessuna riga extra verrà generata.`
      Resta un **avviso**: il verdetto non deve diventare `⛔`.
- [ ] **Righe lunghe leggibili.** I motivi sono frasi intere: verifica che la label del
      verdetto vada a capo invece di troncare, alle risoluzioni che usi davvero.
- [ ] **Stessa risposta dall'assistente.** Chiedi all'assistente di provare lo stesso
      messaggio bloccato da una condizione: deve dare **lo stesso motivo** della GUI, con la
      condizione nominata. *(Nota: nel «🩺 perché è stato scartato?» — che legge il diario —
      lo scarto per condizioni appare ancora come `NO_CONTENT_MATCH`: il codice nuovo è di
      sola diagnosi e il diario non è stato toccato. Per distinguere, riprova il messaggio.)*

## G. Simulazione XTrader

- [ ] Eseguita la procedura `xtrader_simulation_test.md` con XTrader in **Modalità
      Simulazione**, stake basso, limiti chiari. Esito atteso raggiunto.

## I. Disaster recovery / resilienza (#109 · #110) — manuale Windows

Passi **manuali** non automatizzabili in CI, riferiti dalla matrice
`archive/resilience_110_matrix.md` (voci 1, 15-19). **Attenzione alla modalità**: in **DRY_RUN**
il CSV operativo NON viene scritto (`live_guard` → `DRY_RUN`), quindi gli scenari che
devono produrre una riga attiva (power-cut, XTrader) vanno eseguiti in **modalità REALE
con XTrader in *Modalità Simulazione*** e stake basso/limiti chiari; gli scenari di sola
rete/auto-start possono restare in DRY_RUN.

- [ ] **#110/1 — Cleanup CSV stantio all'avvio PRIMA dell'auto-start.** Con
      `auto_start_listener=true` e una riga ATTIVA lasciata nel CSV (es. da una sessione
      precedente: scrivila in modalità REALE+Simulazione, oppure incollala a mano), chiudi
      e RIAPRI l'app. Atteso: all'avvio il CSV è riportato a **solo header** PRIMA che
      l'auto-start del listener parta — il log mostra il cleanup all'avvio e nessuna riga
      orfana viene presentata a XTrader, anche con auto-start attivo.
- [ ] **#110/17 — Power-cut con CSV attivo.** *(modalità REALE + XTrader in Simulazione,
      stake basso — in DRY_RUN il CSV non verrebbe scritto e lo scenario non sarebbe
      esercitato.)* Fai scrivere un segnale nel CSV, poi spegni brutalmente VM/PC (o
      `kill -9`). Riapri l'app. Atteso: CSV a **solo header** PRIMA di START (nessuna riga
      orfana); il log segnala il cleanup all'avvio. **Dedupe/daily dopo il crash sono
      best-effort**: il duplicato recente è riconosciuto e il daily count è preservato
      **solo se lo stato guard era stato persistito prima del crash**; un crash nella
      finestra stretta "write CSV riuscita → prima di `_save_guard_state`" può far
      dimenticare quel segnale (vedi `archive/resilience_110_matrix.md` #110/10) — è un fail-safe
      accettato, non una garanzia di "exactly-once". Per un check deterministico del
      dedupe, fai prima arrivare un 2° segnale (così lo stato viene salvato) e poi togli
      la corrente.
- [ ] **#110/15 — START con CSV lockato (file-lock).** *(modalità REALE o DRY_RUN: serve
      solo che `init_csv` non possa scrivere.)* Apri il CSV in Excel/XTrader in modo
      **lockante** (o togli i permessi di scrittura), poi premi **AVVIA**. Atteso: l'avvio
      **fallisce in modo pulito** (log con l'errore di `init_csv`), lo stato resta
      **OFFLINE** e il listener NON parte (nessuna sessione "attiva" falsa). Se il lock
      arriva a runtime, il log segnala l'errore e l'auto-clear riprova (retry).
- [ ] **#110/18 — Telegram live outage / reconnect.** *(DRY_RUN va bene: non serve
      scrivere il CSV.)* Avvia il listener, stacca la rete ~5 min e invia segnali nel
      canale mentre è offline; riattacca la rete. Atteso: stato **RICONNESSIONE…** con
      backoff. Nota: a ogni riconnessione il polling usa `drop_pending_updates=True`,
      quindi **l'intero backlog accumulato offline viene SCARTATO** (non filtrato per età):
      i messaggi inviati mentre la rete era giù **non** vengono processati. Solo i
      messaggi inviati **dopo** la riconnessione (e comunque entro `max_signal_age`)
      passano. **Verifica di ripresa**: dopo che lo stato torna **CONNESSO**, invia UN
      segnale valido NUOVO e conferma che viene **processato** entro `max_signal_age`
      (così il test non passa anche se il listener non riprendesse a processare).
- [ ] **#110/16 — Windows reboot + auto-start.** Configura l'app in Startup
      folder / Task Scheduler con `auto_start_listener=true`. Caso **DRY_RUN**:
      riavvia il PC → l'app parte, il listener parte da solo, il CSV è pulito.
      Caso **REALE**: riavvia → l'app parte e **chiede conferma**; senza click non
      scrive nulla.
- [ ] **#110/19 — XTrader sandbox (lettura singola).** *(modalità REALE + XTrader in
      *Modalità Simulazione*, stake basso: serve una riga reale nel CSV perché XTrader la
      legga.)* Refresh automatico attivo, CSV path reale. Fai arrivare un segnale valido:
      XTrader lo legge **una sola volta**; allo scadere del timeout il CSV torna a solo
      header; riavviando XTrader non rilegge segnali vecchi; il file non resta lockato.

## H. Rilascio

- [ ] Tag `v<versione>` creato (la release pubblica parte solo su tag).
- [ ] Note di release scritte (cosa cambia, limiti noti, avviso simulazione).
- [ ] Merge eseguito **manualmente** dal proprietario.

> Promemoria: nessuna promessa di profitto. Prima dell'uso reale, sempre simulazione,
> stake basso, limiti chiari, consapevolezza del rischio.
